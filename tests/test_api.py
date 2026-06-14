"""Tests for the VardrMap API client: auth/User-Agent headers and retry config.

These are pure construction/configuration tests — no network. They lock in the
resilience contract: idempotent methods retry on transient failures with backoff,
while POST/PATCH never auto-retry (so a dropped response can't double-act).
"""

from urllib3.util.retry import Retry

from vardrrunner import __version__
from vardrrunner.api import _RETRY_STATUSES, VardrMapClient


def _client(**kwargs) -> VardrMapClient:
    return VardrMapClient("https://api.example.com/", "vmap_testkey", **kwargs)


def test_base_url_trailing_slash_stripped():
    assert _client().base == "https://api.example.com"


def test_url_join_handles_leading_slash_either_way():
    c = _client()
    assert c._url("/me") == "https://api.example.com/me"
    assert c._url("programs") == "https://api.example.com/programs"


def test_authorization_header_set():
    assert _client().session.headers["Authorization"] == "Bearer vmap_testkey"


def test_user_agent_reports_runner_version():
    ua = _client().session.headers["User-Agent"]
    assert ua.startswith(f"vardrrunner/{__version__}")


def test_retry_adapter_mounted_for_http_and_https():
    c = _client()
    for scheme in ("https://x", "http://x"):
        adapter = c.session.get_adapter(scheme)
        assert isinstance(adapter.max_retries, Retry)


def test_retry_configuration_defaults():
    retry = _client().session.get_adapter("https://x").max_retries
    assert retry.total == 3
    assert retry.backoff_factor == 0.5
    assert tuple(retry.status_forcelist) == _RETRY_STATUSES
    assert retry.raise_on_status is False


def test_idempotent_methods_retry_but_post_and_patch_do_not():
    retry = _client().session.get_adapter("https://x").max_retries
    allowed = retry.allowed_methods
    assert "GET" in allowed
    assert "POST" not in allowed
    assert "PATCH" not in allowed


def test_retries_and_backoff_are_configurable():
    retry = _client(retries=5, backoff_factor=1.0).session.get_adapter("https://x").max_retries
    assert retry.total == 5
    assert retry.backoff_factor == 1.0
