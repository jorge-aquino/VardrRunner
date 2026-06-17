"""
Tool handlers — one per job type.

Each handler knows four things about its tool: how to validate its config, how to
resolve its targets, how to execute it, and how to upload the result. The uniform
job lifecycle (availability check → claim → events → done/fail) lives in
``commands/jobs.py`` and drives these handlers, so every tool gets identical
claim/event/failure handling and the executor stays small.

Adding a tool is a one-file change: write a handler and register it below.
"""

import json
from pathlib import Path
from typing import Any, Generic, TypeVar

from vardrrunner import api, configs, runner
from vardrrunner.targets import _is_wildcard, _resolve_targets

C = TypeVar("C")


class ToolHandler(Generic[C]):
    """Base class for a tool handler. ``tool`` is the executable name on PATH."""

    tool: str = ""

    def parse_config(self, cfg: dict) -> C:
        raise NotImplementedError

    def resolve_targets(
        self, client: api.VardrMapClient, program_id: str, target_source: str, config: C
    ) -> list[str]:
        raise NotImplementedError

    def running_label(self, targets: list[str], config: C) -> str:
        return f"{self.tool} against {len(targets)} target(s)"

    def execute(self, targets: list[str], run_dir: Path, config: C) -> Path | None:
        """Run the tool. Return the artifact to upload, or None if nothing was produced."""
        raise NotImplementedError

    def upload(self, client: api.VardrMapClient, program_id: str, output: Path) -> str:
        """Push the artifact to the backend. Return a one-line human summary."""
        raise NotImplementedError


def _resolve_standard(
    client: api.VardrMapClient, program_id: str, target_source: str, config: Any
) -> list[str]:
    """Scope/recon target resolution shared by httpx, nuclei, and nmap."""
    return _resolve_targets(
        client,
        program_id,
        scope=(target_source == "scope"),
        from_recon=(target_source == "recon"),
        target=None,
        targets_file=None,
        status_code=getattr(config, "status_code", None),
        limit=config.limit,
    )


class HttpxHandler(ToolHandler[configs.HttpxConfig]):
    tool = "httpx"

    def parse_config(self, cfg: dict) -> configs.HttpxConfig:
        return configs.HttpxConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        return _resolve_standard(client, program_id, target_source, config)

    def execute(self, targets, run_dir, config):
        output = run_dir / "httpx.jsonl"
        runner.run_httpx(targets, output, timeout=config.timeout)
        return output

    def upload(self, client, program_id, output):
        result = client.import_file(program_id, "httpx", str(output))
        count = result.get("import_record", {}).get("imported_count", "?")
        return f"imported {count} result(s)"


class NucleiHandler(ToolHandler[configs.NucleiConfig]):
    tool = "nuclei"

    def parse_config(self, cfg: dict) -> configs.NucleiConfig:
        return configs.NucleiConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        return _resolve_standard(client, program_id, target_source, config)

    def running_label(self, targets, config):
        label = f"severity={config.severity}" if config.severity else "all"
        return f"nuclei ({label}) against {len(targets)} target(s)"

    def execute(self, targets, run_dir, config):
        output = run_dir / "nuclei.jsonl"
        runner.run_nuclei(
            targets,
            output,
            severity=config.severity,
            templates=config.templates,
            timeout=config.timeout,
        )
        return output

    def upload(self, client, program_id, output):
        result = client.import_file(program_id, "nuclei", str(output))
        count = result.get("import_record", {}).get("imported_count", "?")
        return f"imported {count} finding(s)"


class NmapHandler(ToolHandler[configs.NmapConfig]):
    tool = "nmap"

    def parse_config(self, cfg: dict) -> configs.NmapConfig:
        return configs.NmapConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        raw = _resolve_standard(client, program_id, target_source, config)
        # nmap needs bare hosts, not full URLs; normalize and de-duplicate.
        return list(dict.fromkeys(runner.strip_url_to_host(t) for t in raw if t.strip()))

    def running_label(self, targets, config):
        return f"nmap --top-ports {config.top_ports} against {len(targets)} target(s)"

    def execute(self, targets, run_dir, config):
        xml_path = run_dir / "nmap.xml"
        runner.run_nmap(
            targets,
            xml_path,
            top_ports=config.top_ports,
            timing=config.timing,
            timeout=config.timeout,
        )
        return xml_path

    def upload(self, client, program_id, output):
        services = runner.parse_nmap_xml(output)
        if not services:
            return "no open ports found"
        result = client.create_services(program_id, services)
        created = result.get("created", 0)
        updated = result.get("updated", 0)
        return f"{created} new, {updated} updated service(s)"


