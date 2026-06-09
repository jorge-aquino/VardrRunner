"""
Job queue commands: list pending jobs and run them locally.

The UI creates job records; VardrRunner polls /jobs/pending, executes
the tool locally, and uploads results via the existing import endpoint.
"""
import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from vardrrunner import api, config, runner
from vardrrunner.commands.run import _confirm, _make_run_dir, _resolve_targets

console = Console()


def list_jobs() -> None:
    """Show all pending scan jobs for the authenticated user."""
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)
    jobs = client.pending_jobs()

    if not jobs:
        console.print("[dim]No pending jobs.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Pending Scan Jobs")
    table.add_column("ID",            style="dim", no_wrap=True)
    table.add_column("Tool",          style="bold")
    table.add_column("Source")
    table.add_column("Config",        style="dim")
    table.add_column("Created")

    for j in jobs:
        cfg_str = "  ".join(f"{k}={v}" for k, v in (j.get("config") or {}).items())
        table.add_row(
            j["id"][:8] + "…",
            j["tool_type"],
            j["target_source"],
            cfg_str or "—",
            j.get("created_at", "")[:16],
        )

    console.print(table)


def run_jobs(yes: bool = False) -> None:
    """Claim and execute all pending jobs for the authenticated user."""
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)
    jobs = client.pending_jobs()

    if not jobs:
        console.print("[dim]No pending jobs.[/dim]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(jobs)}[/bold] pending job(s).")

    for job in jobs:
        job_id      = job["id"]
        tool_type   = job["tool_type"]
        target_src  = job["target_source"]
        program_id  = job["program_id"]
        cfg         = job.get("config") or {}

        console.rule(f"Job {job_id[:8]}… — {tool_type} / {target_src}")

        # Validate tool is installed before claiming
        if not runner.tool_available(tool_type):
            console.print(f"[red]'{tool_type}' not found on PATH — marking job failed.[/red]")
            client.complete_job(job_id, "failed", error=f"'{tool_type}' not found on PATH")
            continue

        # Resolve targets
        try:
            status_code: Optional[int] = cfg.get("status_code")
            limit: int = int(cfg.get("limit", 100))
            targets = _resolve_targets(
                client=client,
                program_id=program_id,
                scope=(target_src == "scope"),
                from_recon=(target_src == "recon"),
                target=None,
                targets_file=None,
                status_code=status_code,
                limit=limit,
            )
        except SystemExit:
            client.complete_job(job_id, "failed", error="Failed to resolve targets")
            continue

        if not targets:
            console.print("[yellow]No targets resolved — marking job as done.[/yellow]")
            client.complete_job(job_id, "done")
            continue

        _confirm(targets, tool_type, yes)

        # Claim the job
        try:
            client.claim_job(job_id)
        except Exception as e:
            console.print(f"[red]Could not claim job:[/red] {e}")
            continue

        run_dir = _make_run_dir()
        error_msg = ""
        try:
            if tool_type == "httpx":
                output = run_dir / "httpx.jsonl"
                severity = None
                templates = None
                console.print(f"Running httpx… output → [dim]{output}[/dim]")
                rc = runner.run_httpx(targets, output)
            else:  # nuclei
                output = run_dir / "nuclei.jsonl"
                severity  = cfg.get("severity")
                templates = ",".join(cfg["templates"]) if cfg.get("templates") else None
                label = f"severity={severity}" if severity else "all"
                console.print(f"Running nuclei ({label})… output → [dim]{output}[/dim]")
                rc = runner.run_nuclei(targets, output, severity=severity, templates=templates)

            if rc != 0:
                console.print(f"[yellow]{tool_type} exited with code {rc}[/yellow]")

            if not output.exists() or output.stat().st_size == 0:
                console.print("[yellow]No output produced — nothing to import.[/yellow]")
                client.complete_job(job_id, "done")
                continue

            console.print("Uploading results…")
            result = client.import_file(program_id, tool_type, str(output))
            count  = result.get("import_record", {}).get("imported_count", "?")
            console.print(f"[green]Done.[/green] Imported {count} result(s).")
            client.complete_job(job_id, "done")

        except Exception as e:
            error_msg = str(e)
            console.print(f"[red]Job failed:[/red] {error_msg}")
            client.complete_job(job_id, "failed", error=error_msg[:500])
