import typer
from rich.console import Console
from rich.table import Table

from vardrrunner import api, config

console = Console()
app = typer.Typer(help="Authentication commands.")


@app.command("vardrmap")
def login_vardrmap(
    api_url: str = typer.Option(None, "--url", help="VardrMap API base URL"),
    api_key: str = typer.Option(None, "--key", help="vmap_ API key"),
):
    """Authenticate vardrrunner with your VardrMap instance."""
    if not api_url:
        api_url = typer.prompt("VardrMap API URL").strip().rstrip("/")
    if not api_key:
        api_key = typer.prompt("API key (vmap_...)", hide_input=True).strip()

    if not api_key.startswith("vmap_"):
        console.print("[red]Error:[/red] API key must start with vmap_")
        raise typer.Exit(1)

    try:
        config.validate_api_url(api_url)
    except config.InvalidApiUrl as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e

    # Verify the key works before saving
    console.print("Verifying credentials…")
    try:
        client = api.VardrMapClient(api_url, api_key)
        user = client.whoami()
    except Exception as e:
        console.print(f"[red]Authentication failed:[/red] {e}")
        raise typer.Exit(1) from e

    config.save({"api_url": api_url, "api_key": api_key})
    console.print(
        f"[green]Logged in[/green] as [bold]{user.get('username') or user.get('github_id')}[/bold]"
    )
    console.print(f"Config saved to [dim]{config.CONFIG_FILE}[/dim]")
    console.print(
        "[yellow]Treat this file like a secret — it contains your API key in plaintext.[/yellow]"
    )


def whoami():
    """Show the identity associated with the configured API key."""
    url, key = config.require_auth()
    try:
        client = api.VardrMapClient(url, key)
        user = client.whoami()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[dim]GitHub ID[/dim]", str(user.get("github_id", "—")))
    table.add_row("[dim]Username[/dim]", str(user.get("username", "—")))
    table.add_row("[dim]Email[/dim]", str(user.get("email", "—")))
    table.add_row("[dim]API URL[/dim]", url)
    console.print(table)
