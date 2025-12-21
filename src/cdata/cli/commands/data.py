"""Data management commands."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from cdata.config import get_settings
from cdata.storage import ParquetStorage

app = typer.Typer()
console = Console()


@app.command("list")
def list_datasets():
    """List stored datasets."""
    settings = get_settings()

    raw_storage = ParquetStorage(settings.raw_data_dir)
    processed_storage = ParquetStorage(settings.processed_data_dir)

    raw_datasets = raw_storage.list_datasets()
    processed_datasets = processed_storage.list_datasets()

    if not raw_datasets and not processed_datasets:
        console.print("[yellow]No datasets found.[/yellow]")
        return

    if raw_datasets:
        table = Table(title="Raw Datasets")
        table.add_column("Name", style="cyan")
        table.add_column("Path")

        for name in raw_datasets:
            path = settings.raw_data_dir / f"{name}.parquet"
            if not path.exists():
                path = settings.raw_data_dir / name
            table.add_row(name, str(path))

        console.print(table)

    if processed_datasets:
        table = Table(title="Processed Datasets")
        table.add_column("Name", style="cyan")
        table.add_column("Path")

        for name in processed_datasets:
            path = settings.processed_data_dir / f"{name}.parquet"
            if not path.exists():
                path = settings.processed_data_dir / name
            table.add_row(name, str(path))

        console.print(table)


@app.command("show")
def show_dataset(
    dataset: str = typer.Argument(..., help="Dataset name to preview"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of rows to show"),
    raw: bool = typer.Option(True, "--raw/--processed", help="Look in raw or processed data"),
):
    """Preview a dataset."""
    settings = get_settings()
    base_path = settings.raw_data_dir if raw else settings.processed_data_dir

    storage = ParquetStorage(base_path)

    if not storage.exists(dataset):
        console.print(f"[red]Dataset '{dataset}' not found.[/red]")
        raise typer.Exit(1)

    df = storage.read(dataset)

    if df.empty:
        console.print("[yellow]Dataset is empty.[/yellow]")
        return

    console.print(f"[bold]Shape:[/bold] {df.shape[0]} rows x {df.shape[1]} columns")
    console.print(f"[bold]Columns:[/bold] {', '.join(df.columns)}")
    console.print()

    table = Table(title=f"Preview: {dataset}")
    for col in df.columns[:8]:
        table.add_column(str(col))

    for _, row in df.head(limit).iterrows():
        values = [str(row[col])[:40] for col in df.columns[:8]]
        table.add_row(*values)

    console.print(table)


@app.command("query")
def query_data(
    sql: str = typer.Argument(..., help="SQL query to execute"),
):
    """Query data using DuckDB SQL."""
    try:
        import duckdb
    except ImportError:
        console.print("[red]DuckDB not installed. Run: pip install duckdb[/red]")
        raise typer.Exit(1)

    settings = get_settings()

    conn = duckdb.connect()
    conn.execute(f"CREATE VIEW raw AS SELECT * FROM parquet_scan('{settings.raw_data_dir}/**/*.parquet')")

    try:
        result = conn.execute(sql).fetchdf()

        if result.empty:
            console.print("[yellow]No results.[/yellow]")
            return

        table = Table(title="Query Results")
        for col in result.columns[:10]:
            table.add_column(str(col))

        for _, row in result.head(50).iterrows():
            values = [str(row[col])[:50] for col in result.columns[:10]]
            table.add_row(*values)

        console.print(table)
        console.print(f"\n[dim]Showing {min(50, len(result))} of {len(result)} results[/dim]")

    except Exception as e:
        console.print(f"[red]Query error:[/red] {e}")
        raise typer.Exit(1)


@app.command("delete")
def delete_dataset(
    dataset: str = typer.Argument(..., help="Dataset name to delete"),
    raw: bool = typer.Option(True, "--raw/--processed", help="Look in raw or processed data"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a dataset."""
    settings = get_settings()
    base_path = settings.raw_data_dir if raw else settings.processed_data_dir

    storage = ParquetStorage(base_path)

    if not storage.exists(dataset):
        console.print(f"[red]Dataset '{dataset}' not found.[/red]")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(f"Delete dataset '{dataset}'?")
        if not confirm:
            console.print("Cancelled.")
            return

    if storage.delete(dataset):
        console.print(f"[green]Deleted '{dataset}'.[/green]")
    else:
        console.print(f"[red]Failed to delete '{dataset}'.[/red]")
        raise typer.Exit(1)
