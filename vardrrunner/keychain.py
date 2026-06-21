"""
OS keychain storage for the API key.

Uses the `keyring` library, which talks to the platform's native secret store —
macOS Keychain, Windows Credential Locker, or the Linux Secret Service. The key
is stored per backend URL (the "account"), so multiple VardrMap instances can each
keep their own credential.

Every function degrades gracefully when no keyring backend is available (e.g. a
headless server with no Secret Service): `available()` returns False and the
getters/setters return None/False instead of raising, so callers can fall back to
environment variables or the legacy config file.
"""

import logging

SERVICE = "vardrrunner"


def available() -> bool:
    """True if a usable (non-fail) keyring backend is present on this machine."""
    try:
        import keyring
        import keyring.backends.fail

        return not isinstance(keyring.get_keyring(), keyring.backends.fail.Keyring)
    except Exception as e:
        logging.debug("keychain availability check failed: %s", e)
        return False


def get_key(api_url: str) -> str | None:
    """Return the stored API key for a backend URL, or None if absent/unavailable."""
    try:
        import keyring

        return keyring.get_password(SERVICE, api_url)
    except Exception as e:
        logging.debug("keychain get_key failed for %s: %s", api_url, e)
        return None


def set_key(api_url: str, api_key: str) -> bool:
    """Store the API key for a backend URL. Returns False if the keychain rejected it."""
    try:
        import keyring

        keyring.set_password(SERVICE, api_url, api_key)
        return True
    except Exception as e:
        logging.debug("keychain set_key failed for %s: %s", api_url, e)
        return False


def delete_key(api_url: str) -> bool:
    """Remove the stored API key for a backend URL. Returns True only if one was deleted."""
    try:
        import keyring

        keyring.delete_password(SERVICE, api_url)
        return True
    except Exception as e:
        logging.debug("keychain delete_key failed for %s: %s", api_url, e)
        return False
