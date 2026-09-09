"""NWS Surf Zone Fatalities source (Layer B, incident-level).

The National Weather Service publishes a preliminary surf-zone fatality table
per year - roughly 50-130 rows/yr across the coasts and the Great Lakes:

    current year: https://www.weather.gov/safety/ripcurrent-fatalities
    prior years:  https://www.weather.gov/safety/ripcurrent-fatalities-25 (etc.)

The HTML year tables are the primary source: they are the published record,
they cover every year, and their ``Total:`` row is what any count should be
checked against.

The page also embeds an ArcGIS webmap. Contrary to what one might expect it
does *not* expose a queryable FeatureServer - its operational layers are an
embedded ``featureCollection`` plus a hosted CSV - and it only covers the last
couple of years. So it is used for what it is genuinely good for: attaching
real coordinates (``geo_precision = "exact"``) to the HTML rows it overlaps,
which saves geocoding those. Rows it does not cover fall through to the
geocoder as normal.

That webmap also publishes ``Hometown_City`` and ``Hometown_State`` per victim.
Those are never read here, and the canonical allowlist in
:func:`cdata.transforms.drowning.sanitize_incident` would drop them even if a
future edit tried to.

The page advertises a CSV at ``/source/safety/Surf_Zone_Fatalities.csv``, which
is still 404. Rather than ship a parser for a schema nobody has seen, each run
probes that URL and reports the result in fetch metadata (``csv_available``);
if it ever returns 200, add the parser then.

NWS states plainly that this data is preliminary, that locations are
approximate, and that it undercounts. That caveat travels with the data into
the dashboard rather than living only in this docstring.
"""

import io
import json
import re
from datetime import date, datetime
from typing import Any, Optional

import httpx

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource
from cdata.transforms.drowning import (
    USER_AGENT,
    build_incident,
    classify_water_body,
    normalize_place,
    normalize_state,
    parse_age,
    parse_incident_date,
)

CURRENT_URL = "https://www.weather.gov/safety/ripcurrent-fatalities"
YEAR_URL_TEMPLATE = "https://www.weather.gov/safety/ripcurrent-fatalities-{yy:02d}"
CSV_URL = "https://www.weather.gov/source/safety/Surf_Zone_Fatalities.csv"

ARCGIS_ITEM_DATA = (
    "https://noaa.maps.arcgis.com/sharing/rest/content/items/{item_id}/data?f=json"
)

#: Flag columns on the HTML table, in the order NWS prints them, mapped to
#: canonical hazards. "Other" carries a numeric suffix decoded from the page
#: legend (see :func:`_parse_legend`).
FLAG_COLUMN_HAZARDS = {
    "rip current": "rip_current",
    "high surf": "high_surf",
    "sneaker wave": "sneaker_wave",
    "other": None,  # resolved via the legend
    "not known": "unknown",
}

#: Fallback legend, used only when the page's own legend cannot be parsed.
#: The live legend is authoritative - it has changed before.
DEFAULT_LEGEND_HAZARDS = {
    "1": "longshore_current",
    "2": "structural_current",
    "3": "structural_current",
    "4": "structural_current",
    "5": "high_surf",
    "6": "structural_current",
    "7": "structural_current",
    "8": "structural_current",
    "9": "structural_current",
    "10": "submersion_other",
}

#: Legend keyword -> canonical hazard. Applied to the text NWS prints beside
#: each legend number, so a renumbered or reworded legend still maps correctly.
LEGEND_KEYWORDS = (
    ("longshore", "longshore_current"),
    ("shore break", "high_surf"),
    ("shorebreak", "high_surf"),
    ("wave", "high_surf"),
    ("structur", "structural_current"),
    ("pier", "structural_current"),
    ("jetty", "structural_current"),
    ("groin", "structural_current"),
    ("inlet", "structural_current"),
    ("channel", "structural_current"),
    ("outlet", "structural_current"),
    ("tidal", "structural_current"),
    ("sandbar", "structural_current"),
    ("current", "structural_current"),
)

_FLAG_RE = re.compile(r"^\s*x\s*[-–]?\s*(\d+)?\s*$", re.I)
_LEGEND_RE = re.compile(r"(\d{1,2})\s*[).:-]\s*([A-Za-z][^\d\n]{2,60})")


def _clean(text: Any) -> str:
    """Whitespace-normalize a cell, treating pandas NaN as empty."""
    if text is None:
        return ""
    if isinstance(text, float) and text != text:  # NaN
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _published_total(html: str) -> Optional[int]:
    """Read the table's own ``Total:`` figure, for checking parsed counts.

    Reported in fetch metadata rather than enforced. NWS revises the table
    in-season, so a mismatch is a signal to look, not a reason to fail a run.
    """
    match = re.search(r"Total:\s*(\d{1,4})", html, re.I)
    return int(match.group(1)) if match else None


