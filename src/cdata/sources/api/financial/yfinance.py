"""Yahoo Finance data source using yfinance."""

from datetime import datetime
from typing import Any

import yfinance as yf

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class YFinanceSource(BaseSource):
    """Yahoo Finance data source."""

    source_type = "yfinance"

    def __init__(self, config: SourceConfig):
        super().__init__(config)

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch stock data from Yahoo Finance.

        Args:
            symbols: List of stock symbols
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
            since: Fetch data since this datetime (for incremental fetching)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        symbols = kwargs.get("symbols", [])
        period = kwargs.get("period", "1mo")
        interval = kwargs.get("interval", "1d")
        since = kwargs.get("since")  # datetime for incremental fetching

        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",")]

        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)

                # Use start date if provided (incremental), otherwise use period
                if since:
                    # Add 1 day to avoid refetching the last date
                    from datetime import timedelta
                    start_date = since + timedelta(days=1)
                    hist = ticker.history(start=start_date.strftime("%Y-%m-%d"), interval=interval)
                else:
                    hist = ticker.history(period=period, interval=interval)

                if hist.empty:
                    if not since:  # Only report as error if not incremental
                        errors.append(f"No data for {symbol}")
                    continue

                for idx, row in hist.iterrows():
                    record = self._create_record(
                        data={
                            "symbol": symbol,
                            "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "volume": int(row["Volume"]),
                        },
                        metadata={"period": period, "interval": interval},
                    )
                    records.append(record)

            except Exception as e:
                errors.append(f"Error fetching {symbol}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by fetching AAPL."""
        try:
            ticker = yf.Ticker("AAPL")
            info = ticker.info
            return "symbol" in info or "shortName" in info
        except Exception:
            return False

    def get_info(self, symbol: str) -> dict[str, Any]:
        """Get detailed info for a symbol."""
        ticker = yf.Ticker(symbol)
        return ticker.info
