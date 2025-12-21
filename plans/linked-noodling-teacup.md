# cdata - Personal Data Scavenger

## Overview
A Python CLI tool for pulling data from the web at will. Supports REST APIs, web scraping, RSS feeds, and Linked Data (RDF/SPARQL). Stores data in Parquet (preferred), CSV, or JSON.

## User Requirements
- **Language**: Python
- **Interface**: CLI commands
- **Data Sources**: REST APIs, web scraping, Linked Data/RDF/SPARQL
- **Storage**: Parquet (preferred), CSV/JSON fallbacks
- **Secrets**: .env file
- **Config**: YAML files
- **Scheduling**: Built-in scheduler (APScheduler)
- **Built-in Sources**: Financial data, News/RSS feeds

---

## Project Structure

```
cdata/
├── .env.example                  # Template for secrets
├── .gitignore
├── pyproject.toml                # Dependencies & entry points
├── README.md
├── plans/                        # Project plans (symlinked for visibility)
│
├── config/
│   ├── sources/                  # Data source definitions
│   │   ├── financial.yaml
│   │   ├── news.yaml
│   │   └── sparql.yaml
│   ├── jobs/                     # Scheduled fetch jobs
│   ├── favorites.yaml            # Tracked entities
│   └── scheduler.yaml            # Scheduler settings
│
├── data/
│   ├── raw/                      # Fetched data (by source/date)
│   ├── processed/                # Transformed data
│   └── cache/                    # HTTP cache
│
├── logs/
│
└── src/cdata/
    ├── __init__.py
    ├── __main__.py
    ├── cli/                      # Typer CLI
    │   ├── app.py                # Main app
    │   └── commands/             # fetch, schedule, sources, jobs, data, favorites, config
    ├── core/
    │   ├── fetcher.py            # Fetch orchestrator
    │   ├── scheduler.py          # APScheduler wrapper
    │   ├── pipeline.py           # Transform pipeline
    │   └── registry.py           # Plugin discovery
    ├── sources/
    │   ├── base.py               # Abstract BaseSource
    │   ├── api/                  # REST API sources
    │   │   └── financial/        # yfinance, alphavantage, crypto
    │   │   └── news/             # newsapi
    │   ├── rss/                  # feedparser
    │   ├── scraping/             # BeautifulSoup
    │   └── linked_data/          # rdflib, SPARQLWrapper
    ├── storage/
    │   ├── base.py               # Abstract storage
    │   ├── parquet.py            # PyArrow
    │   ├── csv.py
    │   └── json.py
    ├── config/
    │   ├── loader.py             # YAML loading
    │   ├── schema.py             # Pydantic models
    │   └── env.py                # dotenv handling
    └── models/                   # Data models
```

---

## CLI Commands

```
cdata fetch run <job-id>          # Run a job
cdata fetch source <source-id>    # Fetch from source
cdata schedule start [--daemon]   # Start scheduler
cdata schedule stop               # Stop scheduler
cdata schedule status             # Show status
cdata sources list                # List sources
cdata sources test <id>           # Test connectivity
cdata jobs list                   # List jobs
cdata data list                   # List datasets
cdata data show <dataset>         # Preview data
cdata data query "<sql>"          # Query with DuckDB
cdata favorites sync              # Fetch all favorites
cdata config validate             # Validate configs
```

---

## Key Dependencies

```toml
dependencies = [
    "typer[all]>=0.9.0",          # CLI
    "rich>=13.0",                  # Pretty output
    "pyyaml>=6.0",                 # Config
    "pydantic>=2.0",               # Validation
    "python-dotenv>=1.0",          # Secrets
    "httpx>=0.25",                 # HTTP client
    "beautifulsoup4>=4.12",        # Scraping
    "pandas>=2.0",                 # Data frames
    "pyarrow>=14.0",               # Parquet
    "yfinance>=0.2",               # Stocks
    "feedparser>=6.0",             # RSS
    "rdflib>=7.0",                 # RDF
    "sparqlwrapper>=2.0",          # SPARQL
    "apscheduler>=3.10",           # Scheduling
]
```

---

## Implementation Steps

### Phase 1: Project Scaffold
1. Create directory structure
2. Write `pyproject.toml` with dependencies
3. Create `README.md`
4. Create `.env.example` and `.gitignore`
5. Create `plans/` symlink for visibility

### Phase 2: Core Infrastructure
1. `src/cdata/config/` - YAML loading, Pydantic schemas, env handling
2. `src/cdata/models/` - Source, Job, Record models
3. `src/cdata/storage/` - Parquet/CSV/JSON backends

### Phase 3: Source Framework
1. `src/cdata/sources/base.py` - Abstract BaseSource
2. `src/cdata/core/registry.py` - Plugin discovery via entry points
3. `src/cdata/core/fetcher.py` - Fetch orchestration

### Phase 4: Built-in Sources
1. `sources/api/financial/yfinance.py` - Stock data
2. `sources/rss/feedparser.py` - RSS feeds
3. `sources/linked_data/sparql.py` - SPARQL endpoints

### Phase 5: CLI
1. `src/cdata/cli/app.py` - Main Typer app
2. Command modules: fetch, sources, jobs, data, config, favorites
3. `__main__.py` entry point

### Phase 6: Scheduler
1. `src/cdata/core/scheduler.py` - APScheduler integration
2. `cli/commands/schedule.py` - Schedule commands
3. Daemon mode support

### Phase 7: Config Files
1. `config/sources/financial.yaml` - Stock/crypto configs
2. `config/sources/news.yaml` - RSS feed configs
3. `config/scheduler.yaml` - Scheduler settings
4. `config/favorites.yaml` - Tracked entities

---

## Critical Files

| File | Purpose |
|------|---------|
| `src/cdata/sources/base.py` | Abstract source interface |
| `src/cdata/core/registry.py` | Plugin discovery |
| `src/cdata/cli/app.py` | CLI entry point |
| `src/cdata/core/scheduler.py` | APScheduler integration |
| `src/cdata/config/schema.py` | Pydantic config models |

---

## Plans Visibility

A `plans/` symlink will be created in the project root pointing to `~/.claude/plans/`, making all Claude Code plans easily accessible from within the cdata workspace.

```bash
# Created during scaffold phase
ln -s ~/.claude/plans ./plans
```