def _promote_header(table: Any) -> Any:
    """Return the table with a real header row, or ``None`` if it is not ours.

    NWS marks the fatality table's header with ``<td>`` rather than ``<th>``,
    so ``read_html`` hands back integer column labels and the header sitting in
    row 0. Older year pages do use a proper header. Both shapes are accepted:
    if the labels are not already the ones we want, the first few rows are
    searched for the header and everything above it is dropped.
    """
    columns = [_clean(c).lower() for c in table.columns]
    if "location" in columns and "st" in columns:
        table = table.copy()
        table.columns = columns
        return table

    for position in range(min(4, len(table))):
        candidate = [_clean(c).lower() for c in table.iloc[position].tolist()]
        if "location" in candidate and "st" in candidate:
            trimmed = table.iloc[position + 1:].copy()
            trimmed.columns = candidate
            return trimmed
    return None


def _parse_legend(html: str) -> dict[str, str]:
    """Decode the ``Other (see Key)`` legend printed under the table.

    Returns ``{"1": "longshore_current", ...}``. Falls back to
    :data:`DEFAULT_LEGEND_HAZARDS` when nothing parses - hardcoding the legend
    outright would silently mis-map every row the year NWS renumbers it.
    """
    # Scan only from the last "Key" mention onward. The first mention is the
    # "Other (see Key)" column header; the legend itself sits below the table,
    # and starting there keeps stray numbering in the table out of the legend.
    markers = list(re.finditer(r"\bkey\b", html, re.I))
    section = html[markers[-1].start():] if markers else html
    # NWS wraps each legend number in <sup> tags, which would otherwise sit
    # between the number and its description and defeat the match.
    section = re.sub(r"<[^>]+>", " ", section)

    legend: dict[str, str] = {}
    for number, description in _LEGEND_RE.findall(section):
        text = _clean(description).lower()
        for keyword, hazard in LEGEND_KEYWORDS:
            if keyword in text:
                legend[number] = hazard
                break
        else:
            legend.setdefault(number, "submersion_other")
    return legend or dict(DEFAULT_LEGEND_HAZARDS)


