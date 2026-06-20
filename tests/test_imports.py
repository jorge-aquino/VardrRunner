"""Tests for the `vardrrunner import` command."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from vardrrunner.commands.imports import SUPPORTED_TOOLS, import_file


def test_supported_tools_does_not_include_ffuf():
    assert "ffuf" not in SUPPORTED_TOOLS


def test_supported_tools_includes_httpx_and_nuclei():
    assert "httpx" in SUPPORTED_TOOLS
    assert "nuclei" in SUPPORTED_TOOLS


def test_supported_tools_excludes_nmap_and_naabu():
    assert "nmap" not in SUPPORTED_TOOLS
    assert "naabu" not in SUPPORTED_TOOLS


def test_import_unsupported_tool_exits(tmp_path):
    f = tmp_path / "out.json"
    f.write_text("{}")
    with pytest.raises(typer.Exit):
        import_file("ffuf", "prog-1", f)


def test_import_missing_file_exits(tmp_path):
    with pytest.raises(typer.Exit):
        import_file("httpx", "prog-1", tmp_path / "no_such_file.jsonl")


def test_import_httpx_calls_backend(tmp_path):
    f = tmp_path / "httpx.jsonl"
    f.write_text('{"url": "https://example.com"}\n')

    client = MagicMock()
    client.import_file.return_value = {"import_record": {"imported_count": 1}}

    with (
        patch("vardrrunner.commands.imports.config.require_auth", return_value=("https://x", "k")),
        patch("vardrrunner.commands.imports.api.VardrMapClient", return_value=client),
    ):
        import_file("httpx", "prog-1", f)

    client.import_file.assert_called_once_with("prog-1", "httpx", str(f))


def test_import_nuclei_calls_backend(tmp_path):
    f = tmp_path / "nuclei.jsonl"
    f.write_text('{"template-id": "t"}\n')

    client = MagicMock()
    client.import_file.return_value = {"import_record": {"imported_count": 3}}

    with (
        patch("vardrrunner.commands.imports.config.require_auth", return_value=("https://x", "k")),
        patch("vardrrunner.commands.imports.api.VardrMapClient", return_value=client),
    ):
        import_file("nuclei", "prog-1", f)

    client.import_file.assert_called_once_with("prog-1", "nuclei", str(f))
