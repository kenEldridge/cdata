"""NCEI Storm Events water-fatality source (Layer B, incident-level).

NOAA's Storm Events Database covers weather-caused deaths from 1996 to the
present and, unlike most incident sources, ships real coordinates. Bulk
gzipped CSVs live at:

    https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/

Three linked file families per year, joined on ``EVENT_ID``:

    StormEvents_details-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz
    StormEvents_locations-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz
    StormEvents_fatalities-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz

The trailing ``cYYYYMMDD`` is a creation stamp that changes when NCEI revises a
year, so filenames are scraped from the directory index rather than
constructed. Only water-relevant event types are kept, and within those only
fatalities whose ``FATALITY_LOCATION`` implies water.

These are *weather-caused* drownings only. A backyard pool drowning on a clear
day is not here, and this dataset is not a substitute for the CDC totals.
"""

import csv
import gzip
import io
import re
from datetime import datetime
from typing import Any, Optional

import httpx

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource
from cdata.transforms.drowning import (
    USER_AGENT,
    build_incident,
    classify_water_body,
    normalize_state,
    parse_age,
)

BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
FORMAT_DOC_URL = BASE_URL + "Storm-Data-Bulk-csv-Format.pdf"

#: Event types that can produce a drowning. Anything else is dropped before the
#: fatalities join, which keeps the download-and-parse cost down.
DEFAULT_EVENT_TYPES = (
    "Rip Current",
    "High Surf",
    "Flash Flood",
    "Flood",
    "Coastal Flood",
    "Storm Surge/Tide",
    "Tsunami",
    "Marine Thunderstorm Wind",
)

#: ``FATALITY_LOCATION`` values that imply the death was in or under water.
#: The rest of the live value set - OUTSIDE/OPEN AREAS, PERMANENT HOME,
#: PERMANENT STRUCTURE, MOBILE/TRAILER HOME, CAMPING, UNDER TREE, BUSINESS,
#: UNKNOWN - is excluded. "UNKNOWN" is excluded deliberately: for a drowning
#: dataset, an unknown location is not evidence of a drowning.
#: Unrecognized values are counted in fetch metadata rather than silently kept,
#: so a new value shows up as a number to look at instead of as bad rows.
WATER_FATALITY_LOCATIONS = frozenset(
    {
        "IN WATER",
        "BOATING",
        "VEHICLE/TOWED TRAILER",
        "LONG SPAN ROADWAY",
        "UNDER WATER",
    }
)

#: Event type -> canonical hazard.
EVENT_TYPE_HAZARDS = {
    "rip current": "rip_current",
    "high surf": "high_surf",
    "sneaker wave": "sneaker_wave",
    "flash flood": "flood",
    "flood": "flood",
    "coastal flood": "flood",
    "heavy rain": "flood",
    "storm surge/tide": "flood",
    "tsunami": "flood",
    "marine thunderstorm wind": "vessel_capsize",
    "marine strong wind": "vessel_capsize",
    "marine high wind": "vessel_capsize",
}

#: ``FATALITY_LOCATION`` -> canonical activity.
FATALITY_LOCATION_ACTIVITIES = {
    "IN WATER": "swimming",
    "UNDER WATER": "swimming",
    "BOATING": "boating",
    "VEHICLE/TOWED TRAILER": "vehicle",
    "LONG SPAN ROADWAY": "vehicle",
}

_FILE_RE = re.compile(
    r"StormEvents_(details|locations|fatalities)-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz",
    re.I,
)


