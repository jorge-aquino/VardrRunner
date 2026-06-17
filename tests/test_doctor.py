"""Tests for `vardrrunner doctor` — the preflight health check and its exit codes."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner.commands import doctor
from vardrrunner.commands.doctor import Check, Health


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point config + runs at a temp dir and clear credential env vars."""
    monkeypatch.setattr("vardrrunner.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("vardrrunner.config.CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr("vardrrunner.config.RUNS_DIR", tmp_path / "runs")
    for var in ("VARDRMAP_URL", "VARDRMAP_API_KEY", "VARDRRUNNER_ALLOW_INSECURE"):
        monkeypatch.delenv(var, raising=False)
    yield


def _run(as_json=False):
    """Run doctor, capturing the SystemExit-style code from typer.Exit."""
    try:
        doctor.run_doctor(as_json=as_json)
    except typer.Exit as e:
        return e.exit_code
    return 0


def test_fails_without_credentials():
    # No config, no env → credentials FAIL → exit non-zero.
    with patch("vardrrunner.runner.tool_available", return_value=True):
        assert _run() == 1


def test_exit_zero_when_healthy(monkeypatch):
    monkeypatch.setenv("VARDRMAP_URL", "https://api.example.com")
    monkeypatch.setenv("VARDRMAP_API_KEY", "vmap_ok")
    client = MagicMock()
    client.whoami.return_value = {"username": "alice"}
    with (
        patch("vardrrunner.commands.doctor.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=True),
        patch("vardrrunner.runner.tool_version", return_value="v1.0.0"),
    ):
        assert _run() == 0


def test_auth_failure_is_fatal(monkeypatch):
    import requests

    monkeypatch.setenv("VARDRMAP_URL", "https://api.example.com")
    monkeypatch.setenv("VARDRMAP_API_KEY", "vmap_bad")
    client = MagicMock()
    resp = MagicMock(status_code=401)
    client.whoami.side_effect = requests.HTTPError(response=resp)
    with (
        patch("vardrrunner.commands.doctor.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=True),
    ):
        assert _run() == 1


def test_missing_tools_warn_but_one_present_is_ok(monkeypatch):
    """Some tools missing → warnings, not failure, as long as one is installed."""
    monkeypatch.setenv("VARDRMAP_URL", "https://api.example.com")
    monkeypatch.setenv("VARDRMAP_API_KEY", "vmap_ok")
    client = MagicMock()
    client.whoami.return_value = {"username": "alice"}
    with (
        patch("vardrrunner.commands.doctor.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", side_effect=lambda t: t == "httpx"),
        patch("vardrrunner.runner.tool_version", return_value="v1.0.0"),
    ):
        assert _run() == 0  # warnings don't fail the preflight


def test_no_tools_at_all_is_fatal(monkeypatch):
    monkeypatch.setenv("VARDRMAP_URL", "https://api.example.com")
    monkeypatch.setenv("VARDRMAP_API_KEY", "vmap_ok")
    client = MagicMock()
    client.whoami.return_value = {"username": "alice"}
    with (
        patch("vardrrunner.commands.doctor.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=False),
    ):
        assert _run() == 1


def test_stale_daemon_pid_warns(monkeypatch):
    check = None
    with (
        patch("vardrrunner.commands.doctor.daemon._read_pid", return_value=4242),
        patch("vardrrunner.commands.doctor.daemon._process_alive", return_value=False),
    ):
        check = doctor._check_daemon()
    assert check.status is Health.WARN and "stale" in check.detail


def test_json_output_is_structured(monkeypatch, capsys):
    monkeypatch.setenv("VARDRMAP_URL", "https://api.example.com")
    monkeypatch.setenv("VARDRMAP_API_KEY", "vmap_ok")
    client = MagicMock()
    client.whoami.return_value = {"username": "alice"}
    with (
        patch("vardrrunner.commands.doctor.api.VardrMapClient", return_value=client),
        patch("vardrrunner.runner.tool_available", return_value=True),
        patch("vardrrunner.runner.tool_version", return_value="v1.0.0"),
    ):
        code = _run(as_json=True)
    import json

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["healthy"] is True
    assert payload["summary"]["fail"] == 0
    assert any(c["name"] == "api auth" for c in payload["checks"])


def test_check_dataclass_shape():
    c = Check("x", Health.OK, "fine")
    assert c.remediation == "" and c.status is Health.OK