class SubfinderHandler(ToolHandler[configs.SubfinderConfig]):
    tool = "subfinder"

    def parse_config(self, cfg: dict) -> configs.SubfinderConfig:
        return configs.SubfinderConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        # subfinder enumerates wildcard scope entries (*.example.com → example.com),
        # regardless of target_source.
        raw = client.scope(program_id)
        domains = []
        for item in raw.get("in", []):
            val = item.get("value", "")
            if _is_wildcard(val):
                stripped = val.lstrip("*").lstrip(".")
                if stripped:
                    domains.append(stripped)
        return domains

    def running_label(self, targets, config):
        return f"subfinder on {len(targets)} domain(s)"

    def execute(self, targets, run_dir, config):
        sf_output = run_dir / "subfinder.txt"
        runner.run_subfinder(targets, sf_output, timeout=config.timeout)
        if not sf_output.exists() or sf_output.stat().st_size == 0:
            return None
        hosts = [line.strip() for line in sf_output.read_text().splitlines() if line.strip()]
        if not hosts:
            return None
        # Convert discovered hosts into httpx-compatible JSONL for the import endpoint.
        jsonl_path = run_dir / "subfinder_httpx.jsonl"
        with jsonl_path.open("w") as fh:
            for host in hosts:
                fh.write(json.dumps({"host": host, "source": "subfinder"}) + "\n")
        return jsonl_path

    def upload(self, client, program_id, output):
        result = client.import_file(program_id, "httpx", str(output))
        count = result.get("import_record", {}).get("imported_count", "?")
        return f"imported {count} subdomain(s) as recon targets"


class DnsxHandler(ToolHandler[configs.DnsxConfig]):
    tool = "dnsx"

    def parse_config(self, cfg: dict) -> configs.DnsxConfig:
        return configs.DnsxConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        raw = _resolve_standard(client, program_id, target_source, config)
        # dnsx resolves bare hostnames, not URLs.
        return list(dict.fromkeys(runner.strip_url_to_host(t) for t in raw if t.strip()))

    def running_label(self, targets, config):
        return f"dnsx on {len(targets)} host(s)"

    def execute(self, targets, run_dir, config):
        out = run_dir / "dnsx.txt"
        runner.run_dnsx(targets, out, timeout=config.timeout)
        if not out.exists() or out.stat().st_size == 0:
            return None
        hosts = [line.strip() for line in out.read_text().splitlines() if line.strip()]
        if not hosts:
            return None
        # Resolvable hosts become recon targets (httpx-compatible JSONL).
        jsonl_path = run_dir / "dnsx_httpx.jsonl"
        with jsonl_path.open("w") as fh:
            for host in hosts:
                fh.write(json.dumps({"host": host, "source": "dnsx"}) + "\n")
        return jsonl_path

    def upload(self, client, program_id, output):
        result = client.import_file(program_id, "httpx", str(output))
        count = result.get("import_record", {}).get("imported_count", "?")
        return f"imported {count} resolvable host(s)"


class NaabuHandler(ToolHandler[configs.NaabuConfig]):
    tool = "naabu"

    def parse_config(self, cfg: dict) -> configs.NaabuConfig:
        return configs.NaabuConfig.from_dict(cfg)

    def resolve_targets(self, client, program_id, target_source, config):
        raw = _resolve_standard(client, program_id, target_source, config)
        return list(dict.fromkeys(runner.strip_url_to_host(t) for t in raw if t.strip()))

    def running_label(self, targets, config):
        return f"naabu --top-ports {config.top_ports} on {len(targets)} host(s)"

    def execute(self, targets, run_dir, config):
        out = run_dir / "naabu.json"
        runner.run_naabu(targets, out, top_ports=config.top_ports, timeout=config.timeout)
        return out

    def upload(self, client, program_id, output):
        services = runner.parse_naabu_json(output)
        if not services:
            return "no open ports found"
        result = client.create_services(program_id, services)
        created = result.get("created", 0)
        updated = result.get("updated", 0)
        return f"{created} new, {updated} updated service(s)"


# Registry: job type → handler. Add a tool by adding a handler here.
REGISTRY: dict[str, ToolHandler[Any]] = {
    h.tool: h
    for h in (
        HttpxHandler(),
        NucleiHandler(),
        NmapHandler(),
        SubfinderHandler(),
        DnsxHandler(),
        NaabuHandler(),
    )
}
