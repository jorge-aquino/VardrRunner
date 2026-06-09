"""
Run a tool against targets fetched from VardrMap, then upload the results.
Tools execute locally — scan traffic comes from the user's machine.
"""
import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vardrrunner import api, config, runner

console = Console()

# Wildcard prefixes we refuse to scan directly.
_WILDCARD_PREFIXES = ("*.", "*")


def _is_wildcard(value: str) -> bool:
    return any(value.startswith(p) for p in _WILDCARD_PREFIXES)


def _make_run_dir() -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = config.runs_dir() / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _resolve_targets(
    client: api.VardrMapClient,
    program_id: str,
    scope: bool,
    from_recon: bool,
    target: Optional[str],
    targets_file: Optional[Path],
    status_code: Optional[int],
    limit: int,
) -> list[str]:
    """Collect the target list from the chosen source."""
    if target:
        return [target]

    if targets_file:
        if not targets_file.exists():
            console.print(f"[red]File not found:[/red] {targets_file}")
            raise typer.Exit(1)
        return [line.strip() for line in targets_file.read_text().splitlines() if line.strip()]

    if scope:
        raw = client.scope(program_id)
        in_scope = raw.get("in", [])
        resolved, skipped = [], []
        for item in in_scope:
            val = item.get("value", "")
            if _is_wildcard(val):
                skipped.append(val)
            else:
                resolved.append(val)
        if skipped:
            console.print("[yellow]Skipping wildcards (run subfinder first to enumerate hosts):[/yellow]")
            for s in skipped:
                console.print(f"  [dim]skip:[/dim] {s}")
        return resolved

    if from_recon:
        items = client.recon(program_id, limit=limit, status_code=status_code)
        targets = []
        for item in items:
            val = item.get("url") or item.get("host")
            if val:
                targets.append(val)
        return targets

    console.print("[red]No target source specified.[/red] Use --scope, --from-recon, --target, or --targets.")
    raise typer.Exit(1)


def _confirm(targets: list[str], tool: str, yes: bool) -> None:
    """Show a dry-run preview and ask for confirmation unless --yes is passed."""
    console.print(f"\n[bold]Targets ({len(targets)}):[/bold]")
    preview = targets[:10]
    for t in preview:
        console.print(f"  {t}")
    if len(targets) > 10:
        console.print(f"  [dim]… and {len(targets) - 10} more[/dim]")

    if not yes:
        confirmed = typer.confirm(f"\nRun {tool} against {len(targets)} target(s)?", default=False)
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)


def run_httpx(
    program_id: str,
    scope: bool      = False,
    from_recon: bool = False,
    target: Optional[str]  = None,
    targets_file: Optional[Path] = None,
    limit: int       = 100,
    status_code: Optional[int]  = None,
    yes: bool        = False,
):
    """Run httpx and upload results to VardrMap."""
    runner.check_tool("httpx")
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)

    targets = _resolve_targets(client, program_id, scope, from_recon, target, targets_file, status_code, limit)
    if not targets:
        console.print("[yellow]No targets found.[/yellow]")
        raise typer.Exit(0)

    _confirm(targets, "httpx", yes)

    run_dir = _make_run_dir()
    output  = run_dir / "httpx.jsonl"
    console.print(f"\nRunning httpx… output → [dim]{output}[/dim]")

    rc = runner.run_httpx(targets, output)
    if rc != 0:
        console.print(f"[yellow]httpx exited with code {rc}[/yellow]")

    if not output.exists() or output.stat().st_size == 0:
        console.print("[yellow]No output produced — nothing to import.[/yellow]")
        raise typer.Exit(0)

    console.print("Uploading results…")
    try:
        result = client.import_file(program_id, "httpx", str(output))
        count  = result.get("import_record", {}).get("imported_count", "?")
        console.print(f"[green]Done.[/green] Imported {count} result(s).")
    except Exception as e:
        console.print(f"[red]Upload failed:[/red] {e}")
        console.print(f"Raw output saved at [dim]{output}[/dim]")
        raise typer.Exit(1)


