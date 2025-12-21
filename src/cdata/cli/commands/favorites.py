"""Favorites management commands."""

import typer
from rich.console import Console
from rich.table import Table

from cdata.config import load_favorites, load_sources
from cdata.core.fetcher import Fetcher

app = typer.Typer()
console = Console()


@app.command("list")
def list_favorites():
    """List tracked favorite entities."""
    favorites = load_favorites()

    if not favorites.entities:
        console.print("[yellow]No favorites configured.[/yellow]")
        console.print("Add favorites in config/favorites.yaml")
        return

    table = Table(title="Favorite Entities")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Sources")

    for entity in favorites.entities:
        sources = ", ".join(entity.sources) if entity.sources else "[dim]None[/dim]"
        table.add_row(entity.id, entity.name, sources)

    console.print(table)


@app.command("show")
def show_favorite(
    entity_id: str = typer.Argument(..., help="Entity ID to show"),
):
    """Show details of a favorite entity."""
    favorites = load_favorites()
    entity = next((e for e in favorites.entities if e.id == entity_id), None)

    if not entity:
        console.print(f"[red]Entity '{entity_id}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]ID:[/bold] {entity.id}")
    console.print(f"[bold]Name:[/bold] {entity.name}")
    console.print(f"[bold]Sources:[/bold] {', '.join(entity.sources) if entity.sources else 'None'}")

    if entity.metadata:
        console.print("[bold]Metadata:[/bold]")
        for key, value in entity.metadata.items():
            console.print(f"  {key}: {value}")


@app.command("sync")
def sync_favorites(
    entity_id: str = typer.Option(None, "--entity", "-e", help="Sync specific entity only"),
):
    """Fetch data for all favorite entities from their sources."""
    favorites = load_favorites()
    sources = {s.id: s for s in load_sources()}
    fetcher = Fetcher()

    entities = favorites.entities
    if entity_id:
        entities = [e for e in entities if e.id == entity_id]
        if not entities:
            console.print(f"[red]Entity '{entity_id}' not found.[/red]")
            raise typer.Exit(1)

    total_records = 0
    errors = []

    for entity in entities:
        for source_id in entity.sources:
            if source_id not in sources:
                errors.append(f"Source '{source_id}' not found for entity '{entity.id}'")
                continue

            source = sources[source_id]
            console.print(f"Syncing [bold]{entity.name}[/bold] from [cyan]{source_id}[/cyan]...")

            kwargs = {}
            if source.type == "yfinance" and "ticker" in entity.metadata:
                kwargs["symbols"] = [entity.metadata["ticker"]]

            result = fetcher.fetch_source_config(source, **kwargs)

            if result.error:
                errors.append(f"{entity.id}/{source_id}: {result.error}")
            else:
                total_records += result.record_count
                console.print(f"  [green]Fetched {result.record_count} records[/green]")

    console.print(f"\n[bold]Sync complete.[/bold] Total records: {total_records}")

    if errors:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in errors:
            console.print(f"  - {error}")
