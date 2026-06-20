"""Tests for the VardrMap API client: auth/User-Agent headers and retry config.

These are pure construction/configuration tests — no network. They lock in the
resilience contract: idempotent methods retry on transient failures with backoff,
while POST/PATCH never auto-retry (so a dropped response can't double-act).
"""

from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# recon() pagination
# ---------------------------------------------------------------------------


def test_recon_single_page_when_results_fit():
    """If the first page is smaller than the requested limit, stop after one request."""
    c = _client()
    page = [{"url": "https://a.com"}, {"url": "https://b.com"}]
    with patch.object(c, "get", return_value={"recon": page}) as mock_get:
        result = c.recon("p1", limit=100)
    assert result == page
    assert mock_get.call_count == 1


def test_recon_paginates_until_exhausted():
    """Multiple pages are requested when the first page is full (== page_size)."""
    page_size = VardrMapClient.RECON_PAGE_SIZE
    page1 = [{"url": f"https://{i}.com"} for i in range(page_size)]
    page2 = [{"url": "https://extra.com"}]

    c = _client()
    call_count = 0

    def fake_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {"recon": page1 if call_count == 1 else page2}

    with patch.object(c, "get", side_effect=fake_get):
        result = c.recon("p1", limit=page_size + 10)

    assert len(result) == page_size + 1
    assert call_count == 2


def test_recon_respects_caller_limit():
    """The caller's limit caps how many items we collect even when pages are full."""
    c = _client()
    # Each call returns 3 items; caller wants 5 → collect first 5 only.
    calls = [0]

    def fake_get(path, params=None):
        calls[0] += 1
        fetch = (params or {}).get("limit", 3)
        return {"recon": [{"url": f"https://{calls[0]}-{i}.com"} for i in range(fetch)]}

    with patch.object(c, "get", side_effect=fake_get):
        result = c.recon("p1", limit=5)

    assert len(result) == 5


def test_recon_page_size_constant():
    assert VardrMapClient.RECON_PAGE_SIZE == 500
