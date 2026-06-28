"""Tests for pipeline commands and TUI."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner.commands.pipeline import (
    _PipelineTUI,
    _run_stage,
    _StageResult,
    list_pipelines,
    run_pipeline,
)
from vardrrunner.pipelines import PIPELINES, Stage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth():
    return patch(
        "vardrrunner.commands.pipeline.config.require_auth", return_value=("http://api", "k")
    )


def _client(mock=None):
    return patch(
        "vardrrunner.commands.pipeline.api.VardrMapClient", return_value=mock or MagicMock()
    )


def _tools_available(available=True):
    return patch("vardrrunner.commands.pipeline.runner.tool_available", return_value=available)


# ---------------------------------------------------------------------------
# list_pipelines
# ---------------------------------------------------------------------------


def test_list_pipelines_prints_all_names(capsys):
    list_pipelines()
    out = capsys.readouterr().out
    for name in PIPELINES:
        assert name in out


def test_list_pipelines_shows_tool_chain(capsys):
    list_pipelines()
    out = capsys.readouterr().out
    assert "subfinder" in out
    assert "httpx" in out


# ---------------------------------------------------------------------------
# run_pipeline — validation paths
# ---------------------------------------------------------------------------


def test_run_pipeline_unknown_name_exits():
    with pytest.raises(typer.Exit):
        run_pipeline("nonexistent", "prog-1", yes=True)


def test_run_pipeline_invalid_severity_exits():
    with _auth(), _client(), _tools_available():
        with pytest.raises(typer.Exit):
            run_pipeline("recon", "prog-1", severity="bogus", yes=True)


def test_run_pipeline_missing_tool_exits():
    with _auth(), _client(), _tools_available(False):
        with pytest.raises(typer.Exit):
            run_pipeline("quick", "prog-1", yes=True)


def test_run_pipeline_confirm_abort_exits(monkeypatch):
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)
    with _auth(), _client(), _tools_available():
        with pytest.raises(typer.Exit):
            run_pipeline("quick", "prog-1", yes=False)


# ---------------------------------------------------------------------------
# run_pipeline — happy path
# ---------------------------------------------------------------------------


def test_run_pipeline_quick_success(capsys):
    client = MagicMock()
    client.scope.return_value = {"in": [{"value": "*.example.com", "kind": "domain"}], "out": []}
    client.import_file.return_value = {"import_record": {"imported_count": 5}}

    def fake_stage(c, stage, prog, sev, cont, handoff, max_t):
        return _StageResult(
            status="done", should_continue=True, targets=10, summary="imported 10", elapsed=1.2
        )

    with _auth(), _client(client), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True)

    out = capsys.readouterr().out
    assert "Pipeline complete" in out


def test_run_pipeline_prints_run_id(capsys):
    def fake_stage(*a, **kw):
        return _StageResult(
            status="done", should_continue=True, targets=5, summary="ok", elapsed=0.5
        )

    with _auth(), _client(), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True)

    out = capsys.readouterr().out
    assert "run" in out.lower()


def test_run_pipeline_stopped_message_when_stage_fails(capsys):
    call_count = [0]

    def fake_stage(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _StageResult(status="no_targets", should_continue=False, elapsed=0.1)
        return _StageResult(
            status="done", should_continue=True, targets=5, summary="ok", elapsed=0.5
        )

    with _auth(), _client(), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True)

    out = capsys.readouterr().out
    assert "stopped" in out.lower()
    assert call_count[0] == 1  # second stage never ran


def test_run_pipeline_continue_on_error_runs_all_stages(capsys):
    results = [
        _StageResult(status="failed", should_continue=True, summary="boom", elapsed=0.1),
        _StageResult(status="done", should_continue=True, targets=3, summary="ok", elapsed=0.5),
    ]
    idx = [0]

    def fake_stage(*a, **kw):
        r = results[idx[0]]
        idx[0] += 1
        return r

    with _auth(), _client(), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True, continue_on_error=True)

    assert idx[0] == 2  # both stages ran


# ---------------------------------------------------------------------------
# _run_stage — unit tests
# ---------------------------------------------------------------------------


def _make_client(scope=None, import_return=None):
    c = MagicMock()
    c.scope.return_value = scope or {"in": [{"value": "*.example.com"}], "out": []}
    c.import_file.return_value = import_return or {"import_record": {"imported_count": 3}}
    return c


def test_run_stage_done_on_success(tmp_path):
    output = tmp_path / "subfinder.txt"
    output.write_text("sub1.example.com\nsub2.example.com\n")

    client = _make_client(scope={"in": [{"value": "*.example.com", "kind": "domain"}], "out": []})

    stage = Stage("subfinder", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_subfinder", return_value=0),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.status == "done"
    assert result.should_continue is True
    assert result.targets > 0


def test_run_stage_no_targets_when_resolution_empty():
    client = _make_client(scope={"in": [], "out": []})
    stage = Stage("subfinder", "scope")
    result = _run_stage(client, stage, "prog-1", None, False)
    assert result.status == "no_targets"
    assert result.should_continue is False


def test_run_stage_failed_on_resolution_error():
    client = MagicMock()
    client.scope.side_effect = RuntimeError("backend down")
    stage = Stage("httpx", "scope")
    result = _run_stage(client, stage, "prog-1", None, False)
    assert result.status == "failed"
    assert "target resolution" in result.summary


def test_run_stage_failed_on_resolution_error_continue_on_error():
    client = MagicMock()
    client.scope.side_effect = RuntimeError("backend down")
    stage = Stage("httpx", "scope")
    result = _run_stage(client, stage, "prog-1", None, True)
    assert result.status == "failed"
    assert result.should_continue is True


def test_run_stage_aborted_when_max_targets_exceeded():
    client = _make_client(
        scope={"in": [{"value": f"host{i}.example.com"} for i in range(600)], "out": []}
    )
    stage = Stage("httpx", "scope")
    with patch("vardrrunner.commands.pipeline.runner.run_httpx"):
        result = _run_stage(client, stage, "prog-1", None, False, max_targets=500)
    assert result.status == "aborted"
    assert result.targets == 600


def test_run_stage_failed_on_tool_timeout(tmp_path):
    from vardrrunner.runner import ToolTimeout

    client = _make_client(scope={"in": [{"value": "app.example.com"}], "out": []})
    stage = Stage("httpx", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch(
            "vardrrunner.commands.pipeline.runner.run_httpx", side_effect=ToolTimeout("timed out")
        ),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.status == "failed"
    assert "timed out" in result.summary


def test_run_stage_failed_on_generic_exception(tmp_path):
    client = _make_client(scope={"in": [{"value": "app.example.com"}], "out": []})
    stage = Stage("httpx", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_httpx", side_effect=OSError("disk full")),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.status == "failed"


def test_run_stage_no_targets_when_output_empty(tmp_path):
    client = _make_client(scope={"in": [{"value": "app.example.com"}], "out": []})
    stage = Stage("httpx", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_httpx", return_value=0),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.status == "no_targets"


def test_run_stage_failed_on_upload_error(tmp_path):
    output = tmp_path / "httpx.jsonl"
    output.write_text('{"url":"https://a.com"}\n')

    client = _make_client(scope={"in": [{"value": "app.example.com"}], "out": []})
    client.import_file.side_effect = RuntimeError("s3 down")
    stage = Stage("httpx", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_httpx", return_value=0),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.status == "failed"
    assert "upload" in result.summary


def test_run_stage_uses_handoff_file_over_backend(tmp_path):
    handoff = tmp_path / "handoff.txt"
    handoff.write_text("sub1.example.com\nsub2.example.com\n")

    client = MagicMock()
    output = tmp_path / "httpx.jsonl"
    output.write_text('{"url":"https://sub1.example.com"}\n')
    client.import_file.return_value = {"import_record": {"imported_count": 1}}

    stage = Stage("httpx", "recon")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_httpx", return_value=0),
    ):
        result = _run_stage(client, stage, "prog-1", None, False, handoff_path=handoff)

    client.scope.assert_not_called()
    assert result.targets == 2


def test_run_stage_writes_handoff_file_for_next_stage(tmp_path):
    output = tmp_path / "subfinder.txt"
    output.write_text("sub1.example.com\nsub2.example.com\n")

    client = _make_client(scope={"in": [{"value": "*.example.com", "kind": "domain"}], "out": []})
    client.import_file.return_value = {"import_record": {"imported_count": 2}}

    stage = Stage("subfinder", "scope")
    with (
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.commands.pipeline.runner.run_subfinder", return_value=0),
    ):
        result = _run_stage(client, stage, "prog-1", None, False)

    assert result.handoff is not None
    assert result.handoff.exists()


# ---------------------------------------------------------------------------
# _PipelineTUI — basic smoke tests
# ---------------------------------------------------------------------------


def test_tui_renders_without_error():
    stages = [Stage("subfinder", "scope"), Stage("httpx", "recon")]
    with _PipelineTUI(stages) as tui:
        tui.start(0)
        tui.finish(0, status="done", targets=50, summary="imported 50", elapsed=3.2)
        tui.start(1)
        tui.finish(1, status="done", targets=50, summary="imported 20", elapsed=8.1)


def test_tui_marks_remaining_stages_aborted():
    stages = [Stage("subfinder", "scope"), Stage("httpx", "recon"), Stage("nuclei", "recon")]
    with _PipelineTUI(stages) as tui:
        tui.start(0)
        tui.finish(0, status="no_targets")
        tui.finish(1, status="aborted")
        tui.finish(2, status="aborted")
    # If we get here without raising, the TUI handled all states gracefully.


def test_tui_shows_spinner_while_running():
    stages = [Stage("httpx", "recon")]
    tui = _PipelineTUI(stages)
    tui.start(0)
    table = tui._render()
    assert table.row_count == 1


# ---------------------------------------------------------------------------
# run_pipeline — --dry-run
# ---------------------------------------------------------------------------


def test_run_pipeline_dry_run_does_not_execute(capsys):
    client = MagicMock()
    client.scope.return_value = {"in": [{"value": "*.example.com", "kind": "domain"}], "out": []}

    with _auth(), _client(client), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage") as mock_stage:
            run_pipeline("quick", "prog-1", yes=True, dry_run=True)
    mock_stage.assert_not_called()
    out = capsys.readouterr().out
    assert "dry run" in out.lower()


def test_run_pipeline_dry_run_shows_target_count(capsys):
    client = MagicMock()
    client.scope.return_value = {
        "in": [{"value": "*.a.com"}, {"value": "*.b.com"}],
        "out": [],
    }

    with _auth(), _client(client), _tools_available():
        run_pipeline("quick", "prog-1", yes=True, dry_run=True)

    out = capsys.readouterr().out
    assert "2" in out  # 2 wildcard domains resolved for subfinder


def test_run_pipeline_dry_run_resolution_error_exits():
    client = MagicMock()
    client.scope.side_effect = RuntimeError("backend down")

    with _auth(), _client(client), _tools_available():
        with pytest.raises(typer.Exit):
            run_pipeline("quick", "prog-1", yes=True, dry_run=True)


# ---------------------------------------------------------------------------
# run_pipeline — --json
# ---------------------------------------------------------------------------


def test_run_pipeline_json_output(capsys):
    import json as _json

    def fake_stage(*a, **kw):
        return _StageResult(
            status="done", should_continue=True, targets=10, summary="imported 10", elapsed=1.0
        )

    with _auth(), _client(), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True, as_json=True)

    out = capsys.readouterr().out
    payload = _json.loads(out)
    assert payload["pipeline"] == "quick"
    assert payload["success"] is True
    assert len(payload["stages"]) == 2
    assert payload["stages"][0]["status"] == "done"


def test_run_pipeline_json_stopped_pipeline(capsys):
    import json as _json

    def fake_stage(*a, **kw):
        return _StageResult(status="no_targets", should_continue=False, elapsed=0.1)

    with _auth(), _client(), _tools_available():
        with patch("vardrrunner.commands.pipeline._run_stage", side_effect=fake_stage):
            run_pipeline("quick", "prog-1", yes=True, as_json=True)

    payload = _json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert any(s["status"] == "aborted" for s in payload["stages"])
