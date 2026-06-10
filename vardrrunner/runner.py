"""
Safe subprocess runner. Only tools in ALLOWED_TOOLS can be executed.
Commands are built as argument lists — shell=True is never used.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# Allowlist maps subcommand names to their executable names.
# Add new tools here only — never allow arbitrary executables.
ALLOWED_TOOLS = {
    "httpx":     "httpx",
    "nuclei":    "nuclei",
    "subfinder": "subfinder",
}


def tool_available(name: str) -> bool:
    """Return True if the tool binary exists on PATH."""
    return shutil.which(ALLOWED_TOOLS.get(name, "")) is not None


def tool_version(name: str) -> Optional[str]:
    """Return the version string (e.g. 'v1.6.9') for an installed tool, or None."""
    binary = ALLOWED_TOOLS.get(name, "")
    if not binary or not shutil.which(binary):
        return None
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=5, check=False
        )
        output = (result.stdout or "") + (result.stderr or "")
        match = re.search(r"v\d+\.\d+\.\d+", output)
        return match.group(0) if match else "unknown"
    except Exception:
        return None


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


def run_subfinder(domains: list[str], output_path: Path) -> int:
    """Run subfinder against a list of root domains. Output is one host per line."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(domains))
        domains_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["subfinder"],
        "-dL", domains_file,
        "-o",  str(output_path),
        "-silent",
    ]
    result = subprocess.run(cmd, check=False)
    Path(domains_file).unlink(missing_ok=True)
    return result.returncode