def _clean(value: Any) -> str:
    """Whitespace-normalize a cell, treating None and NaN as empty."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _read_gz_csv(content: bytes) -> list[dict[str, str]]:
    """Decompress and parse one gzipped Storm Events CSV."""
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as handle:
        text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
        return list(csv.DictReader(text))


class NCEIStormEventsSource(BaseSource):
    """NCEI Storm Events source, filtered to water-related fatalities.

    Config keys:
        start_year: earliest data year to fetch (default 1996)
        end_year: latest data year (default: current year)
        event_types: event types to keep (default :data:`DEFAULT_EVENT_TYPES`)
        max_years: hard cap on years fetched per run, newest first
    """

    source_type = "ncei_storm_events"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._headers = {"User-Agent": USER_AGENT}

    # -- directory index --------------------------------------------------

    def _index_files(self, client: httpx.Client) -> dict[int, dict[str, str]]:
        """Scrape the directory index into ``{year: {family: url}}``.

        When NCEI leaves several creation stamps for one year in place, the
        newest stamp wins - that is the revised file.
        """
        response = client.get(BASE_URL)
        response.raise_for_status()

        best: dict[tuple[int, str], tuple[str, str]] = {}
        for match in _FILE_RE.finditer(response.text):
            family, year_text, stamp = match.group(1).lower(), match.group(2), match.group(3)
            key = (int(year_text), family)
            if key not in best or stamp > best[key][0]:
                best[key] = (stamp, BASE_URL + match.group(0))

        index: dict[int, dict[str, str]] = {}
        for (year, family), (_stamp, url) in best.items():
            index.setdefault(year, {})[family] = url
        return index

    # -- per-year parsing -------------------------------------------------

    def _incidents_for_year(
        self,
        client: httpx.Client,
        year: int,
        urls: dict[str, str],
        event_types: set[str],
        started_at: datetime,
        unknown_locations: dict[str, int],
    ) -> list[dict[str, Any]]:
        if "details" not in urls or "fatalities" not in urls:
            return []

        details_rows = _read_gz_csv(client.get(urls["details"]).content)
        wanted: dict[str, dict[str, str]] = {}
        for row in details_rows:
            if _clean(row.get("EVENT_TYPE")).lower() in event_types:
                wanted[_clean(row.get("EVENT_ID"))] = row
        if not wanted:
            return []

        fatality_rows = _read_gz_csv(client.get(urls["fatalities"]).content)

        incidents: list[dict[str, Any]] = []
        for fatality in fatality_rows:
            event_id = _clean(fatality.get("EVENT_ID"))
            detail = wanted.get(event_id)
            if detail is None:
                continue

            location = _clean(fatality.get("FATALITY_LOCATION")).upper()
            if location not in WATER_FATALITY_LOCATIONS:
                if location:
                    unknown_locations[location] = unknown_locations.get(location, 0) + 1
                continue

            state = normalize_state(_clean(detail.get("STATE")))
            if not state:
                continue

            event_type = _clean(detail.get("EVENT_TYPE"))
            hazard = EVENT_TYPE_HAZARDS.get(event_type.lower(), "submersion_other")

            # FATALITY_DATE is the authoritative date; fall back to the event.
            raw_date = (
                _clean(fatality.get("FATALITY_DATE"))
                or _clean(detail.get("BEGIN_DATE_TIME"))
            )
            iso_date, precision = self._parse_ncei_date(raw_date, year)

            age, age_text = parse_age(_clean(fatality.get("FATALITY_AGE")))
            place_name = _clean(detail.get("CZ_NAME")) or _clean(detail.get("BEGIN_LOCATION"))
            county_fips = self._county_fips(detail)

            lat = self._as_float(detail.get("BEGIN_LAT"))
            lon = self._as_float(detail.get("BEGIN_LON"))

            fatality_id = _clean(fatality.get("FATALITY_ID")) or event_id
            fatality_type = _clean(fatality.get("FATALITY_TYPE")).upper()

            incidents.append(
                build_incident(
                    source_id=self.source_id,
                    source_url=urls["details"],
                    natural_key=f"{event_id}|{fatality_id}",
                    date_value=iso_date,
                    date_precision=precision,
                    state=state,
                    county_fips=county_fips,
                    place_name=place_name,
                    lat=lat,
                    lon=lon,
                    # Zone-based events (CZ_TYPE "Z", common for Rip Current)
                    # carry no BEGIN_LAT and no county, only a forecast-zone
                    # name - so they claim "place", not "county", and fall
                    # through to the geocoder like any other place name.
                    geo_precision=(
                        "exact" if lat is not None and lon is not None
                        else ("county" if county_fips else "place")
                    ),
                    water_body_type=classify_water_body(None, place_name),
                    hazard=hazard,
                    activity=FATALITY_LOCATION_ACTIVITIES.get(location, "unknown"),
                    intent="unintentional",
                    age=age,
                    age_text=age_text,
                    sex=_clean(fatality.get("FATALITY_SEX")),
                    fatal=True,
                    # Structured provenance only - the free-text EPISODE_NARRATIVE
                    # and EVENT_NARRATIVE fields are deliberately not ingested.
                    notes=f"{event_type} ({'direct' if fatality_type == 'D' else 'indirect'})",
                    fetched_at=started_at,
                )
            )
        return incidents

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _county_fips(detail: dict[str, str]) -> Optional[str]:
        """Assemble a 5-digit county FIPS from the split NCEI columns."""
        state_fips = _clean(detail.get("STATE_FIPS"))
        cz_fips = _clean(detail.get("CZ_FIPS"))
        cz_type = _clean(detail.get("CZ_TYPE")).upper()
        # Only "C" rows are counties; "Z" is a forecast zone and "M" is marine.
        if cz_type != "C" or not state_fips or not cz_fips:
            return None
        try:
            return f"{int(float(state_fips)):02d}{int(float(cz_fips)):03d}"
        except ValueError:
            return None

    @staticmethod
    def _parse_ncei_date(raw: str, year: int) -> tuple[Optional[str], str]:
        """Parse the NCEI date formats (``MM/DD/YYYY HH:MM:SS``, ``DD-MON-YY``)."""
        text = _clean(raw)
        if not text:
            return f"{year:04d}-01-01", "year"
        head = text.split(" ")[0]
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(head, fmt).date().isoformat(), "day"
            except ValueError:
                continue
        return f"{year:04d}-01-01", "year"

    # -- BaseSource -------------------------------------------------------

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch water-related storm fatalities as canonical incident records."""
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        start_year = int(kwargs.get("start_year", 1996))
        end_year = int(kwargs.get("end_year", datetime.utcnow().year))
        event_types = {
            str(t).lower()
            for t in (kwargs.get("event_types") or DEFAULT_EVENT_TYPES)
        }
        max_years = kwargs.get("max_years")

        unknown_locations: dict[str, int] = {}
        years_fetched: list[int] = []

        with httpx.Client(
            timeout=180, follow_redirects=True, headers=self._headers
        ) as client:
            try:
                index = self._index_files(client)
            except Exception as exc:
                return self._create_result(
                    records, started_at, error=f"Could not read NCEI index: {exc}"
                )

            years = sorted(
                (y for y in index if start_year <= y <= end_year), reverse=True
            )
            if max_years:
                years = years[: int(max_years)]

            for year in years:
                try:
                    incidents = self._incidents_for_year(
                        client, year, index[year], event_types, started_at,
                        unknown_locations,
                    )
                except Exception as exc:
                    errors.append(f"{year}: {exc}")
                    continue

                years_fetched.append(year)
                for incident in incidents:
                    records.append(
                        self._create_record(
                            data=incident,
                            metadata={"layer": "incident", "year": year},
                        )
                    )

        return self._create_result(
            records,
            started_at,
            error="; ".join(errors) if errors else None,
            metadata={
                "years_fetched": sorted(years_fetched),
                "unrecognized_fatality_locations": unknown_locations,
                "format_documentation": FORMAT_DOC_URL,
                "caveat": (
                    "Weather-caused deaths only, 1996-present, with a two to "
                    "three month reporting lag; recent years are revised."
                ),
            },
        )

    def test_connection(self) -> bool:
        """Cheapest real request: fetch the bulk CSV directory index."""
        try:
            with httpx.Client(
                timeout=30, follow_redirects=True, headers=self._headers
            ) as client:
                response = client.get(BASE_URL)
                response.raise_for_status()
                return bool(_FILE_RE.search(response.text))
        except Exception:
            return False
