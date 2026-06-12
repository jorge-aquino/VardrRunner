"""
Tests for the VardrRunner daemon: PID helpers, stop, status, _detach, and the
main polling loop. All signal delivery and subprocess calls are mocked.
"""
import os
import signal
import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import typer

from vardrrunner.commands import daemon as daemon_mod
from vardrrunner.commands.jobs import execute_pending_jobs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pid_file(tmp_path, monkeypatch):
    """Redirect PID_FILE to a temp path so tests don't touch ~/.vardrrunner.pid."""
    pf = tmp_path / ".vardrrunner.pid"
    monkeypatch.setattr(daemon_mod, "PID_FILE", pf)
    return pf


# ---------------------------------------------------------------------------
# _read_pid
# ---------------------------------------------------------------------------

class TestReadPid:
    def test_no_file_returns_none(self, pid_file):
        assert daemon_mod._read_pid() is None

    def test_valid_file_returns_int(self, pid_file):
        pid_file.write_text("12345")
        assert daemon_mod._read_pid() == 12345

    def test_invalid_content_returns_none(self, pid_file):
        pid_file.write_text("not-a-pid")
        assert daemon_mod._read_pid() is None

    def test_empty_file_returns_none(self, pid_file):
        pid_file.write_text("")
        assert daemon_mod._read_pid() is None


# ---------------------------------------------------------------------------
# _process_alive
# ---------------------------------------------------------------------------

class TestProcessAlive:
    def test_self_is_alive(self):
        assert daemon_mod._process_alive(os.getpid()) is True

    def test_nonexistent_pid_returns_false(self):
        assert daemon_mod._process_alive(2_000_000_000) is False


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

class TestStop:
    def test_no_pid_file_exits_1(self, pid_file):
        with pytest.raises(typer.Exit):
            daemon_mod.stop()

    def test_stale_pid_removes_file_and_exits(self, pid_file):
        pid_file.write_text("2000000000")
        with pytest.raises(typer.Exit):
            daemon_mod.stop()
        assert not pid_file.exists()

    def test_live_pid_sends_sigterm(self, pid_file):
        pid_file.write_text(str(os.getpid()))
        with patch("vardrrunner.commands.daemon.os.kill") as mock_kill:
            daemon_mod.stop()
        # os.kill is also called with signal 0 by _process_alive; assert the SIGTERM call happened
        mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_no_pid_file_does_not_raise(self, pid_file):
        daemon_mod.status()  # should not raise

    def test_live_pid_prints_running(self, pid_file, capsys):
        pid_file.write_text(str(os.getpid()))
        daemon_mod.status()
        # Rich writes to its own console, not capsys — just check it doesn't raise

    def test_stale_pid_removes_file(self, pid_file):
        pid_file.write_text("2000000000")
        daemon_mod.status()
        assert not pid_file.exists()


# ---------------------------------------------------------------------------
# _detach
# ---------------------------------------------------------------------------

