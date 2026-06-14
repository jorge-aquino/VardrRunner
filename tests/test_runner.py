"""
Tests for the safe subprocess runner. Tools are mocked — we test argument
construction and wildcard handling, not actual tool execution.
"""
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vardrrunner import runner
from vardrrunner.commands.run import _is_wildcard, _resolve_targets


# ---------------------------------------------------------------------------
# Wildcard detection
# ---------------------------------------------------------------------------

def test_wildcard_detected():
    assert _is_wildcard("*.example.com") is True
    assert _is_wildcard("*example.com")  is True


def test_non_wildcard_passes():
    assert _is_wildcard("app.example.com")          is False
    assert _is_wildcard("https://api.example.com")  is False
    assert _is_wildcard("192.168.1.1")              is False


# ---------------------------------------------------------------------------
# tool_available
# ---------------------------------------------------------------------------

def test_tool_available_returns_false_for_unknown():
    assert runner.tool_available("notarealtool") is False


def test_tool_available_uses_shutil_which():
    with patch("shutil.which", return_value="/usr/bin/httpx"):
        assert runner.tool_available("httpx") is True


def test_tool_available_missing():
    with patch("shutil.which", return_value=None):
        assert runner.tool_available("httpx") is False


# ---------------------------------------------------------------------------
# _resolve_targets — inline target
# ---------------------------------------------------------------------------

def test_resolve_targets_inline():
    client = MagicMock()
    targets = _resolve_targets(
        client, "prog-1",
        scope=False, from_recon=False,
        target="https://example.com",
        targets_file=None,
        status_code=None,
        limit=100,
    )
    assert targets == ["https://example.com"]
    client.scope.assert_not_called()
    client.recon.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_targets — targets file
# ---------------------------------------------------------------------------

def test_resolve_targets_file(tmp_path):
    f = tmp_path / "targets.txt"
    f.write_text("https://a.com\nhttps://b.com\n")
    client = MagicMock()
    targets = _resolve_targets(
        client, "prog-1",
        scope=False, from_recon=False,
        target=None,
        targets_file=f,
        status_code=None,
        limit=100,
    )
    assert targets == ["https://a.com", "https://b.com"]


def test_resolve_targets_file_missing_raises(tmp_path):
    import typer
    client = MagicMock()
    with pytest.raises(typer.Exit):
        _resolve_targets(
            client, "prog-1",
            scope=False, from_recon=False,
            target=None,
            targets_file=tmp_path / "missing.txt",
            status_code=None,
            limit=100,
        )


# ---------------------------------------------------------------------------
# _resolve_targets — scope (wildcards skipped)
# ---------------------------------------------------------------------------

def test_resolve_targets_scope_skips_wildcards(capsys):
    client = MagicMock()
    client.scope.return_value = {
        "in": [
            {"value": "app.example.com", "kind": "domain"},
            {"value": "*.example.com",   "kind": "domain"},
            {"value": "api.example.com", "kind": "domain"},
        ],
        "out": [],
    }
    targets = _resolve_targets(
        client, "prog-1",
        scope=True, from_recon=False,
        target=None, targets_file=None,
        status_code=None, limit=100,
    )
    assert "app.example.com" in targets
    assert "api.example.com" in targets
    assert "*.example.com"   not in targets


# ---------------------------------------------------------------------------
# _resolve_targets — from recon
# ---------------------------------------------------------------------------

def test_resolve_targets_from_recon():
    client = MagicMock()
    client.recon.return_value = [
        {"url": "https://app.example.com", "host": "app.example.com"},
        {"url": "",                          "host": "api.example.com"},
    ]
    targets = _resolve_targets(
        client, "prog-1",
        scope=False, from_recon=True,
        target=None, targets_file=None,
        status_code=200,
        limit=50,
    )
    client.recon.assert_called_once_with("prog-1", limit=50, status_code=200)
    assert "https://app.example.com" in targets
    assert "api.example.com"         in targets


# ---------------------------------------------------------------------------
# run_httpx / run_nuclei — subprocess is called with a list, not a shell string
# ---------------------------------------------------------------------------

def test_run_httpx_uses_arg_list(tmp_path):
    output = tmp_path / "out.jsonl"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        runner.run_httpx(["https://example.com"], output)
        args = mock_run.call_args[0][0]
        assert isinstance(args, list), "subprocess must be called with a list, not a shell string"
        assert args[0] == "httpx"


def test_run_nuclei_uses_arg_list(tmp_path):
    output = tmp_path / "out.jsonl"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        runner.run_nuclei(["https://example.com"], output, severity="high,critical")
        args = mock_run.call_args[0][0]
        assert isinstance(args, list)
        assert args[0] == "nuclei"
        assert "-severity" in args
        assert "high,critical" in args
