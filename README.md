# cdata

Personal data scavenger - pull data from the web at will.

## Features

- **Multiple Data Sources**: REST APIs, web scraping, RSS/Atom feeds, Linked Data (RDF/SPARQL)
- **Flexible Storage**: Parquet (preferred), CSV, JSON
- **Data Accumulation**: Append-based storage with deduplication via primary keys
- **Incremental Fetching**: Only fetch new data since last run
- **Built-in Scheduler**: Automated periodic data fetching via APScheduler
- **Plugin Architecture**: Easily extensible with custom sources
- **Favorites Tracking**: Monitor entities across multiple sources
- **Web Integration**: Data displayed on [the-derple-dex](https://github.com/kenEldridge/the-derple-dex)

## Installation

```bash
# Clone and install in development mode
git clone <repo-url> cdata
cd cdata
pip install -e ".[dev]"
```

## Quick Start

```bash
# Initialize configuration
cdata config init

# List available sources
cdata sources list

# Fetch data from a source
cdata fetch source yfinance --symbols AAPL,GOOGL

# Run a scheduled job manually
cdata fetch run daily_stocks

# Start the scheduler daemon
cdata schedule start --daemon

# Query stored data
cdata data query "SELECT * FROM stocks WHERE symbol = 'AAPL' LIMIT 10"
```

## Configuration

### Environment Variables (.env)

```bash
# API Keys
ALPHAVANTAGE_API_KEY=your_key_here
NEWSAPI_KEY=your_key_here

# Paths (optional)
CDATA_CONFIG_DIR=./config
CDATA_DATA_DIR=./data
```

### Source Configuration (config/sources/*.yaml)

```yaml
sources:
  - id: my_stocks
    name: "Stock Watchlist"
    type: yfinance
    enabled: true
    config:
      symbols:
        - AAPL
        - GOOGL
        - MSFT
```

### Job Configuration (config/jobs/*.yaml)

```yaml
jobs:
  - id: daily_stocks
    source: my_stocks
    schedule:
      type: cron
      expression: "0 18 * * 1-5"  # 6 PM weekdays
    storage:
      backend: parquet
      path: data/raw/stocks
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `cdata fetch run <job>` | Run a fetch job |
| `cdata fetch source <id>` | Fetch from a specific source |
| `cdata schedule start` | Start scheduler daemon |
| `cdata schedule stop` | Stop scheduler |
| `cdata schedule status` | Show scheduler status |
| `cdata sources list` | List configured sources |
| `cdata sources test <id>` | Test source connectivity |
| `cdata jobs list` | List configured jobs |
| `cdata data list` | List stored datasets |
| `cdata data show <dataset>` | Preview dataset |
| `cdata data query "<sql>"` | Query data with SQL |
| `cdata favorites sync` | Fetch all favorites |
| `cdata config validate` | Validate configuration |

## Built-in Sources

### yfinance (Stocks)
```yaml
type: yfinance
config:
  symbols: [AAPL, GOOGL]
  period: "1mo"
  interval: "1d"
```

### RSS Feeds
```yaml
type: rss
config:
  feeds:
    - name: Hacker News
      url: https://news.ycombinator.com/rss
```

### SPARQL Endpoints
```yaml
type: sparql
config:
  endpoint: https://dbpedia.org/sparql
  query: |
    SELECT ?name WHERE { ... }
```

### Web Scraping
```yaml
type: scraping
config:
  url: https://example.com
  selectors:
    title: "h1.title"
    content: "div.content"
```

## Project Structure

```
cdata/
├── config/           # YAML configuration
│   ├── sources/      # Data source definitions
│   ├── jobs/         # Scheduled job definitions
│   └── favorites.yaml
├── data/             # Stored data
│   ├── raw/          # Raw fetched data (parquet)
│   ├── processed/    # Transformed data
│   ├── cache/        # HTTP cache
│   └── index.json    # Dataset metadata index
├── logs/             # Application logs
└── src/cdata/        # Source code
```

## Current Data Sources

Financial and economic data configured in `config/sources/financial.yaml`:

| Source | Type | Description |
|--------|------|-------------|
| `us_indices` | yfinance | S&P 500, Dow, NASDAQ, Russell 2000, VIX |
| `global_indices` | yfinance | FTSE, DAX, CAC, Nikkei, Hang Seng, Euro Stoxx |
| `treasury_yields` | yfinance | 13-week, 5yr, 10yr, 30yr Treasury yields |
| `bond_etfs` | yfinance | TLT, IEF, SHY, AGG, LQD, HYG, TIP, MUB |
| `currencies` | yfinance | Dollar Index, EUR, GBP, JPY, CNY |
| `commodities` | yfinance | Gold, Silver, WTI, Brent, Natural Gas, Copper |
| `sector_etfs` | yfinance | All 10 S&P 500 sector ETFs |
| `macro_proxies` | yfinance | SPY, QQQ, IWM, GLD, etc. |
| `fed_news` | rss | Federal Reserve press releases & speeches |
| `financial_news` | rss | Yahoo Finance, Seeking Alpha, CNBC |
| `economics_news` | rss | Calculated Risk, Marginal Revolution |

## Integration with the-derple-dex

Data from cdata is displayed on [the-derple-dex](https://github.com/kenEldridge/the-derple-dex) Astro site.

To update the site with fresh data:

```bash
# 1. Fetch latest data
cdata fetch source us_indices
cdata fetch source treasury_yields
# ... or fetch all sources

# 2. Run the prepare script in the-derple-dex
cd ../the-derple-dex
python3 scripts/prepare-data.py

# 3. Build/preview the site
npm run build
```

The `prepare-data.py` script reads parquet files from `../cdata/data/raw/` and converts them to JSON for the static site.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Type check
mypy src/
```

## License

MIT
