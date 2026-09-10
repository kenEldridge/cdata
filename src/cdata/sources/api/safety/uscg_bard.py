"""USCG Boating Accident Report Database (BARD) source (Layer B, incident).

The one Tier-1/2 source that actually covers ordinary recreational-water
drownings away from the coast - a boating death on Lake Norman, NC, or any
other inland lake, shows up here even though it's neither a coastal surf-zone
death (NWS) nor a storm-driven one (NCEI). Confirmed by inspecting the real
files: 14 Lake Norman drowning deaths, 2014-2022 alone.

USCG doesn't publish BARD directly; the Data Liberation Project got it via
FOIA and republishes converted CSVs, split into three non-overlapping
periods (2009-2013, 2014-2022, 2023), each with linked ``Accidents`` and
``Deaths`` tables joined on ``BARDID``:

    https://www.data-liberation-project.org/datasets/uscg-boating-accident-report-database/

Not every boating death is a drowning - confirmed live: of 8,935 deaths
across all three periods, 6,087 (68%) have ``CauseofDeath == "Drowning"``;
the rest are trauma, cardiac arrest, hypothermia, carbon monoxide, etc. Only
drowning rows are kept.

Coordinates are present (``LATITUDE``/``LONGITUDE``) but sparse (~13% of
accidents overall) and only trusted when ``CoordinatesConfidence == "C"``
(confident) - "NC" rows exist and are deliberately not trusted as exact.
Everything else falls back to ``NameOfBodyOfWater``/``NearestCityorTown``
for the geocoder, same as any other place-name source.

``RedactedNarrative`` (a free-text accident description) exists in the
Accidents table but is deliberately not ingested, matching this project's
established precedent in ``ncei_storm_events.py`` of not carrying free text
past the privacy allowlist even when a third party claims to have redacted
it - a name check missed once still leaks a name.

``DeceasedGender`` uses undocumented codes (observed live: only ``-1`` and
``0``, no ``1`` - plausibly an MS Access boolean export rather than a real
sex code) and is not confidently mappable without the field dictionary this
class couldn't reach; every row maps to sex ``"U"`` rather than guess.
"""

import csv
import io
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

BASE_URL = (
    "https://dlp-cdn.muckrock.com/USCG%20Boating%20Accident%20Report%20"
    "Database%20(BARD)/Converted%20Files/CSV/"
)

#: (accidents_filename, deaths_filename) per non-overlapping period.
PERIOD_FILES = (
    ("bard-2009-2013-ReleasableAccidents.csv", "bard-2009-2013-ReleasableDeaths.csv"),
    ("bard-2014-2022-ReleasableAccidentes.csv", "bard-2014-2022-ReleasableDeaths.csv"),
    ("bard-2023-2023-ReleasableAccidents.csv", "bard-2023-2023-ReleasableDeaths.csv"),
)