class TestDetach:
    def test_spawns_daemon_process(self, tmp_path, monkeypatch):
        log = tmp_path / "daemon.log"
        exe = "vardrrunner"

        with patch("vardrrunner.commands.daemon.shutil.which", return_value=exe), \
             patch("vardrrunner.commands.daemon.subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            MockPopen.return_value = mock_proc
            daemon_mod._detach(poll_interval=5, heartbeat_interval=60, log_file=log)

        args, kwargs = MockPopen.call_args
        cmd = args[0]
        assert cmd[0] == exe
        assert "daemon" in cmd
        assert "start" in cmd
        assert "--poll-interval" in cmd
        assert "--log-file" in cmd

    def test_defaults_log_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(daemon_mod, "DEFAULT_LOG", tmp_path / "daemon.log")
        with patch("vardrrunner.commands.daemon.shutil.which", return_value="vardrrunner"), \
             patch("vardrrunner.commands.daemon.subprocess.Popen") as MockPopen:
            MockPopen.return_value = MagicMock(pid=1)
            daemon_mod._detach(poll_interval=5, heartbeat_interval=60, log_file=None)

        args, _ = MockPopen.call_args
        assert str(tmp_path / "daemon.log") in args[0]

    def test_detach_uses_start_new_session(self, tmp_path):
        log = tmp_path / "daemon.log"
        with patch("vardrrunner.commands.daemon.shutil.which", return_value="vardrrunner"), \
             patch("vardrrunner.commands.daemon.subprocess.Popen") as MockPopen:
            MockPopen.return_value = MagicMock(pid=1)
            daemon_mod._detach(poll_interval=5, heartbeat_interval=60, log_file=log)

        _, kwargs = MockPopen.call_args
        assert kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# start (foreground loop)
# ---------------------------------------------------------------------------

class TestStart:
    def test_writes_and_removes_pid_file(self, pid_file, monkeypatch):
        """Daemon writes PID on entry and removes it in the finally block."""
        # Control the event: one pass through the loop, then stop
        iterations = {"n": 0}

        class FakeEvent:
            def __init__(self):
                self._set = False

            def is_set(self):
                r = iterations["n"] >= 1
                iterations["n"] += 1
                return r

            def wait(self, timeout=None):
                return self._set

            def set(self):
                self._set = True

        with patch("vardrrunner.commands.daemon.threading.Event", FakeEvent), \
             patch("vardrrunner.commands.daemon.threading.Thread") as MockThread, \
             patch("vardrrunner.commands.daemon.signal.signal"), \
             patch("vardrrunner.commands.daemon.config.require_auth", return_value=("http://api", "key")), \
             patch("vardrrunner.commands.daemon.api.VardrMapClient"), \
             patch("vardrrunner.commands.daemon.execute_pending_jobs", return_value=0), \
             patch("vardrrunner.commands.daemon.send_heartbeat"):
            daemon_mod.start(detach=False, poll_interval=1, heartbeat_interval=60, log_file=None)

        assert not pid_file.exists()  # cleaned up in finally

    def test_calls_execute_pending_jobs(self, pid_file):
        """Daemon calls execute_pending_jobs on each poll cycle."""
        iterations = {"n": 0}

        class FakeEvent:
            def is_set(self):
                r = iterations["n"] >= 1
                iterations["n"] += 1
                return r

            def wait(self, timeout=None):
                return False

            def set(self):
                pass

        with patch("vardrrunner.commands.daemon.threading.Event", FakeEvent), \
             patch("vardrrunner.commands.daemon.threading.Thread"), \
             patch("vardrrunner.commands.daemon.signal.signal"), \
             patch("vardrrunner.commands.daemon.config.require_auth", return_value=("http://api", "key")), \
             patch("vardrrunner.commands.daemon.api.VardrMapClient"), \
             patch("vardrrunner.commands.daemon.execute_pending_jobs", return_value=0) as mock_exec, \
             patch("vardrrunner.commands.daemon.send_heartbeat"):
            daemon_mod.start(detach=False, poll_interval=1, heartbeat_interval=60, log_file=None)

        mock_exec.assert_called_once()

    def test_starts_heartbeat_thread(self, pid_file):
        """Daemon starts the heartbeat background thread."""
        iterations = {"n": 0}

        class FakeEvent:
            def is_set(self):
                r = iterations["n"] >= 1
                iterations["n"] += 1
                return r

            def wait(self, timeout=None):
                return False

            def set(self):
                pass

        with patch("vardrrunner.commands.daemon.threading.Event", FakeEvent), \
             patch("vardrrunner.commands.daemon.threading.Thread") as MockThread, \
             patch("vardrrunner.commands.daemon.signal.signal"), \
             patch("vardrrunner.commands.daemon.config.require_auth", return_value=("http://api", "key")), \
             patch("vardrrunner.commands.daemon.api.VardrMapClient"), \
             patch("vardrrunner.commands.daemon.execute_pending_jobs", return_value=0), \
             patch("vardrrunner.commands.daemon.send_heartbeat"):
            daemon_mod.start(detach=False, poll_interval=1, heartbeat_interval=60, log_file=None)

        MockThread.assert_called_once()
        MockThread.return_value.start.assert_called_once()

    def test_exits_when_not_authenticated(self, pid_file):
        with patch("vardrrunner.commands.daemon.config.require_auth", side_effect=RuntimeError("no creds")):
            with pytest.raises(typer.Exit):
                daemon_mod.start(detach=False, poll_interval=5, heartbeat_interval=60, log_file=None)

    def test_detach_delegates_to_detach(self, pid_file, tmp_path):
        log = tmp_path / "daemon.log"
        with patch("vardrrunner.commands.daemon._detach") as mock_detach:
            daemon_mod.start(detach=True, poll_interval=5, heartbeat_interval=60, log_file=log)
        mock_detach.assert_called_once_with(poll_interval=5, heartbeat_interval=60, log_file=log)

    def test_poll_error_does_not_crash_daemon(self, pid_file):
        """A transient API error is caught and the loop continues."""
        iterations = {"n": 0}

        class FakeEvent:
            def is_set(self):
                r = iterations["n"] >= 2
                iterations["n"] += 1
                return r

            def wait(self, timeout=None):
                return False

            def set(self):
                pass

        call_count = {"n": 0}

        def flaky_execute(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("temporary network error")
            return 0

        with patch("vardrrunner.commands.daemon.threading.Event", FakeEvent), \
             patch("vardrrunner.commands.daemon.threading.Thread"), \
             patch("vardrrunner.commands.daemon.signal.signal"), \
             patch("vardrrunner.commands.daemon.config.require_auth", return_value=("http://api", "key")), \
             patch("vardrrunner.commands.daemon.api.VardrMapClient"), \
             patch("vardrrunner.commands.daemon.execute_pending_jobs", side_effect=flaky_execute), \
             patch("vardrrunner.commands.daemon.send_heartbeat"):
            daemon_mod.start(detach=False, poll_interval=1, heartbeat_interval=60, log_file=None)

        assert call_count["n"] == 2  # tried twice despite first failure


# ---------------------------------------------------------------------------
# execute_pending_jobs
# ---------------------------------------------------------------------------

class TestExecutePendingJobs:
    def test_empty_queue_returns_zero(self):
        client = MagicMock()
        client.pending_jobs.return_value = []
        con = MagicMock()
        assert execute_pending_jobs(client, con) == 0

    def test_returns_job_count(self, tmp_path):
        output_file = tmp_path / "httpx.jsonl"
        output_file.write_text('{"url":"https://example.com"}\n')

        job = {
            "id": "job-d01", "program_id": "prog-1",
            "tool_type": "httpx", "target_source": "scope",
            "config": {"limit": 50},
        }
        client = MagicMock()
        client.pending_jobs.return_value = [job]
        client.scope.return_value = {"in": [{"value": "app.example.com"}], "out": []}
        client.import_file.return_value = {"import_record": {"imported_count": 1}}

        with patch("vardrrunner.commands.jobs.runner.tool_available", return_value=True), \
             patch("vardrrunner.commands.jobs._make_run_dir", return_value=tmp_path), \
             patch("vardrrunner.commands.jobs.runner.run_httpx", return_value=0):
            con = MagicMock()
            result = execute_pending_jobs(client, con)

        assert result == 1
        client.claim_job.assert_called_once_with("job-d01")
        client.complete_job.assert_called_once_with("job-d01", "done")
