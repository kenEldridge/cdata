"""Sources management commands."""

import typer
from rich.console import Console
from rich.table import Table

from cdata.config import load_sources
from cdata.core import get_registry
from cdata.core.fetcher import Fetcher

app = typer.Typer()
console = Console()


@app.command("list")
def list_sources():
    """List configured data sources."""
    sources = load_sources()
    registry = get_registry()

    if not sources:
        console.print("[yellow]No sources configured.[/yellow]")
        console.print("Add sources in config/sources/*.yaml")
        return

    table = Table(title="Configured Sources")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type", style="magenta")
    table.add_column("Enabled")
    table.add_column("Registered")

    for source in sources:
        enabled = "[green]Yes[/green]" if source.enabled else "[red]No[/red]"
        registered = "[green]Yes[/green]" if registry.is_registered(source.type) else "[red]No[/red]"
        table.add_row(source.id, source.name, source.type, enabled, registered)

    console.print(table)


@app.command("types")
def list_types():
    """List available source types."""
    registry = get_registry()
    types = registry.list_source_types()

    if not types:
        console.print("[yellow]No source types registered.[/yellow]")
        return

    table = Table(title="Available Source Types")
    table.add_column("Type", style="cyan")

    for source_type in types:
        table.add_row(source_type)

    console.print(table)


@app.command("test")
def test_source(
    source_id: str = typer.Argument(..., help="Source ID to test"),
):
    """Test connectivity to a source."""
    fetcher = Fetcher()

    with console.status(f"Testing [bold]{source_id}[/bold]..."):
        success = fetcher.test_source(source_id)

    if success:
        console.print(f"[green]Connection successful![/green]")
    else:
        console.print(f"[red]Connection failed![/red]")
        raise typer.Exit(1)


@app.command("show")
def show_source(
    source_id: str = typer.Argument(..., help="Source ID to show"),
):
    """Show details of a source."""
    sources = load_sources()
    source = next((s for s in sources if s.id == source_id), None)

    if not source:
        console.print(f"[red]Source '{source_id}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]ID:[/bold] {source.id}")
    console.print(f"[bold]Name:[/bold] {source.name}")
    console.print(f"[bold]Type:[/bold] {source.type}")
    console.print(f"[bold]Enabled:[/bold] {source.enabled}")
    if source.description:
        console.print(f"[bold]Description:[/bold] {source.description}")

    if source.config:
        console.print("[bold]Config:[/bold]")
        for key, value in source.config.items():
            console.print(f"  {key}: {value}")
