"""Data management commands."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from cdata.config import get_settings
from cdata.core.index import get_index_manager
from cdata.storage import ParquetStorage
from cdata.web import generate_static_site

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
        # Also remove from index
        index_manager = get_index_manager()
        index_manager.remove_dataset(dataset, "raw" if raw else "processed")
    else:
        console.print(f"[red]Failed to delete '{dataset}'.[/red]")
        raise typer.Exit(1)


@app.command("index")
def show_index():
    """Show the dataset index."""
    index_manager = get_index_manager()
    datasets = index_manager.list_datasets()

    if not datasets:
        console.print("[yellow]No datasets in index. Run 'cdata data rebuild-index' to build it.[/yellow]")
        return

    table = Table(title="Dataset Index")
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("Records", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Last Updated")
    table.add_column("Fetches", justify="right")

    for entry in datasets:
        size_kb = entry.file_size_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        table.add_row(
            entry.name,
            entry.source_id,
            str(entry.record_count),
            size_str,
            entry.last_updated.strftime("%Y-%m-%d %H:%M"),
            str(entry.fetch_count),
        )

    console.print(table)
    console.print(f"\n[dim]Index: {index_manager.index_path}[/dim]")


@app.command("rebuild-index")
def rebuild_index():
    """Rebuild the dataset index from files."""
    index_manager = get_index_manager()

    console.print("Scanning data directories...")
    count = index_manager.rebuild()

    console.print(f"[green]Rebuilt index with {count} datasets.[/green]")
    console.print(f"Index saved to: {index_manager.index_path}")


@app.command("site")
def generate_site(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory"),
    open_browser: bool = typer.Option(False, "--open", help="Open in browser after generating"),
):
    """Generate static HTML frontend for the data index."""
    from pathlib import Path
    import webbrowser

    output_path = Path(output) if output else None
    index_path = generate_static_site(output_path)

    console.print(f"[green]Static site generated![/green]")
    console.print(f"  index.html: {index_path}")
    console.print(f"  index.json: {index_path.parent / 'index.json'}")

    if open_browser:
        webbrowser.open(f"file://{index_path.absolute()}")
