"""Federal Reserve Economic Data (FRED) source."""

import os
from datetime import datetime
from typing import Any, Optional

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class FREDSource(BaseSource):
    """FRED data source for economic indicators."""

    source_type = "fred"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._fred = None

    def _get_client(self):
        """Lazy load FRED client."""
        if self._fred is None:
            from fredapi import Fred
            api_key = os.environ.get("FRED_API_KEY")
            if not api_key:
                raise ValueError("FRED_API_KEY environment variable not set")
            self._fred = Fred(api_key=api_key)
        return self._fred

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch economic data from FRED.

        Args:
            series: List of FRED series IDs (e.g., ['GDP', 'UNRATE', 'CPIAUCSL'])
            start_date: Start date (YYYY-MM-DD) - optional
            end_date: End date (YYYY-MM-DD) - optional
            since: Fetch data since this datetime (for incremental fetching)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        series_ids = kwargs.get("series", [])
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        since = kwargs.get("since")

        if isinstance(series_ids, str):
            series_ids = [s.strip() for s in series_ids.split(",")]

        # Use since date for incremental fetching
        if since:
            from datetime import timedelta
            start_date = (since + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            fred = self._get_client()
        except Exception as e:
            return self._create_result(
                records, started_at, error=f"Failed to initialize FRED client: {e}"
            )

        for series_id in series_ids:
            try:
                # Fetch series data
                data = fred.get_series(
                    series_id,
                    observation_start=start_date,
                    observation_end=end_date,
                )

                if data.empty:
                    if not since:
                        errors.append(f"No data for {series_id}")
                    continue

                # Get series metadata
                try:
                    info = fred.get_series_info(series_id)
                    title = info.get("title", series_id)
                    units = info.get("units", "")
                    frequency = info.get("frequency", "")
                except Exception:
                    title = series_id
                    units = ""
                    frequency = ""

                for date, value in data.items():
                    # Skip NaN values
                    if value != value:  # NaN check
                        continue

                    record = self._create_record(
                        data={
                            "series_id": series_id,
                            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
                            "value": float(value),
                            "title": title,
                            "units": units,
                            "frequency": frequency,
                        },
                        metadata={"source": "FRED"},
                    )
                    records.append(record)

            except Exception as e:
                errors.append(f"Error fetching {series_id}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by fetching GDP series info."""
        try:
            fred = self._get_client()
            info = fred.get_series_info("GDP")
            return "title" in info
        except Exception:
            return False

    def search_series(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for FRED series by keyword."""
        try:
            fred = self._get_client()
            results = fred.search(query, limit=limit)
            return results.to_dict("records") if not results.empty else []
        except Exception:
            return []

    def get_series_info(self, series_id: str) -> dict[str, Any]:
        """Get metadata for a specific series."""
        fred = self._get_client()
        return fred.get_series_info(series_id).to_dict()
