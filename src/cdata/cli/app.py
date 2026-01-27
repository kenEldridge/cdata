"""Main Typer CLI application."""

import typer
from rich.console import Console

from cdata.cli.commands import fetch, sources, jobs, data, schedule, config, favorites
from cdata.cli.commands.init import init_project

console = Console()

app = typer.Typer(
    name="cdata",
    help="Personal data scavenger - pull data from the web at will.",
    no_args_is_help=True,
)

app.add_typer(fetch.app, name="fetch", help="Fetch data from sources")
app.add_typer(sources.app, name="sources", help="Manage data sources")
app.add_typer(jobs.app, name="jobs", help="Manage fetch jobs")
app.add_typer(data.app, name="data", help="Query and manage stored data")
app.add_typer(schedule.app, name="schedule", help="Manage the scheduler")
app.add_typer(config.app, name="config", help="Configuration utilities")
app.add_typer(favorites.app, name="favorites", help="Manage favorite entities")

app.command("init")(init_project)


@app.callback()
def main():
    """cdata - Personal data scavenger."""
    from dotenv import load_dotenv

    load_dotenv()


if __name__ == "__main__":
    app()
