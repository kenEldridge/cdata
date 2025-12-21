"""Jobs management commands."""

import typer
from rich.console import Console
from rich.table import Table

from cdata.config import load_jobs, load_sources

app = typer.Typer()
console = Console()


@app.command("list")
def list_jobs():
    """List configured fetch jobs."""
    jobs = load_jobs()
    sources = {s.id: s for s in load_sources()}

    if not jobs:
        console.print("[yellow]No jobs configured.[/yellow]")
        console.print("Add jobs in config/jobs/*.yaml")
        return

    table = Table(title="Configured Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Schedule")
    table.add_column("Storage")
    table.add_column("Enabled")

    for job in jobs:
        source_exists = job.source in sources
        source_display = job.source if source_exists else f"[red]{job.source} (missing)[/red]"

        schedule = "Manual"
        if job.schedule:
            if job.schedule.expression:
                schedule = f"cron: {job.schedule.expression}"
            else:
                parts = []
                if job.schedule.hours:
                    parts.append(f"{job.schedule.hours}h")
                if job.schedule.minutes:
                    parts.append(f"{job.schedule.minutes}m")
                if job.schedule.seconds:
                    parts.append(f"{job.schedule.seconds}s")
                schedule = f"every {' '.join(parts)}" if parts else "Manual"

        storage = job.storage.backend.value
        enabled = "[green]Yes[/green]" if job.enabled else "[red]No[/red]"

        table.add_row(job.id, source_display, schedule, storage, enabled)

    console.print(table)


@app.command("show")
def show_job(
    job_id: str = typer.Argument(..., help="Job ID to show"),
):
    """Show details of a job."""
    jobs = load_jobs()
    job = next((j for j in jobs if j.id == job_id), None)

    if not job:
        console.print(f"[red]Job '{job_id}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]ID:[/bold] {job.id}")
    console.print(f"[bold]Source:[/bold] {job.source}")
    console.print(f"[bold]Enabled:[/bold] {job.enabled}")

    if job.description:
        console.print(f"[bold]Description:[/bold] {job.description}")

    if job.schedule:
        console.print("[bold]Schedule:[/bold]")
        console.print(f"  Type: {job.schedule.type.value}")
        if job.schedule.expression:
            console.print(f"  Expression: {job.schedule.expression}")
        if job.schedule.hours:
            console.print(f"  Hours: {job.schedule.hours}")
        if job.schedule.minutes:
            console.print(f"  Minutes: {job.schedule.minutes}")
        if job.schedule.seconds:
            console.print(f"  Seconds: {job.schedule.seconds}")

    console.print("[bold]Storage:[/bold]")
    console.print(f"  Backend: {job.storage.backend.value}")
    if job.storage.path:
        console.print(f"  Path: {job.storage.path}")
    if job.storage.partition_by:
        console.print(f"  Partition by: {', '.join(job.storage.partition_by)}")