class NWSSurfZoneSource(BaseSource):
    """NWS surf zone fatality data source.

    Config keys:
        start_year: earliest year page to probe (default 2010)
        prefer_arcgis: enrich HTML rows with coordinates from the webmap
        arcgis_item_id: webmap item id backing the page's embedded map
        max_missing_years: stop probing backwards after this many 404s
    """

    source_type = "nws_surf_zone"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._headers = {"User-Agent": USER_AGENT}

    # -- ArcGIS coordinate enrichment -------------------------------------

    @staticmethod
    def _arcgis_row_key(state: Any, location: Any, iso_date: Optional[str]) -> tuple:
        return (normalize_state(state) or "", normalize_place(location),
                iso_date or "")

    def _arcgis_coordinates(
        self, client: httpx.Client, item_id: str
    ) -> dict[tuple, tuple[float, float]]:
        """Build ``{(state, place, date): (lat, lon)}`` from the webmap.

        The webmap's operational layers are an embedded ``featureCollection``
        and a hosted CSV, not a queryable FeatureServer. Both are read for their
        ``Lat``/``Long`` attributes; the projected geometry (Web Mercator) is
        ignored in favour of those, which are already in degrees.

        Only coordinates are taken. The layers also carry ``Hometown_City`` and
        ``Hometown_State``, which are exactly the kind of field this project
        does not ingest.
        """
        response = client.get(ARCGIS_ITEM_DATA.format(item_id=item_id))
        response.raise_for_status()
        # The item JSON declares utf-8 but carries latin-1 bytes in Spanish
        # place names, so a strict decode raises partway through.
        payload = json.loads(response.content.decode("utf-8", errors="replace"))

        index: dict[tuple, tuple[float, float]] = {}

        def add(attrs: dict[str, Any]) -> None:
            try:
                lat = float(attrs.get("Lat"))
                lon = float(attrs.get("Long"))
            except (TypeError, ValueError):
                return
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return

            iso_date = None
            try:
                iso_date = date(
                    int(attrs["Year"]), int(attrs["Month"]), int(attrs["Day"])
                ).isoformat()
            except (KeyError, TypeError, ValueError):
                iso_date = None

            state, location = attrs.get("State"), attrs.get("Location")
            index.setdefault(self._arcgis_row_key(state, location, iso_date),
                             (lat, lon))
            # Also key without the date, as a looser fallback.
            index.setdefault(self._arcgis_row_key(state, location, None),
                             (lat, lon))

        for layer in payload.get("operationalLayers", []) or []:
            collection = layer.get("featureCollection") or {}
            for sub in collection.get("layers", []) or []:
                for feature in (sub.get("featureSet") or {}).get("features", []) or []:
                    add(feature.get("attributes") or {})

            url = layer.get("url")
            if url and str(layer.get("layerType", "")).upper() == "CSV":
                try:
                    import pandas as pd

                    csv_response = client.get(url)
                    csv_response.raise_for_status()
                    frame = pd.read_csv(
                        io.StringIO(csv_response.content.decode("utf-8", "replace"))
                    )
                    for row in frame.to_dict(orient="records"):
                        add(row)
                except Exception:
                    # A hosted CSV that moved or changed shape costs us
                    # coordinates for those rows, nothing more.
                    continue

        return index

    def _year_pages(
        self, client: httpx.Client, start_year: int, max_missing_years: int
    ) -> list[tuple[int, str, str]]:
        """Return ``(year, url, html)`` for the current year and prior years.

        Prior-year URLs use a 2-digit suffix; NWS does not publish an index of
        them, so we probe backwards and stop after a run of 404s.
        """
        pages: list[tuple[int, str, str]] = []
        this_year = datetime.utcnow().year

        response = client.get(CURRENT_URL)
        if response.status_code == 200:
            pages.append((this_year, CURRENT_URL, response.text))

        missing = 0
        for year in range(this_year - 1, start_year - 1, -1):
            url = YEAR_URL_TEMPLATE.format(yy=year % 100)
            try:
                page = client.get(url)
            except httpx.HTTPError:
                missing += 1
                if missing >= max_missing_years:
                    break
                continue
            if page.status_code == 200:
                missing = 0
                pages.append((year, url, page.text))
            else:
                missing += 1
                if missing >= max_missing_years:
                    break
        return pages

    # -- parsing ----------------------------------------------------------

    def _rows_from_html(self, html: str, year: int) -> list[dict[str, Any]]:
        """Parse the surf-zone table out of one year page.

        Column layout: ``Rip Current | High Surf | Sneaker Wave | Other (see
        Key) | Not Known | Location | ST | M/F | Age | Date``. The first five
        are ``X``-marked flags that collapse into a single hazard.
        """
        import pandas as pd

        legend = _parse_legend(html)
        try:
            tables = pd.read_html(io.StringIO(html))
        except ValueError:
            return []

        rows: list[dict[str, Any]] = []
        for table in tables:
            table = _promote_header(table)
            if table is None:
                continue
            columns = list(table.columns)

            # Header text carries qualifiers - the "Other" flag column is
            # printed as "Other (see Key)" - so flag columns are matched by
            # prefix rather than by an exact string.
            flag_columns: list[tuple[str, Optional[str]]] = []
            for key, mapped in FLAG_COLUMN_HAZARDS.items():
                actual = next(
                    (c for c in columns if c == key or c.startswith(key)), None
                )
                if actual:
                    flag_columns.append((actual, mapped))

            for _, raw in table.iterrows():
                location = _clean(raw.get("location"))
                state = _clean(raw.get("st"))
                # Skip the trailing blank padding rows, the "Total:" row, and
                # the legend row (which NWS puts inside the same table, its
                # text repeated across every cell).
                if not location or not state:
                    continue
                lowered = location.lower()
                if lowered.startswith("total") or lowered.startswith("key:"):
                    continue

                hazard = "unknown"
                for column, mapped in flag_columns:
                    flag = _clean(raw.get(column))
                    match = _FLAG_RE.match(flag)
                    if not match:
                        continue
                    if mapped is not None:
                        hazard = mapped
                    else:
                        suffix = match.group(1)
                        hazard = legend.get(suffix, "submersion_other")
                    break

                rows.append(
                    {
                        "location": location,
                        "state": state,
                        "sex": _clean(raw.get("m/f") or raw.get("m / f")),
                        "age": _clean(raw.get("age")),
                        "date": _clean(raw.get("date")),
                        "hazard": hazard,
                        "year": year,
                    }
                )
        return rows

    def _incident_from_html_row(
        self, row: dict[str, Any], source_url: str, started_at: datetime,
        occurrence: int = 0,
    ) -> Optional[dict[str, Any]]:
        """Build a canonical incident from one parsed table row.

        ``occurrence`` distinguishes rows whose every published field matches -
        two people drowning at the same beach, on the same day, of the same age
        and sex is rare but real, and without it the second row would collapse
        into the first and quietly undercount. It is the row's index among
        identical rows on the same page, so re-fetching the same page produces
        the same ids.
        """
        state = normalize_state(row["state"])
        if not state:
            return None
        iso_date, precision = parse_incident_date(row["date"], year_hint=row["year"])
        age, age_text = parse_age(row["age"])
        natural_key = (
            f"{iso_date}|{state}|{row['location']}|{row['sex']}|{age_text}"
            f"|{occurrence}"
        )

        return build_incident(
            source_id=self.source_id,
            source_url=source_url,
            natural_key=natural_key,
            date_value=iso_date,
            date_precision=precision,
            state=state,
            place_name=row["location"],
            geo_precision="unknown",
            water_body_type=classify_water_body(None, row["location"]),
            hazard=row["hazard"],
            activity="unknown",
            intent="unintentional",
            age=age,
            age_text=age_text,
            sex=row["sex"],
            fatal=True,
            fetched_at=started_at,
        )

    # -- BaseSource -------------------------------------------------------

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch surf zone fatalities as canonical incident records."""
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []
        metadata: dict[str, Any] = {}

        start_year = int(kwargs.get("start_year", 2010))
        prefer_arcgis = bool(kwargs.get("prefer_arcgis", True))
        item_id = kwargs.get("arcgis_item_id", "0c1d0029571141a6a26160d14cf1179c")
        max_missing_years = int(kwargs.get("max_missing_years", 3))

        with httpx.Client(
            timeout=45, follow_redirects=True, headers=self._headers
        ) as client:
            # Reports whether the advertised CSV has come back, from a real
            # request rather than an assumption.
            try:
                metadata["csv_available"] = client.head(CSV_URL).status_code == 200
            except httpx.HTTPError:
                metadata["csv_available"] = False

            coordinates: dict[tuple, tuple[float, float]] = {}
            if prefer_arcgis and item_id:
                try:
                    coordinates = self._arcgis_coordinates(client, item_id)
                except Exception as exc:
                    errors.append(f"ArcGIS coordinate lookup failed: {exc}")
            metadata["arcgis_coordinates"] = len(coordinates)

            try:
                pages = self._year_pages(client, start_year, max_missing_years)
            except Exception as exc:
                pages = []
                errors.append(f"Year page probe failed: {exc}")

            seen: set[str] = set()
            published_totals: dict[int, Optional[int]] = {}
            matched = 0

            for year, url, html in pages:
                published_totals[year] = _published_total(html)
                # Occurrence counter per page, so identical published rows stay
                # distinct while the same row on two pages still dedupes.
                occurrences: dict[tuple, int] = {}

                for row in self._rows_from_html(html, year):
                    signature = (row["date"], row["state"], row["location"],
                                 row["sex"], row["age"])
                    occurrence = occurrences.get(signature, 0)
                    occurrences[signature] = occurrence + 1

                    incident = self._incident_from_html_row(
                        row, url, started_at, occurrence=occurrence
                    )
                    if not incident or incident["incident_id"] in seen:
                        continue
                    seen.add(incident["incident_id"])

                    # Attach real coordinates where the webmap covers this row;
                    # everything else falls through to the geocoder.
                    hit = coordinates.get(
                        self._arcgis_row_key(
                            incident["state"], incident["place_name"],
                            incident["date"],
                        )
                    ) or coordinates.get(
                        self._arcgis_row_key(
                            incident["state"], incident["place_name"], None
                        )
                    )
                    if hit:
                        incident["lat"], incident["lon"] = hit
                        incident["geo_precision"] = "exact"
                        matched += 1

                    records.append(
                        self._create_record(
                            data=incident,
                            metadata={"layer": "incident", "year": year},
                        )
                    )

            metadata["years_parsed"] = [year for year, _, _ in pages]
            metadata["published_totals"] = published_totals
            metadata["rows_with_coordinates"] = matched

        if not records and not errors:
            errors.append("No surf zone fatality rows parsed from any year page")

        metadata["caveat"] = (
            "NWS states this data is preliminary, that locations are "
            "approximate, and that the count is an undercount."
        )
        return self._create_result(
            records, started_at,
            error="; ".join(errors) if errors else None,
            metadata=metadata,
        )

    def test_connection(self) -> bool:
        """Cheapest real request: HEAD the current-year fatality page."""
        try:
            with httpx.Client(
                timeout=15, follow_redirects=True, headers=self._headers
            ) as client:
                response = client.head(CURRENT_URL)
                if response.status_code >= 400:
                    response = client.get(CURRENT_URL)
                return response.status_code == 200
        except Exception:
            return False
