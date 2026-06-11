"""
Safe subprocess runner. Only tools in ALLOWED_TOOLS can be executed.
Commands are built as argument lists — shell=True is never used.
"""
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# Allowlist maps subcommand names to their executable names.
# Add new tools here only — never allow arbitrary executables.
ALLOWED_TOOLS = {
    "httpx":     "httpx",
    "nuclei":    "nuclei",
    "subfinder": "subfinder",
    "nmap":      "nmap",
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


def run_nmap(targets: list[str], output_path: Path, top_ports: int = 100, timing: int = 3) -> int:
    """Run nmap with service detection against a list of targets.

    Safe profile only: --top-ports N, -sV with low intensity, -T{0-4}.
    Output is XML written to output_path. Never uses -A, -O, -p-, --script, or -T5.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    safe_timing = max(0, min(4, timing))  # clamp 0-4; never allow T5
    cmd = [
        ALLOWED_TOOLS["nmap"],
        "-iL", targets_file,
        f"--top-ports", str(top_ports),
        "-sV", "--version-intensity", "2",
        f"-T{safe_timing}",
        "-oX", str(output_path),
        "--open",
    ]
    result = subprocess.run(cmd, check=False)
    Path(targets_file).unlink(missing_ok=True)
    return result.returncode


def parse_nmap_xml(xml_path: Path) -> list[dict]:
    """Parse nmap XML output into a list of service dicts for the services API."""
    services: list[dict] = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return services

    for host_el in root.findall("host"):
        addr_el = host_el.find("address[@addrtype='ipv4']")
        if addr_el is None:
            addr_el = host_el.find("address[@addrtype='ipv6']")
        if addr_el is None:
            continue
        host_ip = addr_el.get("addr", "")

        hostname_el = host_el.find("hostnames/hostname[@type='user']")
        if hostname_el is None:
            hostname_el = host_el.find("hostnames/hostname")
        host_name = hostname_el.get("name", "") if hostname_el is not None else ""
        host = host_name or host_ip

        ports_el = host_el.find("ports")
        if ports_el is None:
            continue
        for port_el in ports_el.findall("port"):
            state_el = port_el.find("state")
            if state_el is None or state_el.get("state") != "open":
                continue
            portid = int(port_el.get("portid", "0"))
            protocol = port_el.get("protocol", "tcp")
            svc_el = port_el.find("service")
            service_name = product = version = ""
            if svc_el is not None:
                service_name = svc_el.get("name", "")
                product = svc_el.get("product", "")
                version = svc_el.get("version", "")
            services.append({
                "host": host,
                "port": portid,
                "protocol": protocol,
                "service_name": service_name,
                "product": product,
                "version": version,
                "state": "open",
                "source": "nmap",
            })
    return services


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
