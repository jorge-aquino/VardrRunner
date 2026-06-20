"""
Pipeline commands — run a chain of tools as one recon workflow.

Each pipeline run gets a short UUID run ID printed at the start and end so
operators can cross-reference logs. Targets flow locally between stages via a
handoff file: after each stage completes, its discovered targets (hosts or URLs)
are written to a plain-text file in the stage's run directory. The next stage
reads from that file instead of the shared backend recon store, so no stale recon
from prior runs can contaminate the pipeline.

Fallback: if a stage produces no parseable handoff targets (e.g. nuclei, nmap)
the next stage falls back to the backend recon store as before — preserving the
original behaviour for terminal tools and for the direct `run` commands.
"""

import uuid
from pathlib import Path

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

    if severity:
        try:
            configs.NucleiConfig.from_dict({"severity": severity})
        except configs.ConfigError as e:
            console.print(f"[red]Invalid --severity:[/red] {e}")
            raise typer.Exit(1) from e

    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)

    missing = sorted({s.tool for s in stages if not runner.tool_available(s.tool)})
    if missing:
        console.print(f"[red]Missing tools:[/red] {', '.join(missing)} — install them and retry.")
        raise typer.Exit(1)

    run_id = uuid.uuid4().hex[:8]
    chain = " → ".join(s.tool for s in stages)
    console.print(
        f"\n[bold]Pipeline '{name}'[/bold]: {chain}  "
        f"(program {program_id}  run [dim]{run_id}[/dim])"
    )
    if not yes and not typer.confirm("Run this pipeline?", default=False):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    total = len(stages)
    handoff_path: Path | None = None
    for i, stage in enumerate(stages, 1):
        console.rule(f"Stage {i}/{total} — {stage.tool} (from {stage.source})")
        should_continue, handoff_path = _run_stage(
            client, stage, program_id, severity, continue_on_error, handoff_path
        )
        if not should_continue:
            break

    console.print(f"\n[green]Pipeline complete.[/green] Run ID: [dim]{run_id}[/dim]")


def _run_stage(
    client: api.VardrMapClient,
    stage: pipelines.Stage,
    program_id: str,
    severity: str | None,
    continue_on_error: bool,
    handoff_path: Path | None = None,
) -> tuple[bool, Path | None]:
    """Run one pipeline stage. Returns (should_continue, handoff_file_for_next_stage)."""
    handler = handlers.REGISTRY[stage.tool]
    cfg = {"severity": severity} if (stage.tool == "nuclei" and severity) else {}
    config_obj = handler.parse_config(cfg)

    # Target resolution: prefer the previous stage's local handoff over the shared
    # backend recon store so stale data from earlier pipeline runs can't contaminate
    # this one. Fall back to backend resolution when no handoff is available.
    if handoff_path is not None and stage.source == "recon" and handoff_path.exists():
        raw = [t for t in handoff_path.read_text().splitlines() if t.strip()]
        targets = handler.normalize_handoff_targets(raw)
        console.print(
            f"[dim]Using {len(targets)} target(s) handed off from the previous stage.[/dim]"
        )
    else:
        try:
            targets = handler.resolve_targets(client, program_id, stage.source, config_obj)
        except Exception as e:
            console.print(f"[red]Target resolution failed:[/red] {e}")
            return continue_on_error, None

    if not targets:
        console.print("[yellow]No targets for this stage — stopping pipeline.[/yellow]")
        return False, None

    console.print(
        f"{len(targets)} target(s); running {handler.running_label(targets, config_obj)}…"
    )
    run_dir = _make_run_dir()
    try:
        output = handler.execute(targets, run_dir, config_obj)
    except runner.ToolTimeout as e:
        console.print(f"[red]{e}[/red]")
        return continue_on_error, None
    except Exception as e:
        console.print(f"[red]Execution failed:[/red] {e}")
        return continue_on_error, None

    if output is None or not output.exists() or output.stat().st_size == 0:
        console.print("[yellow]No output produced — stopping pipeline.[/yellow]")
        return False, None

    try:
        summary = handler.upload(client, program_id, output)
    except Exception as e:
        console.print(f"[red]Upload failed:[/red] {e}")
        return continue_on_error, None

    console.print(f"[green]Stage done.[/green] {summary}")

    # Extract targets from this stage's output and write a handoff file for the
    # next stage. Terminal tools (nuclei, nmap, naabu) return [] so no handoff is
    # written and the next stage falls back to the backend recon store.
    extracted = handler.extract_handoff_targets(output)
    if extracted:
        next_handoff = run_dir / "handoff.txt"
        next_handoff.write_text("\n".join(extracted))
        console.print(f"[dim]→ {len(extracted)} target(s) queued for next stage.[/dim]")
        return True, next_handoff

    return True, None
