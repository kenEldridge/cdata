"""Configuration commands."""

from pathlib import Path

import typer
from rich.console import Console

from cdata.config import get_settings, load_sources, load_jobs, load_favorites

app = typer.Typer()
console = Console()


@app.command("validate")
def validate_config():
    """Validate configuration files."""
    errors = []
    warnings = []

    try:
        settings = get_settings()
        console.print("[green]Settings loaded.[/green]")
    except Exception as e:
        errors.append(f"Settings error: {e}")

    try:
        sources = load_sources()
        console.print(f"[green]Loaded {len(sources)} sources.[/green]")

        source_ids = set()
        for source in sources:
            if source.id in source_ids:
                warnings.append(f"Duplicate source ID: {source.id}")
            source_ids.add(source.id)
    except Exception as e:
        errors.append(f"Sources error: {e}")

    try:
        jobs = load_jobs()
        console.print(f"[green]Loaded {len(jobs)} jobs.[/green]")

        job_ids = set()
        for job in jobs:
            if job.id in job_ids:
                warnings.append(f"Duplicate job ID: {job.id}")
            job_ids.add(job.id)

            if job.source not in source_ids:
                warnings.append(f"Job '{job.id}' references unknown source: {job.source}")
    except Exception as e:
        errors.append(f"Jobs error: {e}")

    try:
        favorites = load_favorites()
        console.print(f"[green]Loaded {len(favorites.entities)} favorites.[/green]")
    except Exception as e:
        errors.append(f"Favorites error: {e}")

    if warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  - {warning}")

    if errors:
        console.print("\n[red]Errors:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        raise typer.Exit(1)

    if not warnings and not errors:
        console.print("\n[green]All configuration is valid![/green]")


@app.command("init")
def init_config():
    """Initialize configuration directories and example files."""
    settings = get_settings()

    dirs_to_create = [
        settings.config_dir,
        settings.sources_config_dir,
        settings.jobs_config_dir,
        settings.data_dir,
        settings.raw_data_dir,
        settings.processed_data_dir,
        settings.cache_dir,
        settings.logs_dir,
    ]

    for dir_path in dirs_to_create:
        dir_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]Created:[/green] {dir_path}")

    example_sources = settings.sources_config_dir / "example.yaml"
    if not example_sources.exists():
        example_sources.write_text("""# Example source configuration
sources:
  - id: my_stocks
    name: "My Stock Watchlist"
    type: yfinance
    enabled: true
    config:
      symbols:
        - AAPL
        - GOOGL
        - MSFT

  - id: tech_news
    name: "Tech News RSS"
    type: rss
    enabled: true
    config:
      feeds:
        - name: Hacker News
          url: https://news.ycombinator.com/rss
        - name: Lobsters
          url: https://lobste.rs/rss
""")
        console.print(f"[green]Created:[/green] {example_sources}")

    example_jobs = settings.jobs_config_dir / "example.yaml"
    if not example_jobs.exists():
        example_jobs.write_text("""# Example job configuration
jobs:
  - id: daily_stocks
    source: my_stocks
    enabled: true
    description: "Fetch stock data daily at 6 PM"
    schedule:
      type: cron
      expression: "0 18 * * 1-5"
    storage:
      backend: parquet
      path: data/raw/stocks

  - id: hourly_news
    source: tech_news
    enabled: true
    description: "Fetch tech news every hour"
    schedule:
      type: interval
      hours: 1
    storage:
      backend: parquet
""")
        console.print(f"[green]Created:[/green] {example_jobs}")

    favorites_file = settings.config_dir / "favorites.yaml"
    if not favorites_file.exists():
        favorites_file.write_text("""# Tracked favorite entities
entities:
  - id: aapl
    name: Apple Inc.
    sources:
      - my_stocks
    metadata:
      sector: Technology
      ticker: AAPL
""")
        console.print(f"[green]Created:[/green] {favorites_file}")

    console.print("\n[green]Configuration initialized![/green]")
    console.print("Edit the example files in config/ to customize your setup.")


@app.command("show")
def show_config():
    """Show current configuration."""
    settings = get_settings()

    console.print("[bold]Paths:[/bold]")
    console.print(f"  Config dir: {settings.config_dir}")
    console.print(f"  Data dir: {settings.data_dir}")
    console.print(f"  Logs dir: {settings.logs_dir}")

    console.print("\n[bold]HTTP:[/bold]")
    console.print(f"  Timeout: {settings.http_timeout}s")
    console.print(f"  Retries: {settings.http_retries}")

    console.print("\n[bold]Scheduler:[/bold]")
    console.print(f"  Timezone: {settings.scheduler_timezone}")

    console.print("\n[bold]API Keys:[/bold]")
    console.print(f"  AlphaVantage: {'[green]Set[/green]' if settings.alphavantage_api_key else '[yellow]Not set[/yellow]'}")
    console.print(f"  NewsAPI: {'[green]Set[/green]' if settings.newsapi_key else '[yellow]Not set[/yellow]'}")