def run_subfinder(
    program_id: str,
    yes: bool = False,
):
    """Run subfinder against wildcard scope entries and upload results as recon (httpx targets)."""
    runner.check_tool("subfinder")
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)

    raw = client.scope(program_id)
    in_scope = raw.get("in", [])

    # Extract root domains from wildcard entries like *.example.com → example.com
    domains = []
    for item in in_scope:
        val = item.get("value", "")
        if _is_wildcard(val):
            stripped = val.lstrip("*").lstrip(".")
            if stripped:
                domains.append(stripped)

    if not domains:
        console.print("[yellow]No wildcard scope entries found.[/yellow]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Wildcard domains ({len(domains)}):[/bold]")
    for d in domains:
        console.print(f"  {d}")

    if not yes:
        confirmed = typer.confirm(f"\nRun subfinder against {len(domains)} domain(s)?", default=False)
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    run_dir = _make_run_dir()
    output  = run_dir / "subfinder.txt"
    console.print(f"\nRunning subfinder… output → [dim]{output}[/dim]")

    rc = runner.run_subfinder(domains, output)
    if rc != 0:
        console.print(f"[yellow]subfinder exited with code {rc}[/yellow]")

    if not output.exists() or output.stat().st_size == 0:
        console.print("[yellow]No subdomains discovered.[/yellow]")
        raise typer.Exit(0)

    hosts = [line.strip() for line in output.read_text().splitlines() if line.strip()]
    console.print(f"Discovered [bold]{len(hosts)}[/bold] subdomain(s).")

    # Convert plain hosts to httpx-compatible JSONL for import
    import json as _json
    jsonl_path = run_dir / "subfinder_httpx.jsonl"
    with jsonl_path.open("w") as fh:
        for host in hosts:
            fh.write(_json.dumps({"host": host, "source": "subfinder"}) + "\n")

    console.print("Uploading as httpx recon targets…")
    try:
        result = client.import_file(program_id, "httpx", str(jsonl_path))
        count  = result.get("import_record", {}).get("imported_count", "?")
        console.print(f"[green]Done.[/green] Imported {count} host(s) as recon targets.")
    except Exception as e:
        console.print(f"[red]Upload failed:[/red] {e}")
        console.print(f"Raw output saved at [dim]{output}[/dim]")
        raise typer.Exit(1)


def run_nuclei(
    program_id: str,
    scope: bool      = False,
    from_recon: bool = False,
    target: Optional[str]  = None,
    targets_file: Optional[Path] = None,
    limit: int       = 100,
    status_code: Optional[int]  = None,
    severity: Optional[str]     = None,
    templates: Optional[str]    = None,
    yes: bool        = False,
):
    """Run nuclei and upload results to VardrMap."""
    runner.check_tool("nuclei")
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)

    targets = _resolve_targets(client, program_id, scope, from_recon, target, targets_file, status_code, limit)
    if not targets:
        console.print("[yellow]No targets found.[/yellow]")
        raise typer.Exit(0)

    _confirm(targets, "nuclei", yes)

    run_dir = _make_run_dir()
    output  = run_dir / "nuclei.jsonl"
    label   = f"severity={severity}" if severity else "all severities"
    console.print(f"\nRunning nuclei ({label})… output → [dim]{output}[/dim]")

    rc = runner.run_nuclei(targets, output, severity=severity, templates=templates)
    if rc != 0:
        console.print(f"[yellow]nuclei exited with code {rc}[/yellow]")

    if not output.exists() or output.stat().st_size == 0:
        console.print("[yellow]No findings produced — nothing to import.[/yellow]")
        raise typer.Exit(0)

    console.print("Uploading results…")
    try:
        result = client.import_file(program_id, "nuclei", str(output))
        count  = result.get("import_record", {}).get("imported_count", "?")
        console.print(f"[green]Done.[/green] Imported {count} finding(s).")
    except Exception as e:
        console.print(f"[red]Upload failed:[/red] {e}")
        console.print(f"Raw output saved at [dim]{output}[/dim]")
        raise typer.Exit(1)
