"""
vardrrunner daemon — long-running background worker.

start  : run the job-poll + heartbeat loop (foreground or detached)
stop   : send SIGTERM to a detached daemon
status : show whether a daemon is running
"""
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vardrrunner import api, config
from vardrrunner.commands.heartbeat import send_heartbeat
from vardrrunner.commands.jobs import execute_pending_jobs

console = Console()

PID_FILE = Path.home() / ".vardrrunner.pid"
DEFAULT_LOG = Path.home() / ".vardrrunner.log"


# ── PID helpers ──────────────────────────────────────────────────────────────

def _read_pid() -> Optional[int]:
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ── Commands ─────────────────────────────────────────────────────────────────

def start(
    detach: bool = typer.Option(
        False, "--detach", "-d",
        help="Run in background and write PID to ~/.vardrrunner.pid",
    ),
    poll_interval: int = typer.Option(5, "--poll-interval", help="Seconds between job polls"),
    heartbeat_interval: int = typer.Option(60, "--heartbeat-interval", help="Seconds between heartbeats"),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file",
        help="Append output to file (defaults to ~/.vardrrunner.log when --detach is used)",
    ),
) -> None:
    """Start the daemon: continuously poll for jobs and send heartbeats."""
    if detach:
        _detach(poll_interval=poll_interval, heartbeat_interval=heartbeat_interval, log_file=log_file)
        return

    try:
        config.require_auth()
    except Exception as e:
        console.print(f"[red]Not authenticated:[/red] {e}")
        raise typer.Exit(1)

    out = console
    _fh = None
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _fh = open(log_file, "a", buffering=1)
        out = Console(file=_fh, highlight=False)

    pid = os.getpid()
    PID_FILE.write_text(str(pid))
    out.print(
        f"[green]Daemon started[/green] · PID {pid} "
        f"· poll {poll_interval}s · heartbeat {heartbeat_interval}s"
    )
    out.print("[dim]Press Ctrl+C to stop.[/dim]")

    _stop = threading.Event()

    def _on_signal(sig, _frame):
        out.print(f"\n[yellow]Signal {sig} — finishing current job then stopping…[/yellow]")
        _stop.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Heartbeat runs on its own interval independent of job duration
    def _hb_loop():
        send_heartbeat(quiet=True)
        while not _stop.wait(timeout=heartbeat_interval):
            send_heartbeat(quiet=True)

    hb_thread = threading.Thread(target=_hb_loop, daemon=True, name="vardrrunner-heartbeat")
    hb_thread.start()

    try:
        while not _stop.is_set():
            try:
                url, key = config.require_auth()
                client   = api.VardrMapClient(url, key)
                count    = execute_pending_jobs(client, out)
                if count:
                    out.print(f"[dim]Cycle complete — {count} job(s) executed.[/dim]")
            except Exception as e:
                out.print(f"[red]Poll error:[/red] {e}")
            _stop.wait(timeout=poll_interval)
    finally:
        PID_FILE.unlink(missing_ok=True)
        if _fh:
            _fh.close()
        out.print("[dim]Daemon stopped.[/dim]")


def stop() -> None:
    """Stop a running daemon by sending SIGTERM."""
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No daemon running (no PID file).[/yellow]")
        raise typer.Exit(1)
    if not _process_alive(pid):
        console.print(f"[yellow]PID {pid} is not running — removing stale PID file.[/yellow]")
        PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(1)
    os.kill(pid, signal.SIGTERM)
    console.print(f"[green]Sent SIGTERM to daemon (PID {pid}).[/green]")


def status() -> None:
    """Show whether the daemon is currently running."""
    pid = _read_pid()
    if pid is None:
        console.print("[dim]Daemon not running (no PID file).[/dim]")
        return
    if _process_alive(pid):
        console.print(f"[green]Daemon running[/green] · PID {pid}")
    else:
        console.print(f"[yellow]Stale PID file (process {pid} not found) — cleaning up.[/yellow]")
        PID_FILE.unlink(missing_ok=True)


def _detach(poll_interval: int, heartbeat_interval: int, log_file: Optional[Path]) -> None:
    """Re-launch self without --detach so the child runs as a foreground daemon."""
    exe = shutil.which("vardrrunner") or sys.argv[0]
    if log_file is None:
        log_file = DEFAULT_LOG

    cmd = [
        exe, "daemon", "start",
        "--poll-interval", str(poll_interval),
        "--heartbeat-interval", str(heartbeat_interval),
        "--log-file", str(log_file),
    ]

    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_file, "a")

    proc = subprocess.Popen(
        cmd,
        stdout=fh,
        stderr=fh,
        start_new_session=True,
        close_fds=True,
    )
    console.print(f"[green]Daemon started[/green] · PID {proc.pid} · log {log_file}")
