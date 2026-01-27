"""cdata init - scaffold a new project directory."""

from pathlib import Path

import typer
from rich.console import Console

console = Console()

_ENV_CONTENT = """\
# cdata project configuration
CDATA_CONFIG_DIR=./config
CDATA_DATA_DIR=./data
CDATA_SOURCES_MODULE_DIR=./sources

# API Keys (optional)
# FRED_API_KEY=
# BLS_API_KEY=
"""

_SOURCES_YAML_CONTENT = """\
# Define your data sources here.
# Each source uses a built-in type (yfinance, fred, bls, rss, scraping, etc.)
# See: cdata sources types
#
# sources:
#   - id: my_stocks
#     name: "My Stock Watchlist"
#     type: yfinance
#     enabled: true
#     config:
#       symbols: [AAPL, MSFT, GOOG]
#       period: "1y"
#       interval: "1d"

sources: []
"""

_EXAMPLE_SOURCE_CONTENT = '''\
"""Example custom source.

Rename this file (remove the _ prefix) and implement your source.
It will be auto-discovered by cdata on next run.
"""

from typing import Any
from datetime import datetime

from cdata.sources.base import BaseSource
from cdata.models import FetchResult


class ExampleSource(BaseSource):
    source_type = "example"

    def fetch(self, **kwargs: Any) -> FetchResult:
        started_at = datetime.utcnow()
        records = []
        # Your fetch logic here — use self._create_record(data={...})
        return self._create_result(records, started_at)

    def test_connection(self) -> bool:
        return True
'''

_FILES: list[tuple[str, str]] = [
    (".env", _ENV_CONTENT),
    ("config/sources/sources.yaml", _SOURCES_YAML_CONTENT),
    ("sources/_example.py", _EXAMPLE_SOURCE_CONTENT),
]


def init_project() -> None:
    """Scaffold a new cdata project in the current directory."""
    root = Path.cwd()
    created: list[str] = []
    skipped: list[str] = []

    # Create directories
    for dir_path in ("config/sources", "data", "sources"):
        full = root / dir_path
        full.mkdir(parents=True, exist_ok=True)

    # Write files (never overwrite)
    for rel_path, content in _FILES:
        full = root / rel_path
        if full.exists():
            skipped.append(rel_path)
        else:
            full.write_text(content)
            created.append(rel_path)

    if created:
        console.print("[green]Created:[/green]")
        for f in created:
            console.print(f"  {f}")

    if skipped:
        console.print("[yellow]Skipped (already exists):[/yellow]")
        for f in skipped:
            console.print(f"  {f}")

    if not created and not skipped:
        console.print("[dim]Nothing to do.[/dim]")

    console.print("\n[bold]Project initialized.[/bold] Edit .env and config/sources/sources.yaml to get started.")
