"""SEC EDGAR data source for company filings and financial data."""

import time
from datetime import datetime
from typing import Any, Optional

import requests

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class SECEDGARSource(BaseSource):
    """SEC EDGAR data source for company filings and XBRL financial data."""

    source_type = "sec_edgar"

    BASE_URL = "https://data.sec.gov"
    RATE_LIMIT_DELAY = 0.1  # 10 requests per second = 0.1 seconds between requests

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._session = None
        self._last_request_time = 0

    def _get_session(self) -> requests.Session:
        """Get or create HTTP session with proper User-Agent."""
        if self._session is None:
            self._session = requests.Session()
            # SEC requires a proper User-Agent header
            # Using a standard browser User-Agent to ensure compatibility
            user_agent = self.config.config.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            self._session.headers.update({
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov"
            })
        return self._session

    def _rate_limit(self):
        """Enforce rate limit of 10 requests per second."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _format_cik(self, cik: str | int) -> str:
        """Format CIK with leading zeros (10 digits)."""
        return str(cik).zfill(10)

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch data from SEC EDGAR.

        Args:
            mode: One of 'submissions', 'filings', or 'facts' (default: 'facts')
            ciks: List of CIK numbers (Central Index Key) - can be string or int
            filing_types: List of filing types to filter (e.g., ['10-K', '10-Q']) - only for filings mode
            facts: List of XBRL fact names (e.g., ['Assets', 'Deposits']) - only for facts mode
            since: Fetch data since this datetime (for incremental fetching)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        mode = kwargs.get("mode", "facts")
        ciks = kwargs.get("ciks", [])
        filing_types = kwargs.get("filing_types", [])
        facts_filter = kwargs.get("facts", [])
        since = kwargs.get("since")

        if isinstance(ciks, (str, int)):
            ciks = [ciks]

        if not ciks:
            return self._create_result(
                records, started_at, error="No CIKs provided"
            )

        try:
            session = self._get_session()
        except Exception as e:
            return self._create_result(
                records, started_at, error=f"Failed to initialize session: {e}"
            )

        for cik in ciks:
            try:
                formatted_cik = self._format_cik(cik)

                if mode == "submissions":
                    self._fetch_submissions(formatted_cik, session, records, errors)
                elif mode == "filings":
                    self._fetch_filings(
                        formatted_cik, session, records, errors,
                        filing_types, since
                    )
                elif mode == "facts":
                    self._fetch_facts(
                        formatted_cik, session, records, errors,
                        facts_filter, since
                    )
                else:
                    errors.append(f"Invalid mode: {mode}")

            except Exception as e:
                errors.append(f"Error fetching CIK {cik}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def _fetch_submissions(
        self,
        cik: str,
        session: requests.Session,
        records: list[Record],
        errors: list[str]
    ):
        """Fetch company submissions data."""
        self._rate_limit()
        url = f"{self.BASE_URL}/submissions/CIK{cik}.json"

        try:
            response = session.get(url)
            response.raise_for_status()
            data = response.json()

            record = self._create_record(
                data={
                    "cik": cik,
                    "name": data.get("name"),
                    "sic": data.get("sic"),
                    "sic_description": data.get("sicDescription"),
                    "entity_type": data.get("entityType"),
                    "tickers": data.get("tickers", []),
                    "exchanges": data.get("exchanges", []),
                    "ein": data.get("ein"),
                    "fiscal_year_end": data.get("fiscalYearEnd"),
                    "filings_count": len(data.get("filings", {}).get("recent", {}).get("accessionNumber", [])),
                },
                metadata={"source": "SEC EDGAR", "mode": "submissions"},
            )
            records.append(record)

        except Exception as e:
            errors.append(f"Error fetching submissions for CIK {cik}: {e}")

    def _fetch_filings(
        self,
        cik: str,
        session: requests.Session,
        records: list[Record],
        errors: list[str],
        filing_types: list[str],
        since: Optional[datetime]
    ):
        """Fetch company filings list."""
        self._rate_limit()
        url = f"{self.BASE_URL}/submissions/CIK{cik}.json"

        try:
            response = session.get(url)
            response.raise_for_status()
            data = response.json()

            filings = data.get("filings", {}).get("recent", {})
            if not filings:
                return

            # Get filing data arrays
            accession_numbers = filings.get("accessionNumber", [])
            filing_dates = filings.get("filingDate", [])
            forms = filings.get("form", [])
            primary_docs = filings.get("primaryDocument", [])

            for i in range(len(accession_numbers)):
                form = forms[i] if i < len(forms) else ""
                filing_date = filing_dates[i] if i < len(filing_dates) else ""

                # Filter by filing type if specified
                if filing_types and form not in filing_types:
                    continue

                # Filter by date if since is specified
                if since and filing_date:
                    filing_dt = datetime.strptime(filing_date, "%Y-%m-%d")
                    if filing_dt <= since:
                        continue

                record = self._create_record(
                    data={
                        "cik": cik,
                        "accession_number": accession_numbers[i],
                        "filing_date": filing_date,
                        "form": form,
                        "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                    },
                    metadata={"source": "SEC EDGAR", "mode": "filings"},
                )
                records.append(record)

        except Exception as e:
            errors.append(f"Error fetching filings for CIK {cik}: {e}")

    def _fetch_facts(
        self,
        cik: str,
        session: requests.Session,
        records: list[Record],
        errors: list[str],
        facts_filter: list[str],
        since: Optional[datetime]
    ):
        """Fetch XBRL company facts."""
        self._rate_limit()
        url = f"{self.BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"

        try:
            response = session.get(url)
            response.raise_for_status()
            data = response.json()

            cik_str = data.get("cik")
            entity_name = data.get("entityName", "")

            # Navigate through facts structure
            facts = data.get("facts", {})

            # Process US-GAAP facts (most common)
            us_gaap = facts.get("us-gaap", {})

            for fact_name, fact_data in us_gaap.items():
                # Filter by fact names if specified
                if facts_filter and fact_name not in facts_filter:
                    continue

                label = fact_data.get("label", fact_name)
                description = fact_data.get("description", "")

                # Process units (USD, shares, etc.)
                units = fact_data.get("units", {})

                for unit_type, values in units.items():
                    for value_entry in values:
                        filed_date = value_entry.get("filed")
                        end_date = value_entry.get("end")

                        # Filter by date if since is specified
                        if since and filed_date:
                            filed_dt = datetime.strptime(filed_date, "%Y-%m-%d")
                            if filed_dt <= since:
                                continue

                        record = self._create_record(
                            data={
                                "cik": cik_str,
                                "entity_name": entity_name,
                                "fact": fact_name,
                                "label": label,
                                "description": description,
                                "value": value_entry.get("val"),
                                "unit": unit_type,
                                "form": value_entry.get("form"),
                                "fiscal_year": value_entry.get("fy"),
                                "fiscal_period": value_entry.get("fp"),
                                "start_date": value_entry.get("start"),
                                "end_date": end_date,
                                "filed_date": filed_date,
                                "accession_number": value_entry.get("accn"),
                            },
                            metadata={"source": "SEC EDGAR", "mode": "facts"},
                        )
                        records.append(record)

        except Exception as e:
            errors.append(f"Error fetching facts for CIK {cik}: {e}")

    def test_connection(self) -> bool:
        """Test connection by fetching Apple's (CIK 320193) submissions."""
        try:
            session = self._get_session()
            self._rate_limit()
            response = session.get(f"{self.BASE_URL}/submissions/CIK0000320193.json")
            response.raise_for_status()
            data = response.json()
            return "name" in data and "cik" in data
        except Exception:
            return False
