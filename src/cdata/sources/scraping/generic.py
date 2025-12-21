"""Generic web scraping source using BeautifulSoup."""

from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from cdata.config import get_settings
from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class ScrapingSource(BaseSource):
    """Generic web scraping data source."""

    source_type = "scraping"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self.settings = get_settings()

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Scrape data from a web page.

        Args:
            url: URL to scrape
            selectors: Dict mapping field names to CSS selectors
            multiple: If True, find all matches; if False, find first match only
            attrs: Dict mapping field names to attribute names to extract (default: text)
        """
        started_at = datetime.utcnow()

        url = kwargs.get("url")
        selectors = kwargs.get("selectors", {})
        multiple = kwargs.get("multiple", False)
        attrs = kwargs.get("attrs", {})

        if not url:
            return self._create_result([], started_at, error="No URL specified")

        if not selectors:
            return self._create_result([], started_at, error="No selectors specified")

        try:
            with httpx.Client(timeout=self.settings.http_timeout) as client:
                response = client.get(url)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            records: list[Record] = []

            if multiple:
                first_selector = list(selectors.values())[0]
                elements = soup.select(first_selector)

                for i, _ in enumerate(elements):
                    row_data = {"url": url}
                    for field, selector in selectors.items():
                        all_matches = soup.select(selector)
                        if i < len(all_matches):
                            elem = all_matches[i]
                            attr = attrs.get(field)
                            if attr:
                                row_data[field] = elem.get(attr, "")
                            else:
                                row_data[field] = elem.get_text(strip=True)
                        else:
                            row_data[field] = None

                    record = self._create_record(data=row_data)
                    records.append(record)
            else:
                row_data = {"url": url}
                for field, selector in selectors.items():
                    elem = soup.select_one(selector)
                    if elem:
                        attr = attrs.get(field)
                        if attr:
                            row_data[field] = elem.get(attr, "")
                        else:
                            row_data[field] = elem.get_text(strip=True)
                    else:
                        row_data[field] = None

                record = self._create_record(data=row_data)
                records.append(record)

            return self._create_result(records, started_at)

        except httpx.HTTPError as e:
            return self._create_result([], started_at, error=f"HTTP error: {e}")
        except Exception as e:
            return self._create_result([], started_at, error=str(e))

    def test_connection(self) -> bool:
        """Test connection by fetching example.com."""
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get("https://example.com")
                return response.status_code == 200
        except Exception:
            return False
