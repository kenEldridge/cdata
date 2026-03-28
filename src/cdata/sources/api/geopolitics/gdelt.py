"""GDELT (Global Database of Events, Language, and Tone) conflict event source.

Downloads GDELT 2.0 event CSV files filtered to conflict events (QuadClass 3+4)
for configured countries. No API key required — GDELT is fully open.

GDELT v2 publishes event files every 15 minutes as:
  http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHmmSS.export.CSV.zip

Data format: http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource

# GDELT 2.0 URLs
GDELT_LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_MASTERFILE_URL = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
GDELT_V2_BASE = "http://data.gdeltproject.org/gdeltv2/"

# GDELT 2.0 event CSV column names (61 fields, tab-delimited)
EVENT_COLUMNS = [
    "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
    "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
    "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
    "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
    "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode",
    "QuadClass", "GoldsteinScale", "NumMentions", "NumSources", "NumArticles",
    "AvgTone",
    "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code",
    "Actor1Geo_Lat", "Actor1Geo_Long", "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code",
    "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code", "ActionGeo_ADM2Code",
    "ActionGeo_Lat", "ActionGeo_Long", "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL",
]

# Fields we keep in each record
KEEP_FIELDS = [
    "GLOBALEVENTID", "SQLDATE", "Year",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1Type1Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2Type1Code",
    "EventCode", "EventBaseCode", "EventRootCode",
    "QuadClass", "GoldsteinScale", "NumMentions", "NumSources", "AvgTone",
    "ActionGeo_FullName", "ActionGeo_CountryCode",
    "ActionGeo_Lat", "ActionGeo_Long",
    "DATEADDED", "SOURCEURL",
]

# FIPS 10-4 country codes used by GDELT (NOT ISO)
COUNTRY_FIPS = {
    "ukraine": "UP",
    "russia": "RS",
    "israel": "IS",
    "palestine": "GZ",  # Gaza Strip; West Bank = WE
    "iran": "IR",
    "syria": "SY",
    "china": "CH",
    "taiwan": "TW",
    "north korea": "KN",
    "south korea": "KS",
    "yemen": "YM",
    "lebanon": "LE",
    "iraq": "IZ",
    "afghanistan": "AF",
    "libya": "LY",
    "sudan": "SU",
    "myanmar": "BM",
    "ethiopia": "ET",
    "somalia": "SO",
    "pakistan": "PK",
    "india": "IN",
    "united states": "US",
    "turkey": "TU",
    "saudi arabia": "SA",
    "egypt": "EG",
    "japan": "JA",
    "philippines": "RP",
}


def _generate_file_urls(lookback_days: int) -> list[str]:
    """Generate GDELT v2 15-min export file URLs for the lookback period.

    Rather than downloading the huge master file list, we generate URLs directly
    from timestamps. GDELT publishes at :00, :15, :30, :45 of every hour.
    """
    urls = []
    now = datetime.utcnow().replace(second=0, microsecond=0)
    # Round down to nearest 15 min
    now = now.replace(minute=(now.minute // 15) * 15)
    cutoff = now - timedelta(days=lookback_days)

    t = now
    while t >= cutoff:
        ts = t.strftime("%Y%m%d%H%M%S")
        urls.append(f"{GDELT_V2_BASE}{ts}.export.CSV.zip")
        t -= timedelta(minutes=15)

    return urls


class GDELTSource(BaseSource):
    """GDELT conflict event data source.

    Downloads GDELT 2.0 event CSV files (published every 15 min) and filters to
    conflict events (QuadClass 3 = Verbal Conflict, 4 = Material Conflict)
    involving configured countries of interest.

    Config keys:
        countries: list of country names to filter (matched against actor + action geo)
        lookback_days: how many days of data to fetch (default 1)
        quad_classes: list of QuadClass values to include (default [3, 4])
        min_mentions: minimum NumMentions to include (default 1, filters noise)
    """

    source_type = "gdelt"

    def __init__(self, config: SourceConfig):
        super().__init__(config)

    def _resolve_fips_codes(self, countries: list[str]) -> set[str]:
        """Convert country names to FIPS codes for matching."""
        codes = set()
        for c in countries:
            fips = COUNTRY_FIPS.get(c.lower())
            if fips:
                codes.add(fips)
                # Palestine has two FIPS codes
                if c.lower() == "palestine":
                    codes.add("WE")
        return codes

    def _matches_country(self, row: dict[str, str], fips_codes: set[str]) -> bool:
        """Check if an event involves any of the target countries."""
        for field in ("Actor1CountryCode", "Actor2CountryCode", "ActionGeo_CountryCode"):
            if row.get(field, "") in fips_codes:
                return True
        return False

    def _parse_row(self, row: dict[str, str]) -> dict[str, Any]:
        """Extract and coerce fields from a raw CSV row."""
        data: dict[str, Any] = {}
        for field in KEEP_FIELDS:
            data[field] = row.get(field, "")

        for field in ("QuadClass", "NumMentions", "NumSources", "Year"):
            if data[field]:
                try:
                    data[field] = int(data[field])
                except (ValueError, TypeError):
                    pass

        for field in ("GoldsteinScale", "AvgTone", "ActionGeo_Lat", "ActionGeo_Long"):
            if data[field]:
                try:
                    data[field] = float(data[field])
                except (ValueError, TypeError):
                    pass

        return data

    def _parse_zip(
        self,
        content: bytes,
        fips_codes: set[str],
        quad_classes: set[int],
        min_mentions: int,
    ) -> list[Record]:
        """Parse a GDELT export ZIP file and return filtered records."""
        records: list[Record] = []

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                reader = csv.DictReader(text, fieldnames=EVENT_COLUMNS, delimiter="\t")

                for row in reader:
                    try:
                        qc = int(row.get("QuadClass", "0"))
                    except ValueError:
                        continue
                    if qc not in quad_classes:
                        continue

                    if fips_codes and not self._matches_country(row, fips_codes):
                        continue

                    try:
                        mentions = int(row.get("NumMentions", "0"))
                    except ValueError:
                        mentions = 0
                    if mentions < min_mentions:
                        continue

                    data = self._parse_row(row)
                    records.append(self._create_record(
                        data=data,
                        metadata={"source": "GDELT"},
                    ))

        return records

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch conflict events from GDELT 15-minute export files."""
        started_at = datetime.utcnow()
        all_records: list[Record] = []
        errors: list[str] = []

        countries = kwargs.get("countries", [])
        lookback_days = int(kwargs.get("lookback_days", 1))
        quad_classes = set(kwargs.get("quad_classes", [3, 4]))
        min_mentions = int(kwargs.get("min_mentions", 1))

        fips_codes = self._resolve_fips_codes(countries)
        if countries and not fips_codes:
            errors.append(
                f"No FIPS codes found for countries: {countries}. "
                f"Supported: {', '.join(sorted(COUNTRY_FIPS.keys()))}"
            )
            return self._create_result(all_records, started_at, error="; ".join(errors))

        urls = _generate_file_urls(lookback_days)
        downloaded = 0
        skipped = 0

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    if resp.status_code == 404:
                        skipped += 1
                        continue
                    resp.raise_for_status()
                except Exception as e:
                    skipped += 1
                    continue  # Skip individual file failures silently

                try:
                    records = self._parse_zip(
                        resp.content, fips_codes, quad_classes, min_mentions,
                    )
                    all_records.extend(records)
                    downloaded += 1
                except Exception as e:
                    errors.append(f"Parse error: {e}")

        if downloaded == 0 and skipped == len(urls):
            errors.append("No GDELT files were available for the requested period")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(
            all_records, started_at, error=error_msg,
            metadata={"files_downloaded": downloaded, "files_skipped": skipped},
        )

    def test_connection(self) -> bool:
        """Test connection by fetching the GDELT last-update file."""
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(GDELT_LAST_UPDATE_URL)
                resp.raise_for_status()
                return "export.CSV" in resp.text
        except Exception:
            return False
