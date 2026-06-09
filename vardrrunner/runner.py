"""
Safe subprocess runner. Only tools in ALLOWED_TOOLS can be executed.
Commands are built as argument lists — shell=True is never used.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# Allowlist maps subcommand names to their executable names.
# Add new tools here only — never allow arbitrary executables.
ALLOWED_TOOLS = {
    "httpx":   "httpx",
    "nuclei":  "nuclei",
}


def tool_available(name: str) -> bool:
    """Return True if the tool binary exists on PATH."""
    return shutil.which(ALLOWED_TOOLS.get(name, "")) is not None


def check_tool(name: str) -> None:
    """Raise SystemExit with a helpful message if the tool is not installed."""
    if not tool_available(name):
        import typer
        raise typer.BadParameter(
            f"'{name}' not found on PATH. Install it and make sure it is executable.",
            param_hint=name,
        )


def run_httpx(targets: list[str], output_path: Path) -> int:
    """Run httpx against a list of targets. Output is JSONL written to output_path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["httpx"],
        "-l", targets_file,
        "-json",
        "-o", str(output_path),
        "-silent",
    ]
    result = subprocess.run(cmd, check=False)
    Path(targets_file).unlink(missing_ok=True)
    return result.returncode


def run_nuclei(
    targets: list[str],
    output_path: Path,
    severity: Optional[str] = None,
    templates: Optional[str] = None,
) -> int:
    """Run nuclei against a list of targets. Output is JSONL written to output_path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["nuclei"],
        "-l", targets_file,
        "-json-export", str(output_path),
        "-silent",
    ]
    if severity:
        cmd += ["-severity", severity]
    if templates:
        cmd += ["-t", templates]

    result = subprocess.run(cmd, check=False)
    Path(targets_file).unlink(missing_ok=True)
    return result.returncode
