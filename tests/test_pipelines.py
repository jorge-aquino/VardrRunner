"""Tests for recon pipelines: definitions and the sequential runner."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner import pipelines
from vardrrunner.commands import pipeline as pipeline_cmd


def _fake_tool(*args, **kwargs):
    """Stand-in for runner.run_*: write a non-empty output file, return success."""
    output = args[1]  # run_*(targets, output, ...)
    output.write_text("data\n")
    return 0


def test_pipeline_definitions():
    assert set(pipelines.PIPELINES) >= {"recon", "quick"}
    recon = [s.tool for s in pipelines.PIPELINES["recon"]]
    assert recon == ["subfinder", "httpx", "nuclei"]
    # First stage reads scope; later stages chain via recon.
    assert pipelines.PIPELINES["recon"][0].source == "scope"
    assert pipelines.PIPELINES["recon"][1].source == "recon"


def test_list_pipelines_runs(capsys):
    pipeline_cmd.list_pipelines()
    out = capsys.readouterr().out
    assert "recon" in out and "subfinder" in out


def test_run_pipeline_unknown_name_exits():
    with pytest.raises(typer.Exit):
        pipeline_cmd.run_pipeline("nope", "prog-1", yes=True)


def test_run_pipeline_invalid_severity_exits():
    with pytest.raises(typer.Exit):
        pipeline_cmd.run_pipeline("recon", "prog-1", severity="bogus", yes=True)


def test_run_pipeline_missing_tool_exits():
    with (
        patch("vardrrunner.commands.pipeline.config.require_auth", return_value=("https://a", "k")),
        patch("vardrrunner.commands.pipeline.api.VardrMapClient", return_value=MagicMock()),
        patch("vardrrunner.runner.tool_available", return_value=False),
    ):
        with pytest.raises(typer.Exit):
            pipeline_cmd.run_pipeline("quick", "prog-1", yes=True)


def test_run_pipeline_executes_stages_in_order(tmp_path):
    client = MagicMock()
    client.scope.return_value = {"in": [{"value": "*.example.com"}], "out": []}
    client.recon.return_value = [{"url": "https://app.example.com"}]
    client.import_file.return_value = {"import_record": {"imported_count": 1}}

    with (
        patch("vardrrunner.commands.pipeline.config.require_auth", return_value=("https://a", "k")),
        patch("vardrrunner.commands.pipeline.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=True),
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.runner.run_subfinder", side_effect=_fake_tool),
        patch("vardrrunner.runner.run_httpx", side_effect=_fake_tool),
        patch("vardrrunner.runner.run_nuclei", side_effect=_fake_tool),
    ):
        pipeline_cmd.run_pipeline("recon", "prog-1", yes=True)

    # Three stages → three uploads, in order: subfinder→httpx import, httpx import, nuclei import.
    upload_tool_types = [c.args[1] for c in client.import_file.call_args_list]
    assert upload_tool_types == ["httpx", "httpx", "nuclei"]


def test_run_pipeline_stops_when_stage_has_no_targets(tmp_path):
    client = MagicMock()
    # No wildcard scope → subfinder resolves zero domains → pipeline stops at stage 1.
    client.scope.return_value = {"in": [{"value": "app.example.com"}], "out": []}

    with (
        patch("vardrrunner.commands.pipeline.config.require_auth", return_value=("https://a", "k")),
        patch("vardrrunner.commands.pipeline.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=True),
        patch("vardrrunner.commands.pipeline._make_run_dir", return_value=tmp_path),
        patch("vardrrunner.runner.run_subfinder", side_effect=_fake_tool),
    ):
        pipeline_cmd.run_pipeline("quick", "prog-1", yes=True)

    client.import_file.assert_not_called()