#: AccidentEvent1 -> canonical hazard. Only the clean matches; everything
#: else (collisions, groundings, fire, skier mishaps, ...) stays "unknown"
#: rather than force a boating-specific event into an ocean-hazard bucket.
ACCIDENT_EVENT_HAZARDS = {
    "capsizing": "vessel_capsize",
    "falls overboard": "fall_overboard",
    "person ejected from vessel": "fall_overboard",
    "person departed vessel": "fall_overboard",
    "flooding/swamping": "flood",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


class USCGBardSource(BaseSource):
    """USCG BARD source, filtered to boating deaths by drowning.

    Config keys:
        periods: which (accidents, deaths) filename pairs to fetch, default
            all three (:data:`PERIOD_FILES`)
    """

    source_type = "uscg_bard"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._headers = {"User-Agent": USER_AGENT}

    @staticmethod
    def _as_coord(value: Any) -> Optional[float]:
        try:
            f = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        return f if f != 0.0 else None

    @staticmethod
    def _parse_bard_date(raw: str) -> tuple[Optional[str], str]:
        text = _clean(raw)
        if not text:
            return None, "year"
        head = text.split(" ")[0]
        try:
            return datetime.strptime(head, "%Y-%m-%d").date().isoformat(), "day"
        except ValueError:
            return None, "year"

    def _deaths_by_bardid(
        self, client: httpx.Client, deaths_url: str
    ) -> dict[str, list[dict[str, str]]]:
        response = client.get(deaths_url)
        by_bardid: dict[str, list[dict[str, str]]] = {}
        for row in _read_csv(response.content):
            cause = _clean(row.get("CauseofDeath")).lower()
            if cause != "drowning":
                continue
            by_bardid.setdefault(_clean(row.get("BARDID")), []).append(row)
        return by_bardid

    def _incidents_for_period(
        self,
        client: httpx.Client,
        accidents_url: str,
        deaths_url: str,
        started_at: datetime,
    ) -> list[dict[str, Any]]:
        deaths = self._deaths_by_bardid(client, deaths_url)
        if not deaths:
            return []

        response = client.get(accidents_url)

        incidents: list[dict[str, Any]] = []
        for row in _read_csv(response.content):
            bardid = _clean(row.get("BARDID"))
            deceased_rows = deaths.get(bardid)
            if not deceased_rows:
                continue

            state = normalize_state(_clean(row.get("State")))
            if not state:
                continue

            iso_date, precision = self._parse_bard_date(row.get("Date"))
            water_body_name = _clean(row.get("NameOfBodyOfWater")) or None
            place_name = _clean(row.get("NearestCityorTown")) or water_body_name or ""

            lat = lon = None
            if _clean(row.get("CoordinatesConfidence")).upper() == "C":
                lat = self._as_coord(row.get("LATITUDE"))
                lon = self._as_coord(row.get("LONGITUDE"))

            event = _clean(row.get("AccidentEvent1")).lower()
            hazard = ACCIDENT_EVENT_HAZARDS.get(event, "unknown")

            for deceased in deceased_rows:
                deceased_id = _clean(deceased.get("DeceasedID")) or "0"
                age, age_text = parse_age(deceased.get("DeceasedAge"))

                incidents.append(
                    build_incident(
                        source_id=self.source_id,
                        source_url=(
                            "https://www.data-liberation-project.org/datasets/"
                            "uscg-boating-accident-report-database/"
                        ),
                        natural_key=f"{bardid}|{deceased_id}",
                        date_value=iso_date,
                        date_precision=precision,
                        state=state,
                        place_name=place_name,
                        lat=lat,
                        lon=lon,
                        geo_precision="exact" if lat is not None else "unknown",
                        water_body_type=classify_water_body(water_body_name, place_name),
                        water_body_name=water_body_name,
                        hazard=hazard,
                        activity="boating",
                        intent="unintentional",
                        age=age,
                        age_text=age_text,
                        sex="U",
                        fatal=True,
                        notes=f"Boating accident ({event or 'unspecified event'})",
                        fetched_at=started_at,
                    )
                )
        return incidents

    # -- BaseSource -------------------------------------------------------

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch boating-drowning deaths as canonical incident records."""
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []
        periods = kwargs.get("periods") or PERIOD_FILES
        periods_fetched: list[str] = []

        with httpx.Client(
            timeout=180, follow_redirects=True, headers=self._headers
        ) as client:
            for accidents_file, deaths_file in periods:
                try:
                    incidents = self._incidents_for_period(
                        client, BASE_URL + accidents_file, BASE_URL + deaths_file,
                        started_at,
                    )
                except Exception as exc:
                    errors.append(f"{accidents_file}: {exc}")
                    continue

                periods_fetched.append(accidents_file)
                for incident in incidents:
                    records.append(
                        self._create_record(
                            data=incident, metadata={"layer": "incident"}
                        )
                    )

        return self._create_result(
            records,
            started_at,
            error="; ".join(errors) if errors else None,
            metadata={
                "periods_fetched": periods_fetched,
                "source_documentation": (
                    "https://www.data-liberation-project.org/datasets/"
                    "uscg-boating-accident-report-database/"
                ),
                "caveat": (
                    "Recreational boating deaths only, 2009-2023, filtered to "
                    "drowning as cause of death. Coordinates are sparse and "
                    "only trusted when the source itself flags them confident; "
                    "most rows fall back to place-name geocoding."
                ),
            },
        )

    def test_connection(self) -> bool:
        """Cheapest real request: HEAD the smallest deaths file."""
        try:
            with httpx.Client(
                timeout=30, follow_redirects=True, headers=self._headers
            ) as client:
                response = client.head(BASE_URL + PERIOD_FILES[0][1])
                return response.status_code == 200
        except Exception:
            return False
