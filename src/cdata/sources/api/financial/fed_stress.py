"""Federal Reserve Stress Test Scenarios data source.

Downloads DFAST/CCAR supervisory stress test scenario data (baseline,
severely adverse, and historic) from the Federal Reserve Board website.
Data is published annually as CSV files — no API key required.

Source: https://www.federalreserve.gov/supervisionreg/stress-tests.htm
"""

import csv
import io
from datetime import datetime
from typing import Any

import httpx

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource

BASE_URL = "https://www.federalreserve.gov/supervisionreg/files"

# Table definitions: (table_id, scenario_name, region)
TABLES = {
    "historic_domestic": ("1A", "Historic", "Domestic"),
    "historic_international": ("1B", "Historic", "International"),
    "baseline_domestic": ("2A", "Supervisory_Baseline", "Domestic"),
    "baseline_international": ("2B", "Supervisory_Baseline", "International"),
    "severely_adverse_domestic": ("3A", "Supervisory_Severely_Adverse", "Domestic"),
    "severely_adverse_international": ("3B", "Supervisory_Severely_Adverse", "International"),
}

# Domestic columns (Table 1A/2A/3A)
DOMESTIC_COLUMNS = [
    "scenario_name",
    "date",
    "real_gdp_growth",
    "nominal_gdp_growth",
    "real_disposable_income_growth",
    "nominal_disposable_income_growth",
    "unemployment_rate",
    "cpi_inflation_rate",
    "3_month_treasury_rate",
    "5_year_treasury_yield",
    "10_year_treasury_yield",
    "bbb_corporate_yield",
    "mortgage_rate",
    "prime_rate",
    "dow_jones_total_stock_market_index",
    "house_price_index",
    "commercial_real_estate_price_index",
    "market_volatility_index",
]

# International columns (Table 1B/2B/3B)
INTERNATIONAL_COLUMNS = [
    "scenario_name",
    "date",
    "euro_area_real_gdp_growth",
    "euro_area_inflation",
    "euro_area_bilateral_dollar_exchange_rate",
    "developing_asia_real_gdp_growth",
    "developing_asia_inflation",
    "developing_asia_bilateral_dollar_exchange_rate",
    "japan_real_gdp_growth",
    "japan_inflation",
    "japan_bilateral_dollar_exchange_rate",
    "uk_real_gdp_growth",
    "uk_inflation",
    "uk_bilateral_dollar_exchange_rate",
]


def _build_csv_url(year: int, table_key: str) -> str:
    """Build the download URL for a scenario CSV file."""
    table_id, scenario, region = TABLES[table_key]
    return f"{BASE_URL}/{year}-Table_{table_id}_{scenario}_{region}.csv"


def _parse_value(val: str) -> float | str:
    """Parse a CSV cell value to float if possible."""
    val = val.strip()
    if not val:
        return val
    try:
        return float(val.replace(",", ""))
    except ValueError:
        return val


class FedStressSource(BaseSource):
    """Federal Reserve stress test scenario data source.

    Downloads the supervisory scenario CSVs published annually by the
    Federal Reserve Board for the Dodd-Frank Act Stress Tests.

    Config params:
        years: List of years to fetch (e.g. [2024, 2025])
        scenarios: List of scenario keys to fetch. Defaults to all.
            Options: historic_domestic, historic_international,
                     baseline_domestic, baseline_international,
                     severely_adverse_domestic, severely_adverse_international
    """

    source_type = "fed_stress"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "cdata/0.1.0"},
        )

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch stress test scenario data.

        Args:
            years: List of years (e.g. [2024, 2025]).
            scenarios: List of scenario table keys to fetch.
                       Defaults to all six tables.
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        years = kwargs.get("years", [datetime.now().year])
        if isinstance(years, int):
            years = [years]

        scenarios = kwargs.get("scenarios", list(TABLES.keys()))
        if isinstance(scenarios, str):
            scenarios = [s.strip() for s in scenarios.split(",")]

        for year in years:
            for scenario_key in scenarios:
                if scenario_key not in TABLES:
                    errors.append(f"Unknown scenario: {scenario_key}")
                    continue

                url = _build_csv_url(year, scenario_key)
                is_international = scenario_key.endswith("_international")
                columns = INTERNATIONAL_COLUMNS if is_international else DOMESTIC_COLUMNS

                try:
                    response = self._client.get(url)
                    response.raise_for_status()

                    reader = csv.reader(io.StringIO(response.text))

                    # Skip header row
                    next(reader, None)

                    for row in reader:
                        if not row or not any(cell.strip() for cell in row):
                            continue

                        # Map columns to values
                        data: dict[str, Any] = {
                            "year": year,
                            "table": scenario_key,
                            "region": "international" if is_international else "domestic",
                        }

                        for i, col_name in enumerate(columns):
                            if i < len(row):
                                data[col_name] = _parse_value(row[i])

                        record = self._create_record(
                            data=data,
                            metadata={"source": "FederalReserve", "url": url},
                        )
                        records.append(record)

                except httpx.HTTPStatusError as e:
                    errors.append(f"{year} {scenario_key}: HTTP {e.response.status_code}")
                except Exception as e:
                    errors.append(f"{year} {scenario_key}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by fetching the 2025 baseline domestic CSV."""
        try:
            url = _build_csv_url(2025, "baseline_domestic")
            response = self._client.get(url)
            return response.status_code == 200
        except Exception:
            return False
