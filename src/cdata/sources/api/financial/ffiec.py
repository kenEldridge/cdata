"""FFIEC Call Report bulk data source.

Downloads quarterly bank call report data from the FFIEC Central Data
Repository (cdr.ffiec.gov) using the ffiec-data-collector library.
No authentication required — data is publicly available.

Source: https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx
"""

import csv
import io
import zipfile
from datetime import datetime
from typing import Any

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource

# Map config product names to library Product enum member names
PRODUCT_MAP = {
    "call_single": "CALL_SINGLE",
    "call_four_periods": "CALL_FOUR_PERIODS",
    "ubpr_ratio_single": "UBPR_RATIO_SINGLE",
    "ubpr_ratio_four": "UBPR_RATIO_FOUR",
    "ubpr_rank_four": "UBPR_RANK_FOUR",
    "ubpr_stats_four": "UBPR_STATS_FOUR",
}


class FFIECSource(BaseSource):
    """FFIEC Call Report bulk data source.

    Downloads quarterly bank call report data from the FFIEC Central Data
    Repository using the ``ffiec-data-collector`` library, which handles
    the ASP.NET form scraping on ``cdr.ffiec.gov``.

    Config params:
        products: List of report types to download.
            Options: call_single, call_four_periods, ubpr_ratio_single,
                     ubpr_ratio_four, ubpr_rank_four, ubpr_stats_four
            Default: ["call_single"]
        reporting_period: Quarter-end date as YYYYMMDD (e.g. "20240331").
            If omitted, the latest available period is downloaded.
    """

    source_type = "ffiec"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._downloader = None

    def _get_downloader(self):
        """Lazy-load the FFIEC downloader."""
        if self._downloader is None:
            from ffiec_data_collector import FFIECDownloader

            self._downloader = FFIECDownloader()
        return self._downloader

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch call report bulk data from FFIEC CDR.

        Args:
            products: List of product keys (see PRODUCT_MAP).
            reporting_period: Quarter-end date as YYYYMMDD string.
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        products = kwargs.get("products", ["call_single"])
        if isinstance(products, str):
            products = [p.strip() for p in products.split(",")]

        reporting_period = kwargs.get("reporting_period")

        try:
            from ffiec_data_collector import FileFormat, Product

            downloader = self._get_downloader()
        except Exception as e:
            return self._create_result(
                records, started_at, error=f"Failed to initialize FFIEC downloader: {e}"
            )

        for product_key in products:
            enum_name = PRODUCT_MAP.get(product_key)
            if not enum_name:
                errors.append(f"Unknown product: {product_key}")
                continue

            product = Product[enum_name]

            try:
                if reporting_period:
                    period = reporting_period
                else:
                    period = downloader.get_latest_period(product)

                result = downloader.download(
                    product=product,
                    period=period,
                    format=FileFormat.TSV,
                    save_to_disk=False,
                )

                content = self._extract_content(result)
                if content is None:
                    errors.append(f"No data returned for {product_key}")
                    continue

                period_str = (
                    period if isinstance(period, str)
                    else getattr(period, "yyyymmdd", str(period))
                )
                parsed = self._parse_zip_tsv(content, product_key, period_str)
                records.extend(parsed)

            except Exception as e:
                errors.append(f"Error fetching {product_key}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    @staticmethod
    def _extract_content(result: Any) -> io.BytesIO | None:
        """Normalise the download result into a BytesIO.

        The library may return a BytesIO directly, raw bytes, or a
        DownloadResult wrapper — handle all cases.
        """
        if isinstance(result, io.BytesIO):
            result.seek(0)
            return result
        if isinstance(result, bytes):
            return io.BytesIO(result)
        # DownloadResult or similar wrapper
        for attr in ("content", "data", "file"):
            payload = getattr(result, attr, None)
            if payload is not None:
                if isinstance(payload, io.BytesIO):
                    payload.seek(0)
                    return payload
                if isinstance(payload, bytes):
                    return io.BytesIO(payload)
        return None

    def _parse_zip_tsv(
        self, content: io.BytesIO, product: str, period: str | None
    ) -> list[Record]:
        """Parse a ZIP archive of TSV schedule files into records."""
        records: list[Record] = []

        with zipfile.ZipFile(content) as zf:
            for name in zf.namelist():
                lower = name.lower()
                if not (lower.endswith(".txt") or lower.endswith(".tsv")):
                    continue

                schedule = name.rsplit(".", 1)[0]

                with zf.open(name) as f:
                    text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                    reader = csv.DictReader(text, delimiter="\t")

                    for row in reader:
                        data: dict[str, Any] = {
                            "product": product,
                            "schedule": schedule,
                        }
                        if period:
                            data["reporting_period"] = period

                        data.update(
                            {k: _coerce(v) for k, v in row.items() if k}
                        )

                        records.append(
                            self._create_record(
                                data=data,
                                metadata={"source": "FFIEC_CDR"},
                            )
                        )

        return records

    def test_connection(self) -> bool:
        """Test connectivity to the FFIEC CDR website."""
        try:
            downloader = self._get_downloader()
            sources = downloader.get_bulk_data_sources_cdr()
            return bool(sources)
        except Exception:
            return False


def _coerce(val: str) -> int | float | str | None:
    """Coerce a TSV cell value to the narrowest numeric type possible."""
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        return val
