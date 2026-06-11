"""
Job queue commands: list pending jobs and run them locally.

The UI creates job records; VardrRunner polls /jobs/pending, executes
the tool locally, and uploads results via the existing import endpoint.
"""
import datetime
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from vardrrunner import api, config, runner
from vardrrunner.commands.heartbeat import send_heartbeat
from vardrrunner.commands.run import _confirm, _is_wildcard, _make_run_dir, _resolve_targets

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


def _emit(client: api.VardrMapClient, job_id: str, kind: str, text: str = "") -> None:
    """Post a job event; swallow errors so a failed event never kills the job loop."""
    try:
        client.post_event(job_id, kind, text)
    except Exception:
        pass


def run_jobs(yes: bool = False) -> None:
    """Claim and execute all pending jobs for the authenticated user."""
    # Report runner status so the Bridge shows this machine as online
    send_heartbeat(quiet=True)

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
            error = f"'{tool_type}' not found on PATH"
            client.complete_job(job_id, "failed", error=error)
            _emit(client, job_id, "failed", error)
            continue

        # ── subfinder: wildcard domain resolution + plain-text → JSONL upload ──
        if tool_type == "subfinder":
            try:
                raw = client.scope(program_id)
                domains = []
                for item in raw.get("in", []):
                    val = item.get("value", "")
                    if _is_wildcard(val):
                        stripped = val.lstrip("*").lstrip(".")
                        if stripped:
                            domains.append(stripped)
            except Exception:
                error = "Failed to resolve scope"
                client.complete_job(job_id, "failed", error=error)
                _emit(client, job_id, "failed", error)
                continue

            if not domains:
                console.print("[yellow]No wildcard scope entries — marking job as done.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "no wildcard scope entries")
                continue

            _confirm(domains, tool_type, yes)

            try:
                client.claim_job(job_id)
            except Exception as e:
                console.print(f"[red]Could not claim job:[/red] {e}")
                continue

            _emit(client, job_id, "started", f"claimed job · {len(domains)} domain(s) to enumerate")
            _emit(client, job_id, "targets_resolved", f"{len(domains)} wildcard domain(s) from scope")

            run_dir   = _make_run_dir()
            sf_output = run_dir / "subfinder.txt"
            console.print(f"Running subfinder… output → [dim]{sf_output}[/dim]")
            _emit(client, job_id, "running", f"running subfinder on {len(domains)} domain(s)")
            rc = runner.run_subfinder(domains, sf_output)
            if rc != 0:
                console.print(f"[yellow]subfinder exited with code {rc}[/yellow]")

            if not sf_output.exists() or sf_output.stat().st_size == 0:
                console.print("[yellow]No subdomains discovered.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "subfinder found no subdomains")
                continue

            hosts = [ln.strip() for ln in sf_output.read_text().splitlines() if ln.strip()]
            console.print(f"Discovered [bold]{len(hosts)}[/bold] subdomain(s).")

            jsonl_path = run_dir / "subfinder_httpx.jsonl"
            with jsonl_path.open("w") as fh:
                for host in hosts:
                    fh.write(json.dumps({"host": host, "source": "subfinder"}) + "\n")

            console.print("Uploading as httpx recon targets…")
            try:
                result = client.import_file(program_id, "httpx", str(jsonl_path))
                count  = result.get("import_record", {}).get("imported_count", "?")
                console.print(f"[green]Done.[/green] Imported {count} host(s) as recon targets.")
                _emit(client, job_id, "uploaded", f"imported {count} subdomain(s) as recon targets")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done")
            except Exception as e:
                error_msg = str(e)
                console.print(f"[red]Upload failed:[/red] {error_msg}")
                client.complete_job(job_id, "failed", error=error_msg[:500])
                _emit(client, job_id, "failed", error_msg[:500])
            continue

        # ── nmap: service discovery — XML output → services API ─────────────────
        if tool_type == "nmap":
            try:
                status_code_filter: Optional[int] = None
                limit_n: int = int(cfg.get("limit", 500))
                targets = _resolve_targets(
                    client=client,
                    program_id=program_id,
                    scope=(target_src == "scope"),
                    from_recon=(target_src == "recon"),
                    target=None,
                    targets_file=None,
                    status_code=status_code_filter,
                    limit=limit_n,
                )
            except SystemExit:
                error = "Failed to resolve targets"
                client.complete_job(job_id, "failed", error=error)
                _emit(client, job_id, "failed", error)
                continue

            if not targets:
                console.print("[yellow]No targets resolved — marking job as done.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "no targets resolved")
                continue

            _confirm(targets, tool_type, yes)

            try:
                client.claim_job(job_id)
            except Exception as e:
                console.print(f"[red]Could not claim job:[/red] {e}")
                continue

            _emit(client, job_id, "started", f"claimed job · {len(targets)} target(s) from {target_src}")
            _emit(client, job_id, "targets_resolved", f"{len(targets)} target(s) from {target_src}")

            top_ports = int(cfg.get("top_ports", 100))
            timing    = int(cfg.get("timing", 3))
            run_dir   = _make_run_dir()
            xml_path  = run_dir / "nmap.xml"

            console.print(f"Running nmap (--top-ports {top_ports} -T{timing})… output → [dim]{xml_path}[/dim]")
            _emit(client, job_id, "running", f"running nmap --top-ports {top_ports} against {len(targets)} target(s)")

            try:
                rc = runner.run_nmap(targets, xml_path, top_ports=top_ports, timing=timing)
                if rc != 0:
                    console.print(f"[yellow]nmap exited with code {rc}[/yellow]")

                if not xml_path.exists() or xml_path.stat().st_size == 0:
                    console.print("[yellow]No nmap output produced.[/yellow]")
                    client.complete_job(job_id, "done")
                    _emit(client, job_id, "done", "nmap produced no output")
                    continue

                services = runner.parse_nmap_xml(xml_path)
                console.print(f"Parsed [bold]{len(services)}[/bold] open port(s).")

                if services:
                    result = client.create_services(program_id, services)
                    created = result.get("created", 0)
                    updated = result.get("updated", 0)
                    console.print(f"[green]Done.[/green] {created} new, {updated} updated service(s).")
                    _emit(client, job_id, "uploaded", f"{created} new, {updated} updated service(s)")
                else:
                    console.print("[yellow]No open ports found.[/yellow]")
                    _emit(client, job_id, "uploaded", "no open ports found")

                client.complete_job(job_id, "done")
                _emit(client, job_id, "done")

            except Exception as e:
                error_msg = str(e)
                console.print(f"[red]Job failed:[/red] {error_msg}")
                client.complete_job(job_id, "failed", error=error_msg[:500])
                _emit(client, job_id, "failed", error_msg[:500])
            continue

        # ── httpx / nuclei: shared target resolution ────────────────────────────
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
            error = "Failed to resolve targets"
            client.complete_job(job_id, "failed", error=error)
            _emit(client, job_id, "failed", error)
            continue

        if not targets:
            console.print("[yellow]No targets resolved — marking job as done.[/yellow]")
            client.complete_job(job_id, "done")
            _emit(client, job_id, "done", "no targets resolved")
            continue

        _confirm(targets, tool_type, yes)

        # Claim the job
        try:
            client.claim_job(job_id)
        except Exception as e:
            console.print(f"[red]Could not claim job:[/red] {e}")
            continue

        _emit(client, job_id, "started", f"claimed job · {len(targets)} target(s) from {target_src}")
        _emit(client, job_id, "targets_resolved", f"{len(targets)} target(s) from {target_src}")

        run_dir = _make_run_dir()
        error_msg = ""
        try:
            if tool_type == "httpx":
                output = run_dir / "httpx.jsonl"
                console.print(f"Running httpx… output → [dim]{output}[/dim]")
                _emit(client, job_id, "running", f"running httpx against {len(targets)} target(s)")
                rc = runner.run_httpx(targets, output)
            else:  # nuclei
                output = run_dir / "nuclei.jsonl"
                severity     = cfg.get("severity")
                raw_templates = cfg.get("templates")
                # templates config is a comma-separated string from the UI (e.g. "cves,exposures");
                # guard against a list in case it arrives that way from older clients
                templates = (
                    ",".join(raw_templates) if isinstance(raw_templates, list)
                    else (raw_templates or None)
                )
                label = f"severity={severity}" if severity else "all"
                console.print(f"Running nuclei ({label})… output → [dim]{output}[/dim]")
                _emit(client, job_id, "running", f"running nuclei ({label}) against {len(targets)} target(s)")
                rc = runner.run_nuclei(targets, output, severity=severity, templates=templates)

            if rc != 0:
                console.print(f"[yellow]{tool_type} exited with code {rc}[/yellow]")

            if not output.exists() or output.stat().st_size == 0:
                console.print("[yellow]No output produced — nothing to import.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", f"{tool_type} produced no output")
                continue

            console.print("Uploading results…")
            result = client.import_file(program_id, tool_type, str(output))
            count  = result.get("import_record", {}).get("imported_count", "?")
            console.print(f"[green]Done.[/green] Imported {count} result(s).")
            _emit(client, job_id, "uploaded", f"imported {count} result(s)")
            client.complete_job(job_id, "done")
            _emit(client, job_id, "done")

        except Exception as e:
            error_msg = str(e)
            console.print(f"[red]Job failed:[/red] {error_msg}")
            client.complete_job(job_id, "failed", error=error_msg[:500])
            _emit(client, job_id, "failed", error_msg[:500])
