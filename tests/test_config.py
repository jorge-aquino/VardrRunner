import pytest

from vardrrunner import config


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    """Redirect config to a temp dir and clear env overrides so tests are hermetic."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    for var in (config.ENV_API_URL, config.ENV_API_KEY, config.ENV_ALLOW_INSECURE):
        monkeypatch.delenv(var, raising=False)
    yield tmp_path


def test_load_returns_empty_when_no_file():
    assert config.load() == {}


def test_save_and_load_roundtrip():
    data = {"api_url": "https://example.com", "api_key": "vmap_test123"}
    config.save(data)
    assert config.load() == data


def test_save_creates_parent_directories(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested"
    monkeypatch.setattr(config, "CONFIG_DIR", nested)
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


# --------------------------------------------------------------------------- #
# Environment overrides
# --------------------------------------------------------------------------- #


def test_env_overrides_file(monkeypatch):
    config.save({"api_url": "https://file.example.com", "api_key": "vmap_file"})
    monkeypatch.setenv(config.ENV_API_URL, "https://env.example.com")
    monkeypatch.setenv(config.ENV_API_KEY, "vmap_env")
    assert config.get_api_url() == "https://env.example.com"
    assert config.get_api_key() == "vmap_env"


def test_env_used_when_no_file(monkeypatch):
    monkeypatch.setenv(config.ENV_API_URL, "https://env.example.com")
    monkeypatch.setenv(config.ENV_API_KEY, "vmap_env")
    assert config.require_auth() == ("https://env.example.com", "vmap_env")


# --------------------------------------------------------------------------- #
# URL validation
# --------------------------------------------------------------------------- #


def test_validate_https_ok():
    assert config.validate_api_url("https://api.example.com") == "https://api.example.com"


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000"])
def test_validate_http_localhost_ok(url):
    assert config.validate_api_url(url) == url


def test_validate_http_remote_rejected():
    with pytest.raises(config.InvalidApiUrl):
        config.validate_api_url("http://api.example.com")


def test_validate_http_remote_allowed_with_opt_in(monkeypatch):
    monkeypatch.setenv(config.ENV_ALLOW_INSECURE, "1")
    assert config.validate_api_url("http://api.example.com") == "http://api.example.com"


@pytest.mark.parametrize("url", ["ftp://api.example.com", "not-a-url", "https://"])
def test_validate_garbage_rejected(url):
    with pytest.raises(config.InvalidApiUrl):
        config.validate_api_url(url)


def test_require_auth_rejects_insecure_url(monkeypatch):
    import typer

    monkeypatch.setenv(config.ENV_API_URL, "http://api.example.com")
    monkeypatch.setenv(config.ENV_API_KEY, "vmap_x")
    with pytest.raises(typer.BadParameter):
        config.require_auth()


def test_require_auth_missing_credentials():
    import typer

    with pytest.raises(typer.BadParameter):
        config.require_auth()
