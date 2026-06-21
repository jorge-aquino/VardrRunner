"""Tests for the OS keychain wrapper."""

import sys
from unittest.mock import MagicMock, patch

import vardrrunner.keychain as kc


def _fake_keyring(*, get_return=None, set_raises=None, delete_raises=None, available=True):
    """Build a minimal fake keyring module."""
    kr = MagicMock()
    kr.get_password.return_value = get_return
    if set_raises:
        kr.set_password.side_effect = set_raises
    if delete_raises:
        kr.delete_password.side_effect = delete_raises
    if available:
        # get_keyring() returns something that is NOT a fail.Keyring
        kr.get_keyring.return_value = object()
        kr.backends.fail.Keyring = type("Keyring", (), {})
    return kr


class TestAvailable:
    def test_real_backend_returns_true(self):
        fake_kr = _fake_keyring(available=True)
        with patch.dict(
            sys.modules, {"keyring": fake_kr, "keyring.backends.fail": fake_kr.backends.fail}
        ):
            assert kc.available() is True

    def test_fail_backend_returns_false(self):
        FailKeyring = type("Keyring", (), {})
        fake_kr = MagicMock()
        fake_kr.get_keyring.return_value = FailKeyring()
        fake_kr.backends.fail.Keyring = FailKeyring
        with patch.dict(
            sys.modules, {"keyring": fake_kr, "keyring.backends.fail": fake_kr.backends.fail}
        ):
            assert kc.available() is False

    def test_import_error_returns_false(self):
        with patch.dict(sys.modules, {"keyring": None}):
            assert kc.available() is False

    def test_exception_returns_false(self):
        fake_kr = MagicMock()
        fake_kr.get_keyring.side_effect = RuntimeError("no keyring")
        with patch.dict(sys.modules, {"keyring": fake_kr, "keyring.backends.fail": MagicMock()}):
            assert kc.available() is False


class TestGetKey:
    def test_returns_stored_key(self):
        fake_kr = _fake_keyring(get_return="vmap_secret")
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.get_key("https://api.example.com") == "vmap_secret"

    def test_returns_none_when_not_found(self):
        fake_kr = _fake_keyring(get_return=None)
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.get_key("https://api.example.com") is None

    def test_exception_returns_none(self):
        fake_kr = MagicMock()
        fake_kr.get_password.side_effect = RuntimeError("keyring broken")
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.get_key("https://api.example.com") is None


class TestSetKey:
    def test_returns_true_on_success(self):
        fake_kr = _fake_keyring()
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.set_key("https://api.example.com", "vmap_key") is True
        fake_kr.set_password.assert_called_once_with(
            kc.SERVICE, "https://api.example.com", "vmap_key"
        )

    def test_returns_false_on_exception(self):
        fake_kr = _fake_keyring(set_raises=RuntimeError("no backend"))
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.set_key("https://api.example.com", "vmap_key") is False


class TestDeleteKey:
    def test_returns_true_on_success(self):
        fake_kr = _fake_keyring()
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.delete_key("https://api.example.com") is True
        fake_kr.delete_password.assert_called_once_with(kc.SERVICE, "https://api.example.com")

    def test_returns_false_on_exception(self):
        fake_kr = _fake_keyring(delete_raises=RuntimeError("not found"))
        with patch.dict(sys.modules, {"keyring": fake_kr}):
            assert kc.delete_key("https://api.example.com") is False
