"""Unit tests for the tool handlers and registry."""

from unittest.mock import MagicMock, patch

import pytest

from vardrrunner import configs, handlers


def test_registry_covers_all_tools():
    assert set(handlers.REGISTRY) == {"httpx", "nuclei", "nmap", "subfinder", "dnsx", "naabu"}
    for name, handler in handlers.REGISTRY.items():
        assert handler.tool == name


def test_parse_config_returns_typed_config():
    cfg = handlers.REGISTRY["httpx"].parse_config({"limit": 5})
    assert isinstance(cfg, configs.HttpxConfig) and cfg.limit == 5


def test_parse_config_propagates_validation_error():
    with pytest.raises(configs.ConfigError):
        handlers.REGISTRY["nmap"].parse_config({"timing": 9})


def test_default_running_label():
    label = handlers.HttpxHandler().running_label(["a", "b"], configs.HttpxConfig())
    assert label == "httpx against 2 target(s)"


def test_nuclei_running_label_includes_severity():
    label = handlers.NucleiHandler().running_label(["a"], configs.NucleiConfig(severity="high"))
    assert "severity=high" in label


def test_nmap_resolve_normalizes_and_dedupes_hosts():
    client = MagicMock()
    with patch(
        "vardrrunner.handlers._resolve_standard",
        return_value=["https://a.com/x", "http://a.com/y", "10.0.0.1:80"],
    ):
        out = handlers.NmapHandler().resolve_targets(client, "p", "recon", configs.NmapConfig())
    assert out == ["a.com", "10.0.0.1"]


def test_nmap_upload_no_services_skips_create(tmp_path):
    client = MagicMock()
    with patch("vardrrunner.runner.parse_nmap_xml", return_value=[]):
        summary = handlers.NmapHandler().upload(client, "p", tmp_path / "nmap.xml")
    assert "no open ports" in summary
    client.create_services.assert_not_called()


def test_nmap_upload_posts_services(tmp_path):
    client = MagicMock()
    client.create_services.return_value = {"created": 1, "updated": 2}
    svcs = [{"host": "h", "port": 80}]
    with patch("vardrrunner.runner.parse_nmap_xml", return_value=svcs):
        summary = handlers.NmapHandler().upload(client, "p", tmp_path / "nmap.xml")
    client.create_services.assert_called_once_with("p", svcs)
    assert "1 new" in summary and "2 updated" in summary


def test_subfinder_execute_builds_jsonl(tmp_path):
    def fake_run(domains, out, timeout=None):
        out.write_text("a.example.com\nb.example.com\n")
        return 0

    with patch("vardrrunner.runner.run_subfinder", side_effect=fake_run):
        out = handlers.SubfinderHandler().execute(
            ["example.com"], tmp_path, configs.SubfinderConfig()
        )
    assert out is not None and out.name == "subfinder_httpx.jsonl"
    lines = out.read_text().splitlines()
    assert len(lines) == 2 and '"host": "a.example.com"' in lines[0]


def test_subfinder_execute_no_results_returns_none(tmp_path):
    def fake_run(domains, out, timeout=None):
        out.write_text("")
        return 0

    with patch("vardrrunner.runner.run_subfinder", side_effect=fake_run):
        out = handlers.SubfinderHandler().execute(
            ["example.com"], tmp_path, configs.SubfinderConfig()
        )
    assert out is None


def test_subfinder_resolve_extracts_wildcard_domains():
    client = MagicMock()
    client.scope.return_value = {
        "in": [
            {"value": "*.example.com"},
            {"value": "app.example.com"},  # not a wildcard — skipped
            {"value": "*.target.io"},
        ],
        "out": [],
    }
    out = handlers.SubfinderHandler().resolve_targets(
        client, "p", "scope", configs.SubfinderConfig()
    )
    assert out == ["example.com", "target.io"]


def test_httpx_upload_summary(tmp_path):
    client = MagicMock()
    client.import_file.return_value = {"import_record": {"imported_count": 3}}
    summary = handlers.HttpxHandler().upload(client, "p", tmp_path / "httpx.jsonl")
    client.import_file.assert_called_once()
    assert "3" in summary


def test_dnsx_execute_builds_recon_jsonl(tmp_path):
    def fake_run(hosts, out, timeout=None):
        out.write_text("a.example.com\nb.example.com\n")
        return 0

    with patch("vardrrunner.runner.run_dnsx", side_effect=fake_run):
        out = handlers.DnsxHandler().execute(["a.example.com"], tmp_path, configs.DnsxConfig())
    assert out is not None and out.name == "dnsx_httpx.jsonl"
    lines = out.read_text().splitlines()
    assert len(lines) == 2 and '"source": "dnsx"' in lines[0]


def test_dnsx_execute_no_results_returns_none(tmp_path):
    with patch(
        "vardrrunner.runner.run_dnsx", side_effect=lambda h, o, timeout=None: o.write_text("")
    ):
        out = handlers.DnsxHandler().execute(["a.example.com"], tmp_path, configs.DnsxConfig())
    assert out is None


def test_naabu_upload_posts_services(tmp_path):
    client = MagicMock()
    client.create_services.return_value = {"created": 2, "updated": 0}
    svcs = [{"host": "h", "port": 80, "protocol": "tcp"}]
    with patch("vardrrunner.runner.parse_naabu_json", return_value=svcs):
        summary = handlers.NaabuHandler().upload(client, "p", tmp_path / "naabu.json")
    client.create_services.assert_called_once_with("p", svcs)
    assert "2 new" in summary


def test_naabu_upload_no_ports_skips_create(tmp_path):
    client = MagicMock()
    with patch("vardrrunner.runner.parse_naabu_json", return_value=[]):
        summary = handlers.NaabuHandler().upload(client, "p", tmp_path / "naabu.json")
    assert "no open ports" in summary
    client.create_services.assert_not_called()
