"""Bureau of Labor Statistics (BLS) data source."""

import os
from datetime import datetime
from typing import Any

import requests

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


# BLS series metadata (series_id -> (title, units, frequency))
BLS_SERIES_INFO = {
    # CPI
    "CUSR0000SA0": ("CPI All Items (Seasonally Adjusted)", "Index 1982-84=100", "Monthly"),
    "CUSR0000SA0L1E": ("CPI All Items Less Food and Energy", "Index 1982-84=100", "Monthly"),
    "CUUR0000SA0": ("CPI All Items (Not Seasonally Adjusted)", "Index 1982-84=100", "Monthly"),
    # Employment
    "LNS14000000": ("Unemployment Rate", "Percent", "Monthly"),
    "LNS11000000": ("Labor Force Participation Rate", "Percent", "Monthly"),
    "CES0000000001": ("Total Nonfarm Employment", "Thousands", "Monthly"),
    "CES0500000001": ("Total Private Employment", "Thousands", "Monthly"),
    # Wages
    "CES0500000003": ("Average Hourly Earnings (Private)", "Dollars", "Monthly"),
    "CES0500000011": ("Average Weekly Earnings (Private)", "Dollars", "Monthly"),
    # PPI
    "WPUFD4": ("PPI Finished Goods", "Index 1982=100", "Monthly"),
    "WPSFD4": ("PPI Finished Goods (Seasonally Adjusted)", "Index 1982=100", "Monthly"),
    "WPUFD49104": ("PPI Finished Core Goods", "Index 1982=100", "Monthly"),
    # Productivity
    "PRS85006092": ("Nonfarm Business Labor Productivity", "Index 2017=100", "Quarterly"),
    "PRS85006112": ("Nonfarm Business Unit Labor Costs", "Index 2017=100", "Quarterly"),
    # JOLTS
    "JTS000000000000000JOL": ("Job Openings Total Nonfarm", "Thousands", "Monthly"),
    "JTS000000000000000HIR": ("Hires Total Nonfarm", "Thousands", "Monthly"),
    "JTS000000000000000QUL": ("Quits Total Nonfarm", "Thousands", "Monthly"),
    "JTS000000000000000TSL": ("Total Separations Nonfarm", "Thousands", "Monthly"),
}


class BLSSource(BaseSource):
    """BLS data source for labor statistics."""

    source_type = "bls"

    # API endpoints
    V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    # API limits
    V1_MAX_YEARS = 10
    V1_MAX_SERIES = 25
    V2_MAX_YEARS = 20
    V2_MAX_SERIES = 50

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._api_key = os.environ.get("BLS_API_KEY")

    def _get_api_url(self) -> str:
        """Get appropriate API URL based on key availability."""
        return self.V2_URL if self._api_key else self.V1_URL

    def _get_max_years(self) -> int:
        """Get max years based on API version."""
        return self.V2_MAX_YEARS if self._api_key else self.V1_MAX_YEARS

    def _fetch_series_batch(
        self,
        series_ids: list[str],
        start_year: int,
        end_year: int
    ) -> dict[str, Any]:
        """Fetch a batch of series from BLS API."""
        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }

        if self._api_key:
            payload["registrationkey"] = self._api_key

        headers = {"Content-Type": "application/json"}

        response = requests.post(
            self._get_api_url(),
            json=payload,
            headers=headers,
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch labor statistics from BLS.

        Args:
            series: List of BLS series IDs
            start_year: Start year (default: 10/20 years ago based on API version)
            end_year: End year (default: current year)
            since: Fetch data since this datetime (for incremental fetching)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        series_ids = kwargs.get("series", [])
        if isinstance(series_ids, str):
            series_ids = [s.strip() for s in series_ids.split(",")]

        current_year = datetime.now().year
        max_years = self._get_max_years()

        start_year = kwargs.get("start_year", current_year - max_years + 1)
        end_year = kwargs.get("end_year", current_year)
        since = kwargs.get("since")

        # Adjust start year for incremental fetch
        if since:
            start_year = max(start_year, since.year)

        # Clamp to max years allowed
        if end_year - start_year >= max_years:
            start_year = end_year - max_years + 1

        # Batch series (v1: 25 max, v2: 50 max)
        max_series = self.V2_MAX_SERIES if self._api_key else self.V1_MAX_SERIES

        for i in range(0, len(series_ids), max_series):
            batch = series_ids[i:i + max_series]

            try:
                result = self._fetch_series_batch(batch, start_year, end_year)

                if result.get("status") != "REQUEST_SUCCEEDED":
                    errors.append(f"BLS API error: {result.get('message', 'Unknown error')}")
                    continue

                for series_data in result.get("Results", {}).get("series", []):
                    series_id = series_data.get("seriesID", "")

                    # Get series metadata
                    info = BLS_SERIES_INFO.get(series_id, (series_id, "", ""))
                    title, units, frequency = info

                    for item in series_data.get("data", []):
                        year = item.get("year")
                        period = item.get("period", "")
                        value_str = item.get("value", "")

                        # Skip annual averages (M13) unless that's what we want
                        if period == "M13":
                            continue

                        # Parse period to date
                        try:
                            if period.startswith("M"):
                                month = int(period[1:])
                                date = f"{year}-{month:02d}-01"
                            elif period.startswith("Q"):
                                quarter = int(period[1:])
                                month = (quarter - 1) * 3 + 1
                                date = f"{year}-{month:02d}-01"
                            else:
                                date = f"{year}-01-01"
                        except ValueError:
                            continue

                        # Parse value
                        try:
                            value = float(value_str)
                        except (ValueError, TypeError):
                            continue

                        # Filter by since date for incremental
                        if since:
                            record_date = datetime.strptime(date, "%Y-%m-%d")
                            if record_date <= since:
                                continue

                        record = self._create_record(
                            data={
                                "series_id": series_id,
                                "date": date,
                                "value": value,
                                "title": title,
                                "units": units,
                                "frequency": frequency,
                                "period": period,
                                "year": year,
                            },
                            metadata={"source": "BLS"},
                        )
                        records.append(record)

            except requests.RequestException as e:
                errors.append(f"Request error for batch {i//max_series + 1}: {e}")
            except Exception as e:
                errors.append(f"Error processing batch {i//max_series + 1}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by fetching unemployment rate."""
        try:
            current_year = datetime.now().year
            result = self._fetch_series_batch(
                ["LNS14000000"],
                current_year - 1,
                current_year
            )
            return result.get("status") == "REQUEST_SUCCEEDED"
        except Exception:
            return False
