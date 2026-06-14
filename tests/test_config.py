import json
from pathlib import Path

import pytest

from vardrrunner import config


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    """Redirect config to a temp directory so tests never touch ~/.vardrmap."""
    monkeypatch.setattr(config, "CONFIG_DIR",  tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "RUNS_DIR",    tmp_path / "runs")
    yield tmp_path


def test_load_returns_empty_when_no_file():
    assert config.load() == {}


def test_save_and_load_roundtrip():
    data = {"api_url": "https://example.com", "api_key": "vmap_test123"}
    config.save(data)
    assert config.load() == data


def test_save_creates_parent_directories(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested"
    monkeypatch.setattr(config, "CONFIG_DIR",  nested)
    monkeypatch.setattr(config, "CONFIG_FILE", nested / "config.json")
    config.save({"api_url": "x", "api_key": "vmap_y"})
    assert (nested / "config.json").exists()


def test_get_api_url_and_key():
    config.save({"api_url": "https://example.com", "api_key": "vmap_abc"})
    assert config.get_api_url() == "https://example.com"
    assert config.get_api_key() == "vmap_abc"


def test_get_api_url_returns_none_when_missing():
    assert config.get_api_url() is None
    assert config.get_api_key() is None
