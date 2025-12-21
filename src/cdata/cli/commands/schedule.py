"""Scheduler commands."""

import logging
import signal
import sys

import typer
from rich.console import Console
from rich.table import Table

from cdata.core.scheduler import Scheduler

app = typer.Typer()
console = Console()


@app.command("start")
def start_scheduler(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background (daemon mode)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Start the scheduler."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    scheduler = Scheduler(daemon=daemon)

    def signal_handler(sig, frame):
        console.print("\n[yellow]Stopping scheduler...[/yellow]")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[bold]Starting cdata scheduler...[/bold]")

    try:
        scheduler.start()

        if daemon:
            console.print("[green]Scheduler running in background.[/green]")
            console.print("Press Ctrl+C to stop.")
            signal.pause()
        else:
            console.print("[green]Scheduler running.[/green]")
            console.print("Press Ctrl+C to stop.")

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping scheduler...[/yellow]")
        scheduler.stop()


@app.command("status")
def scheduler_status():
    """Show scheduler status."""
    scheduler = Scheduler(daemon=True)

    jobs_info = scheduler.get_jobs()

    if not jobs_info:
        console.print("[yellow]No jobs scheduled.[/yellow]")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Next Run")

    for job in jobs_info:
        next_run = job["next_run"] or "Not scheduled"
        table.add_row(job["id"], job["name"], next_run)

    console.print(table)
