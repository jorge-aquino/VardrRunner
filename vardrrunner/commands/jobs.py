"""
Job queue commands: list pending jobs and run them locally.

The UI creates job records; VardrRunner polls /jobs/pending, executes
the tool locally, and uploads results via the existing import endpoint.
"""

import json

import typer
from rich.console import Console
from rich.table import Table

from vardrrunner import api, config, configs, runner
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
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Tool", style="bold")
    table.add_column("Source")
    table.add_column("Config", style="dim")
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


def _fail_job(client: api.VardrMapClient, con: Console, job_id: str, error: str) -> None:
    """Mark a job failed and emit the matching event — the single failure path."""
    con.print(f"[red]Job failed:[/red] {error}")
    client.complete_job(job_id, "failed", error=error[:500])
    _emit(client, job_id, "failed", error[:500])


def execute_pending_jobs(
    client: api.VardrMapClient,
    con: Console,
    yes: bool = True,
) -> int:
    """Claim and execute all pending jobs. Returns the number of jobs found (0 if queue empty)."""
    jobs_list = client.pending_jobs()
    if not jobs_list:
        return 0

    con.print(f"Found [bold]{len(jobs_list)}[/bold] pending job(s).")

    for job in jobs_list:
        job_id = job["id"]
        tool_type = job["tool_type"]
        target_src = job["target_source"]
        program_id = job["program_id"]
        cfg = job.get("config") or {}

        con.rule(f"Job {job_id[:8]}… — {tool_type} / {target_src}")

        # Validate tool is installed before claiming
        if not runner.tool_available(tool_type):
            con.print(f"[red]'{tool_type}' not found on PATH — marking job failed.[/red]")
            error = f"'{tool_type}' not found on PATH"
            client.complete_job(job_id, "failed", error=error)
            _emit(client, job_id, "failed", error)
            continue

        # ── subfinder: wildcard domain resolution + plain-text → JSONL upload ──
        if tool_type == "subfinder":
            try:
                sf_cfg = configs.SubfinderConfig.from_dict(cfg)
            except configs.ConfigError as e:
                _fail_job(client, con, job_id, f"invalid config: {e}")
                continue
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
                con.print("[yellow]No wildcard scope entries — marking job as done.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "no wildcard scope entries")
                continue

            _confirm(domains, tool_type, yes)

            try:
                client.claim_job(job_id)
            except Exception as e:
                con.print(f"[red]Could not claim job:[/red] {e}")
                continue

            _emit(client, job_id, "started", f"claimed job · {len(domains)} domain(s) to enumerate")
            _emit(
                client, job_id, "targets_resolved", f"{len(domains)} wildcard domain(s) from scope"
            )

            run_dir = _make_run_dir()
            sf_output = run_dir / "subfinder.txt"
            con.print(f"Running subfinder… output → [dim]{sf_output}[/dim]")
            _emit(client, job_id, "running", f"running subfinder on {len(domains)} domain(s)")
            try:
                rc = runner.run_subfinder(domains, sf_output, timeout=sf_cfg.timeout)
            except runner.ToolTimeout as e:
                con.print(f"[red]Job failed:[/red] {e}")
                client.complete_job(job_id, "failed", error=str(e)[:500])
                _emit(client, job_id, "failed", str(e)[:500])
                continue
            if rc != 0:
                con.print(f"[yellow]subfinder exited with code {rc}[/yellow]")

            if not sf_output.exists() or sf_output.stat().st_size == 0:
                con.print("[yellow]No subdomains discovered.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "subfinder found no subdomains")
                continue

            hosts = [ln.strip() for ln in sf_output.read_text().splitlines() if ln.strip()]
            con.print(f"Discovered [bold]{len(hosts)}[/bold] subdomain(s).")

            jsonl_path = run_dir / "subfinder_httpx.jsonl"
            with jsonl_path.open("w") as fh:
                for host in hosts:
                    fh.write(json.dumps({"host": host, "source": "subfinder"}) + "\n")

            con.print("Uploading as httpx recon targets…")
            try:
                result = client.import_file(program_id, "httpx", str(jsonl_path))
                count = result.get("import_record", {}).get("imported_count", "?")
                con.print(f"[green]Done.[/green] Imported {count} host(s) as recon targets.")
                _emit(client, job_id, "uploaded", f"imported {count} subdomain(s) as recon targets")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done")
            except Exception as e:
                error_msg = str(e)
                con.print(f"[red]Upload failed:[/red] {error_msg}")
                client.complete_job(job_id, "failed", error=error_msg[:500])
                _emit(client, job_id, "failed", error_msg[:500])
            continue

        # ── nmap: service discovery — XML output → services API ──────────────
        if tool_type == "nmap":
            try:
                nm_cfg = configs.NmapConfig.from_dict(cfg)
            except configs.ConfigError as e:
                _fail_job(client, con, job_id, f"invalid config: {e}")
                continue
            try:
                targets = _resolve_targets(
                    client=client,
                    program_id=program_id,
                    scope=(target_src == "scope"),
                    from_recon=(target_src == "recon"),
                    target=None,
                    targets_file=None,
                    status_code=None,
                    limit=nm_cfg.limit,
                )
            except SystemExit:
                error = "Failed to resolve targets"
                client.complete_job(job_id, "failed", error=error)
                _emit(client, job_id, "failed", error)
                continue

            if not targets:
                con.print("[yellow]No targets resolved — marking job as done.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", "no targets resolved")
                continue

            _confirm(targets, tool_type, yes)

            try:
                client.claim_job(job_id)
            except Exception as e:
                con.print(f"[red]Could not claim job:[/red] {e}")
                continue

            _emit(
                client,
                job_id,
                "started",
                f"claimed job · {len(targets)} target(s) from {target_src}",
            )
            _emit(client, job_id, "targets_resolved", f"{len(targets)} target(s) from {target_src}")

            top_ports = nm_cfg.top_ports
            timing = nm_cfg.timing
            run_dir = _make_run_dir()
            xml_path = run_dir / "nmap.xml"

            nmap_targets = [runner.strip_url_to_host(t) for t in targets if t.strip()]
            nmap_targets = list(dict.fromkeys(nmap_targets))

            con.print(
                f"Running nmap (--top-ports {top_ports} -T{timing})… output → [dim]{xml_path}[/dim]"
            )
            _emit(
                client,
                job_id,
                "running",
                f"running nmap --top-ports {top_ports} against {len(nmap_targets)} target(s)",
            )

            try:
                rc = runner.run_nmap(
                    nmap_targets,
                    xml_path,
                    top_ports=top_ports,
                    timing=timing,
                    timeout=nm_cfg.timeout,
                )
                if rc != 0:
                    con.print(f"[yellow]nmap exited with code {rc}[/yellow]")

                if not xml_path.exists() or xml_path.stat().st_size == 0:
                    con.print("[yellow]No nmap output produced.[/yellow]")
                    client.complete_job(job_id, "done")
                    _emit(client, job_id, "done", "nmap produced no output")
                    continue

                services = runner.parse_nmap_xml(xml_path)
                con.print(f"Parsed [bold]{len(services)}[/bold] open port(s).")

                if services:
                    result = client.create_services(program_id, services)
                    created = result.get("created", 0)
                    updated = result.get("updated", 0)
                    con.print(f"[green]Done.[/green] {created} new, {updated} updated service(s).")
                    _emit(
                        client, job_id, "uploaded", f"{created} new, {updated} updated service(s)"
                    )
                else:
                    con.print("[yellow]No open ports found.[/yellow]")
                    _emit(client, job_id, "uploaded", "no open ports found")

                client.complete_job(job_id, "done")
                _emit(client, job_id, "done")

            except Exception as e:
                error_msg = str(e)
                con.print(f"[red]Job failed:[/red] {error_msg}")
                client.complete_job(job_id, "failed", error=error_msg[:500])
                _emit(client, job_id, "failed", error_msg[:500])
            continue

        # ── httpx / nuclei: shared target resolution ──────────────────────────
        try:
            hn_cfg: configs.HttpxConfig | configs.NucleiConfig = (
                configs.HttpxConfig.from_dict(cfg)
                if tool_type == "httpx"
                else configs.NucleiConfig.from_dict(cfg)
            )
        except configs.ConfigError as e:
            _fail_job(client, con, job_id, f"invalid config: {e}")
            continue
        try:
            targets = _resolve_targets(
                client=client,
                program_id=program_id,
                scope=(target_src == "scope"),
                from_recon=(target_src == "recon"),
                target=None,
                targets_file=None,
                status_code=hn_cfg.status_code,
                limit=hn_cfg.limit,
            )
        except SystemExit:
            error = "Failed to resolve targets"
            client.complete_job(job_id, "failed", error=error)
            _emit(client, job_id, "failed", error)
            continue

        if not targets:
            con.print("[yellow]No targets resolved — marking job as done.[/yellow]")
            client.complete_job(job_id, "done")
            _emit(client, job_id, "done", "no targets resolved")
            continue

        _confirm(targets, tool_type, yes)

        try:
            client.claim_job(job_id)
        except Exception as e:
            con.print(f"[red]Could not claim job:[/red] {e}")
            continue

        _emit(
            client, job_id, "started", f"claimed job · {len(targets)} target(s) from {target_src}"
        )
        _emit(client, job_id, "targets_resolved", f"{len(targets)} target(s) from {target_src}")

        run_dir = _make_run_dir()
        error_msg = ""
        try:
            if tool_type == "httpx":
                output = run_dir / "httpx.jsonl"
                con.print(f"Running httpx… output → [dim]{output}[/dim]")
                _emit(client, job_id, "running", f"running httpx against {len(targets)} target(s)")
                rc = runner.run_httpx(targets, output, timeout=hn_cfg.timeout)
            else:  # nuclei
                assert isinstance(hn_cfg, configs.NucleiConfig)
                output = run_dir / "nuclei.jsonl"
                severity = hn_cfg.severity
                label = f"severity={severity}" if severity else "all"
                con.print(f"Running nuclei ({label})… output → [dim]{output}[/dim]")
                _emit(
                    client,
                    job_id,
                    "running",
                    f"running nuclei ({label}) against {len(targets)} target(s)",
                )
                rc = runner.run_nuclei(
                    targets,
                    output,
                    severity=severity,
                    templates=hn_cfg.templates,
                    timeout=hn_cfg.timeout,
                )

            if rc != 0:
                con.print(f"[yellow]{tool_type} exited with code {rc}[/yellow]")

            if not output.exists() or output.stat().st_size == 0:
                con.print("[yellow]No output produced — nothing to import.[/yellow]")
                client.complete_job(job_id, "done")
                _emit(client, job_id, "done", f"{tool_type} produced no output")
                continue

            con.print("Uploading results…")
            result = client.import_file(program_id, tool_type, str(output))
            count = result.get("import_record", {}).get("imported_count", "?")
            con.print(f"[green]Done.[/green] Imported {count} result(s).")
            _emit(client, job_id, "uploaded", f"imported {count} result(s)")
            client.complete_job(job_id, "done")
            _emit(client, job_id, "done")

        except Exception as e:
            error_msg = str(e)
            con.print(f"[red]Job failed:[/red] {error_msg}")
            client.complete_job(job_id, "failed", error=error_msg[:500])
            _emit(client, job_id, "failed", error_msg[:500])

    return len(jobs_list)


def run_jobs(yes: bool = False) -> None:
    """Claim and execute all pending jobs for the authenticated user."""
    send_heartbeat(quiet=True)
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)
    executed = execute_pending_jobs(client, console, yes=yes)
    if executed == 0:
        console.print("[dim]No pending jobs.[/dim]")
        raise typer.Exit(0)
