"""
Tests for VardrRunner job queue commands and subfinder support.
All subprocess calls and HTTP calls are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner import runner
from vardrrunner.commands import jobs as jobs_cmd
from vardrrunner.commands.run import run_subfinder

# ---------------------------------------------------------------------------
# runner.run_subfinder — subprocess args
# ---------------------------------------------------------------------------


def test_run_subfinder_uses_arg_list(tmp_path):
    output = tmp_path / "out.txt"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        runner.run_subfinder(["example.com", "target.io"], output)
        args = mock_run.call_args[0][0]
        assert isinstance(args, list), "subprocess must be called with a list"
        assert args[0] == "subfinder"
        assert "-dL" in args
        assert "-o" in args
        assert str(output) in args
        assert "-silent" in args


def test_run_subfinder_raises_on_nonzero_exit(tmp_path):
    output = tmp_path / "out.txt"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        with pytest.raises(runner.ToolError):
            runner.run_subfinder(["example.com"], output)


# ---------------------------------------------------------------------------
# run_subfinder command — wildcard extraction
# ---------------------------------------------------------------------------


def test_run_subfinder_command_extracts_wildcards(tmp_path):
    """Wildcard entries like *.example.com → subfinder runs against example.com."""
    client = MagicMock()
    client.scope.return_value = {
        "in": [
            {"value": "*.example.com", "kind": "domain"},
            {"value": "app.other.com", "kind": "domain"},
            {"value": "*.target.io", "kind": "domain"},
        ],
        "out": [],
    }
    client.import_file.return_value = {"import_record": {"imported_count": 5}}

    output_file = tmp_path / "subfinder.txt"
    output_file.write_text("sub1.example.com\nsub2.example.com\n")

    with (
        patch("vardrrunner.commands.run.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.run.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.run.runner.check_tool"),
        patch("vardrrunner.commands.run._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.run.runner.run_subfinder", return_value=0) as mock_sf,
        patch("vardrrunner.commands.run.typer.confirm", return_value=True),
    ):
        run_subfinder("prog-1", yes=False)

    domains_passed = mock_sf.call_args[0][0]
    assert "example.com" in domains_passed
    assert "target.io" in domains_passed
    assert "app.other.com" not in domains_passed


def test_run_subfinder_command_no_wildcards_exits():
    """If no wildcard entries, the command exits with a message."""
    client = MagicMock()
    client.scope.return_value = {"in": [{"value": "app.example.com", "kind": "domain"}], "out": []}

    with (
        patch("vardrrunner.commands.run.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.run.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.run.runner.check_tool"),
        pytest.raises(typer.Exit),
    ):
        run_subfinder("prog-1", yes=True)


# ---------------------------------------------------------------------------
# api.VardrMapClient — new methods
# ---------------------------------------------------------------------------


def test_client_pending_jobs():
    from vardrrunner.api import VardrMapClient

    client = VardrMapClient("http://api", "key")
    with patch.object(client, "get", return_value={"jobs": [{"id": "abc"}]}) as mock_get:
        result = client.pending_jobs()
    mock_get.assert_called_once_with("/jobs/pending")
    assert result == [{"id": "abc"}]


def test_client_claim_job():
    from vardrrunner.api import VardrMapClient

    client = VardrMapClient("http://api", "key")
    with patch.object(client, "post", return_value={"status": "running"}) as mock_post:
        client.claim_job("job-123")
    mock_post.assert_called_once_with("/jobs/job-123/claim")


def test_client_complete_job_done():
    from vardrrunner.api import VardrMapClient

    client = VardrMapClient("http://api", "key")
    with patch.object(client, "patch", return_value={"status": "done"}) as mock_patch:
        client.complete_job("job-123", "done")
    mock_patch.assert_called_once_with("/jobs/job-123", json={"status": "done"})


def test_client_complete_job_failed_with_error():
    from vardrrunner.api import VardrMapClient

    client = VardrMapClient("http://api", "key")
    with patch.object(client, "patch", return_value={"status": "failed"}) as mock_patch:
        client.complete_job("job-123", "failed", error="timeout")
    mock_patch.assert_called_once_with(
        "/jobs/job-123", json={"status": "failed", "error_message": "timeout"}
    )


# ---------------------------------------------------------------------------
# jobs.list_jobs
# ---------------------------------------------------------------------------


def test_list_jobs_no_pending(capsys):
    client = MagicMock()
    client.pending_jobs.return_value = []

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        pytest.raises(typer.Exit),
    ):
        jobs_cmd.list_jobs()


def test_list_jobs_shows_table(capsys):
    client = MagicMock()
    client.pending_jobs.return_value = [
        {
            "id": "abc123",
            "tool_type": "httpx",
            "target_source": "scope",
            "config": {},
            "created_at": "2026-06-09T10:00:00",
        },
    ]

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
    ):
        jobs_cmd.list_jobs()  # should not raise


# ---------------------------------------------------------------------------
# jobs.run_jobs — happy path (httpx job)
# ---------------------------------------------------------------------------


def test_run_jobs_executes_httpx_job(tmp_path):
    output_file = tmp_path / "httpx.jsonl"
    output_file.write_text('{"url":"https://example.com"}\n')

    job = {
        "id": "job-001",
        "program_id": "prog-1",
        "tool_type": "httpx",
        "target_source": "scope",
        "config": {"limit": 100},
    }

    client = MagicMock()
    client.pending_jobs.return_value = [job]
    client.scope.return_value = {"in": [{"value": "app.example.com"}], "out": []}
    client.import_file.return_value = {"import_record": {"imported_count": 1}}

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.jobs.runner.tool_available", return_value=True),
        patch("vardrrunner.commands.jobs._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.jobs.runner.run_httpx", return_value=0),
    ):
        jobs_cmd.run_jobs(yes=True)

    client.claim_job.assert_called_once_with("job-001")
    client.complete_job.assert_called_once_with("job-001", "done")


def test_run_jobs_marks_failed_on_tool_timeout(tmp_path):
    """A hung tool must mark the job failed, not freeze the runner."""
    from vardrrunner.runner import ToolTimeout

    job = {
        "id": "job-timeout",
        "program_id": "prog-1",
        "tool_type": "httpx",
        "target_source": "scope",
        "config": {"timeout": 1},
    }
    client = MagicMock()
    client.pending_jobs.return_value = [job]
    client.scope.return_value = {"in": [{"value": "app.example.com"}], "out": []}

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.jobs.runner.tool_available", return_value=True),
        patch("vardrrunner.commands.jobs._make_run_dir", return_value=tmp_path),
        patch(
            "vardrrunner.commands.jobs.runner.run_httpx",
            side_effect=ToolTimeout("httpx timed out after 1s and was killed"),
        ),
    ):
        jobs_cmd.run_jobs(yes=True)  # must not raise — the daemon survives a hung tool

    client.claim_job.assert_called_once_with("job-timeout")
    assert client.complete_job.call_args[0][:2] == ("job-timeout", "failed")


def test_run_jobs_malformed_job_marks_failed():
    """A job missing a required envelope field fails cleanly instead of crashing the loop."""
    job = {"id": "job-x", "program_id": "p", "target_source": "scope"}  # no tool_type
    client = MagicMock()
    client.pending_jobs.return_value = [job]

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
    ):
        jobs_cmd.run_jobs(yes=True)  # must not raise

    client.claim_job.assert_not_called()
    args, kwargs = client.complete_job.call_args
    assert args[:2] == ("job-x", "failed")
    assert "malformed" in kwargs["error"]


def test_run_jobs_no_jobs_exits():
    client = MagicMock()
    client.pending_jobs.return_value = []

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        pytest.raises(typer.Exit),
    ):
        jobs_cmd.run_jobs(yes=True)


def test_run_jobs_executes_subfinder_job(tmp_path):
    """Subfinder job: extracts wildcard domains, runs subfinder, uploads as httpx."""
    sf_output = tmp_path / "subfinder.txt"
    sf_output.write_text("sub1.example.com\nsub2.example.com\n")

    job = {
        "id": "job-003",
        "program_id": "prog-1",
        "tool_type": "subfinder",
        "target_source": "scope",
        "config": {},
    }

    client = MagicMock()
    client.pending_jobs.return_value = [job]
    client.scope.return_value = {
        "in": [{"value": "*.example.com", "kind": "domain"}],
        "out": [],
    }
    client.import_file.return_value = {"import_record": {"imported_count": 2}}

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.jobs.runner.tool_available", return_value=True),
        patch("vardrrunner.commands.jobs._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.jobs.runner.run_subfinder", return_value=0),
    ):
        jobs_cmd.run_jobs(yes=True)

    client.claim_job.assert_called_once_with("job-003")
    # Subfinder results are uploaded as "httpx" recon targets, not as "subfinder"
    assert client.import_file.call_args[0][1] == "httpx"
    client.complete_job.assert_called_once_with("job-003", "done")


def test_run_jobs_subfinder_no_wildcards_marks_done():
    """Subfinder job with no wildcard scope entries is marked done without execution."""
    job = {
        "id": "job-004",
        "program_id": "prog-1",
        "tool_type": "subfinder",
        "target_source": "scope",
        "config": {},
    }

    client = MagicMock()
    client.pending_jobs.return_value = [job]
    client.scope.return_value = {
        "in": [{"value": "app.example.com", "kind": "domain"}],
        "out": [],
    }

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.jobs.runner.tool_available", return_value=True),
    ):
        jobs_cmd.run_jobs(yes=True)

    client.claim_job.assert_not_called()
    client.complete_job.assert_called_once_with("job-004", "done")


def test_run_jobs_missing_tool_marks_failed():
    job = {
        "id": "job-002",
        "program_id": "prog-1",
        "tool_type": "nuclei",
        "target_source": "scope",
        "config": {},
    }
    client = MagicMock()
    client.pending_jobs.return_value = [job]

    with (
        patch("vardrrunner.commands.jobs.config.require_auth", return_value=("http://api", "key")),
        patch("vardrrunner.commands.jobs.api.VardrMapClient", return_value=client),
        patch("vardrrunner.commands.jobs.runner.tool_available", return_value=False),
    ):
        jobs_cmd.run_jobs(yes=True)

    client.claim_job.assert_not_called()
    client.complete_job.assert_called_once_with(
        "job-002", "failed", error="'nuclei' not found on PATH"
    )
