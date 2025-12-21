"""Fetch commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from cdata.core.fetcher import Fetcher
from cdata.models import FetchStatus

app = typer.Typer()
console = Console()


@app.command("run")
def run_job(
    job_id: str = typer.Argument(..., help="Job ID to run"),
):
    """Run a fetch job."""
    fetcher = Fetcher()

    with console.status(f"Running job [bold]{job_id}[/bold]..."):
        result = fetcher.run_job(job_id)

    if result.status == FetchStatus.SUCCESS:
        console.print(f"[green]Success![/green] Fetched {result.record_count} records.")
    elif result.status == FetchStatus.PARTIAL:
        console.print(f"[yellow]Partial success.[/yellow] Fetched {result.record_count} records.")
        if result.error:
            console.print(f"[yellow]Warnings:[/yellow] {result.error}")
    else:
        console.print(f"[red]Failed![/red] {result.error}")
        raise typer.Exit(1)


@app.command("source")
def fetch_source(
    source_id: str = typer.Argument(..., help="Source ID to fetch from"),
    symbols: Optional[str] = typer.Option(None, "--symbols", "-s", help="Comma-separated symbols (for financial sources)"),
    period: str = typer.Option("1mo", "--period", "-p", help="Data period (for financial sources)"),
    no_save: bool = typer.Option(False, "--no-save", help="Don't save fetched data"),
):
    """Fetch data from a specific source."""
    fetcher = Fetcher()

    kwargs = {}
    if symbols:
        kwargs["symbols"] = [s.strip() for s in symbols.split(",")]
    if period:
        kwargs["period"] = period

    with console.status(f"Fetching from [bold]{source_id}[/bold]..."):
        result = fetcher.fetch_source(source_id, save=not no_save, **kwargs)

    if result.status == FetchStatus.SUCCESS:
        console.print(f"[green]Success![/green] Fetched {result.record_count} records.")

        if result.records and result.record_count <= 10:
            table = Table(title="Fetched Data")
            if result.records:
                for key in list(result.records[0].data.keys())[:6]:
                    table.add_column(key)
                for record in result.records[:10]:
                    row = [str(record.data.get(k, ""))[:50] for k in list(result.records[0].data.keys())[:6]]
                    table.add_row(*row)
                console.print(table)
    elif result.status == FetchStatus.PARTIAL:
        console.print(f"[yellow]Partial success.[/yellow] Fetched {result.record_count} records.")
        if result.error:
            console.print(f"[yellow]Warnings:[/yellow] {result.error}")
    else:
        console.print(f"[red]Failed![/red] {result.error}")
        raise typer.Exit(1)
