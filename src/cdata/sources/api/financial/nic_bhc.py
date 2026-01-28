"""NIC Bank Holding Company (FR Y-9C) data source."""

import csv
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class NICBHCSource(BaseSource):
    """NIC Bank Holding Company (FR Y-9C) data source.

    FR Y-9C provides consolidated financial statements for Bank Holding Companies
    including balance sheet, income, off-balance-sheet commitments, and capital ratios.

    Note: The NIC website has Cloudflare bot protection, so direct downloading may not work.
    For best results, manually download ZIP files from:
    https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload
    and specify the local_file path in config.
    """

    source_type = "nic_bhc"

    BASE_URL = "https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._session = None

    def _get_session(self) -> requests.Session:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            })
        return self._session

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch FR Y-9C data.

        Args:
            local_file: Path to locally downloaded ZIP file (recommended)
            quarter: Quarter to fetch in YYYYMMDD format (e.g., '20231231')
            report_type: Type of report (e.g., 'BHCF', 'BHCK', 'BHCD') - default: all
            rssd_ids: List of RSSD IDs (bank identifiers) to filter - default: all
            schedules: List of schedule names to include (e.g., ['HC', 'HI']) - default: all
            since: Fetch data since this datetime (for incremental fetching)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        local_file = kwargs.get("local_file")
        quarter = kwargs.get("quarter")
        report_type = kwargs.get("report_type", "")
        rssd_ids = kwargs.get("rssd_ids", [])
        schedules = kwargs.get("schedules", [])
        since = kwargs.get("since")

        if not local_file and not quarter:
            return self._create_result(
                records,
                started_at,
                error="Either 'local_file' or 'quarter' must be provided"
            )

        try:
            if local_file:
                zip_path = Path(local_file)
                if not zip_path.exists():
                    return self._create_result(
                        records,
                        started_at,
                        error=f"File not found: {local_file}"
                    )
            else:
                # Attempt to download (may fail due to Cloudflare)
                errors.append(
                    "Direct download not implemented - Cloudflare protection. "
                    "Please download manually and use 'local_file' parameter."
                )
                return self._create_result(records, started_at, error="; ".join(errors))

            # Process the ZIP file
            self._process_zip_file(
                zip_path, records, errors,
                report_type, rssd_ids, schedules, since
            )

        except Exception as e:
            errors.append(f"Error processing FR Y-9C data: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def _process_zip_file(
        self,
        zip_path: Path,
        records: list[Record],
        errors: list[str],
        report_type: str,
        rssd_ids: list[str | int],
        schedules: list[str],
        since: Optional[datetime]
    ):
        """Process FR Y-9C ZIP file containing caret-delimited text files."""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                # List all files in ZIP
                file_list = zip_file.namelist()

                # Filter by report type if specified
                if report_type:
                    file_list = [f for f in file_list if report_type.upper() in f.upper()]

                # Filter by schedules if specified
                if schedules:
                    schedule_patterns = [f"_{s.upper()}" for s in schedules]
                    file_list = [
                        f for f in file_list
                        if any(pat in f.upper() for pat in schedule_patterns)
                    ]

                for filename in file_list:
                    if not filename.endswith('.txt'):
                        continue

                    try:
                        with zip_file.open(filename) as txt_file:
                            # FR Y-9C files are caret-delimited (^)
                            content = txt_file.read().decode('utf-8', errors='replace')
                            reader = csv.DictReader(
                                content.splitlines(),
                                delimiter='^'
                            )

                            for row in reader:
                                # Extract key fields (standard FR Y-9C structure)
                                rssd_id = row.get('RSSD9001', row.get('IDRSSD', ''))
                                report_date = row.get('RSSD9999', row.get('REPORT_DATE', ''))

                                # Filter by RSSD IDs if specified
                                if rssd_ids and rssd_id not in [str(id) for id in rssd_ids]:
                                    continue

                                # Filter by date if since is specified
                                if since and report_date:
                                    try:
                                        report_dt = datetime.strptime(report_date, "%Y%m%d")
                                        if report_dt <= since:
                                            continue
                                    except ValueError:
                                        pass

                                # Create record with all fields
                                record_data = {
                                    "rssd_id": rssd_id,
                                    "report_date": report_date,
                                    "schedule": filename,
                                }

                                # Add all other fields
                                for key, value in row.items():
                                    if key not in record_data:
                                        # Try to convert numeric values
                                        try:
                                            if value and value.strip():
                                                record_data[key] = float(value)
                                        except (ValueError, AttributeError):
                                            record_data[key] = value

                                record = self._create_record(
                                    data=record_data,
                                    metadata={
                                        "source": "NIC BHC",
                                        "file": filename,
                                        "report_type": report_type or "ALL"
                                    }
                                )
                                records.append(record)

                    except Exception as e:
                        errors.append(f"Error processing file {filename}: {e}")

        except Exception as e:
            errors.append(f"Error opening ZIP file: {e}")

    def test_connection(self) -> bool:
        """Test connection - just checks if we can create a session.

        Note: Cannot test actual download due to Cloudflare protection.
        """
        try:
            session = self._get_session()
            return session is not None
        except Exception:
            return False

    def get_available_quarters(self) -> list[str]:
        """Get list of available quarters.

        Note: Not implemented due to Cloudflare protection.
        Users should check the website manually for available quarters.
        """
        return [
            "Check https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload",
            "for available quarters"
        ]
