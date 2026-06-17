"""Direct `run` commands validate options through the same typed configs as jobs."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner.commands import run as run_cmd


def _common_patches(targets):
    """Patch auth/client/tool-check/resolution so only validation is exercised."""
    return (
        patch("vardrrunner.commands.run.runner.check_tool"),
        patch("vardrrunner.commands.run.config.require_auth", return_value=("https://a", "k")),
        patch("vardrrunner.commands.run.api.VardrMapClient", return_value=MagicMock()),
        patch("vardrrunner.commands.run._resolve_targets", return_value=targets),
    )


def test_run_nmap_rejects_invalid_timing():
    """`run nmap --timing 9` must be rejected (parity with jobs), not clamped."""
    p = _common_patches(["10.0.0.1"])
    with p[0], p[1], p[2], p[3], patch("vardrrunner.runner.run_nmap") as mock_nmap:
        with pytest.raises(typer.Exit):
            run_cmd.run_nmap("prog-1", target="10.0.0.1", timing=9, yes=True)
    mock_nmap.assert_not_called()  # rejected before any tool runs


def test_run_nuclei_rejects_invalid_severity():
    p = _common_patches(["https://app.example.com"])
    with p[0], p[1], p[2], p[3], patch("vardrrunner.runner.run_nuclei") as mock_nuclei:
        with pytest.raises(typer.Exit):
            run_cmd.run_nuclei(
                "prog-1", target="https://app.example.com", severity="bogus", yes=True
            )
    mock_nuclei.assert_not_called()
