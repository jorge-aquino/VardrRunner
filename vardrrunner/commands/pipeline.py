"""
Pipeline commands — run a chain of tools as one recon workflow.

This reuses the tool-handler registry: each stage resolves targets, executes its
tool, and uploads, with the next stage pulling the prior stage's results from the
backend's recon store. Stages are operator-initiated (no backend job record), so
there's no claim/event lifecycle here — just sequential resolve → run → upload.
"""

import typer
from rich.console import Console

from vardrrunner import api, config, configs, handlers, pipelines, runner
from vardrrunner.commands.run import _make_run_dir

console = Console()


def list_pipelines() -> None:
    """Print the available pipelines and their tool chains."""
    console.print("[bold]Available pipelines[/bold]")
    for name, stages in pipelines.PIPELINES.items():
        chain = " → ".join(s.tool for s in stages)
        console.print(f"  [bold]{name}[/bold]: {chain}")


def run_pipeline(
    name: str,
    program_id: str,
    severity: str | None = None,
    yes: bool = False,
    continue_on_error: bool = False,
) -> None:
    """Run every stage of a pipeline in order against a program."""
    stages = pipelines.PIPELINES.get(name)
    if stages is None:
        available = ", ".join(pipelines.PIPELINES)
        console.print(f"[red]Unknown pipeline {name!r}.[/red] Available: {available}")
        raise typer.Exit(1)

    # Validate the nuclei severity filter once, up front, so we fail before any work.
    if severity:
        try:
            configs.NucleiConfig.from_dict({"severity": severity})
        except configs.ConfigError as e:
            console.print(f"[red]Invalid --severity:[/red] {e}")
            raise typer.Exit(1) from e

    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)

    # Preflight: every tool in the chain must be installed.
    missing = sorted({s.tool for s in stages if not runner.tool_available(s.tool)})
    if missing:
        console.print(f"[red]Missing tools:[/red] {', '.join(missing)} — install them and retry.")
        raise typer.Exit(1)

    chain = " → ".join(s.tool for s in stages)
    console.print(f"\n[bold]Pipeline '{name}'[/bold]: {chain}  (program {program_id})")
    if not yes and not typer.confirm("Run this pipeline?", default=False):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    total = len(stages)
    for i, stage in enumerate(stages, 1):
        console.rule(f"Stage {i}/{total} — {stage.tool} (from {stage.source})")
        if not _run_stage(client, stage, program_id, severity, continue_on_error):
            break

    console.print("\n[green]Pipeline complete.[/green]")


def _run_stage(
    client: api.VardrMapClient,
    stage: pipelines.Stage,
    program_id: str,
    severity: str | None,
    continue_on_error: bool,
) -> bool:
    """Run one stage. Return True to continue the pipeline, False to stop."""
    handler = handlers.REGISTRY[stage.tool]
    cfg = {"severity": severity} if (stage.tool == "nuclei" and severity) else {}
    config_obj = handler.parse_config(cfg)

    try:
        targets = handler.resolve_targets(client, program_id, stage.source, config_obj)
    except Exception as e:
        console.print(f"[red]Target resolution failed:[/red] {e}")
        return continue_on_error

    if not targets:
        console.print("[yellow]No targets for this stage — stopping pipeline.[/yellow]")
        return False

    console.print(
        f"{len(targets)} target(s); running {handler.running_label(targets, config_obj)}…"
    )
    run_dir = _make_run_dir()
    try:
        output = handler.execute(targets, run_dir, config_obj)
    except runner.ToolTimeout as e:
        console.print(f"[red]{e}[/red]")
        return continue_on_error

    if output is None or not output.exists() or output.stat().st_size == 0:
        console.print("[yellow]No output produced — stopping pipeline.[/yellow]")
        return False

    summary = handler.upload(client, program_id, output)
    console.print(f"[green]Stage done.[/green] {summary}")
    return True
