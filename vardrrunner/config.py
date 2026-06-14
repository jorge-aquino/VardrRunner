"""
Config is stored at ~/.vardrmap/config.json.
Treat this file like a secret — it contains your API key in plaintext.
"""
import json
import stat
from pathlib import Path
from typing import Optional

CONFIG_DIR  = Path.home() / ".vardrmap"
CONFIG_FILE = CONFIG_DIR / "config.json"
RUNS_DIR    = CONFIG_DIR / "runs"


def config_dir() -> Path:
    return CONFIG_DIR


def runs_dir() -> Path:
    return RUNS_DIR


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as f:
        return json.load(f)


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        json.dump(data, f, indent=2)
    # Best-effort: restrict permissions on Unix so the file isn't world-readable.
    # On Windows this has no effect but raises no error.
    try:
        CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def get_api_url() -> Optional[str]:
    return load().get("api_url")


def get_api_key() -> Optional[str]:
    return load().get("api_key")


def require_auth() -> tuple[str, str]:
    """Return (api_url, api_key) or raise SystemExit with a helpful message."""
    cfg = load()
    url = cfg.get("api_url")
    key = cfg.get("api_key")
    if not url or not key:
        import typer
        raise typer.BadParameter(
            "Not logged in. Run: vardrrunner login vardrmap",
            param_hint="auth",
        )
    return url, key
