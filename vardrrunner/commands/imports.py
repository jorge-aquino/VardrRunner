from pathlib import Path

import typer
from rich.console import Console

from vardrrunner import api, config

console = Console()

SUPPORTED_TOOLS = ["nuclei", "httpx", "ffuf"]


def import_file(tool: str, program_id: str, file: Path):
    """Upload a tool output file directly to VardrMap without running the tool."""
    if tool not in SUPPORTED_TOOLS:
        console.print(f"[red]Unsupported tool:[/red] {tool}. Supported: {', '.join(SUPPORTED_TOOLS)}")
        raise typer.Exit(1)

    if not file.exists():
        console.print(f"[red]File not found:[/red] {file}")
        raise typer.Exit(1)

    url, key = config.require_auth()
    try:
        client = api.VardrMapClient(url, key)
        result = client.import_file(program_id, tool, str(file))
    except Exception as e:
        console.print(f"[red]Import failed:[/red] {e}")
        raise typer.Exit(1)

    record = result.get("import_record", {})
    count  = record.get("imported_count", "?")
    console.print(f"[green]Imported[/green] {count} {tool} result(s) into program [bold]{program_id}[/bold]")
