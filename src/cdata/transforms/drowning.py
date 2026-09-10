"""Canonical drowning / water-safety schemas, normalizers and dedup.

There is no single national incident-level drowning database. What exists splits
into two incompatible shapes, and this module keeps them apart:

  * ``drowning_incidents`` (Layer B) - one row per death, with a date and a place.
  * ``drowning_stats``     (Layer A) - death counts and rates by year/geo/strata.

They double-count each other (a rip-current death appears in NWS *and* in CDC's
W65-W74 total), so nothing here ever merges them into one table.

Privacy constraints (non-negotiable):

  * No victim identification. Incident rows carry date, place, hazard, age band,
    sex and provenance - nothing else. :func:`sanitize_incident` enforces a hard
    field allowlist *at ingest*, so a source that starts publishing names cannot
    leak them downstream.
  * Intentional drowning (ICD-10 ``X71``, ``X92``) is excluded entirely from the
    incident layer and from the aggregate layer.
  * Suppression is data: a suppressed aggregate cell keeps ``value=None`` and
    ``suppressed=True``. It is never rendered, or stored, as zero.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Canonical field lists - the allowlist. Anything not here is dropped at ingest.
# ---------------------------------------------------------------------------

INCIDENT_FIELDS: tuple[str, ...] = (
    "incident_id",
    "source_id",
    "source_url",
    "date",
    "date_precision",
    "state",
    "county_fips",
    "place_name",
    "lat",
    "lon",
    "geo_precision",
    "water_body_type",
    "water_body_name",
    "hazard",
    "activity",
    "intent",
    "age",
    "age_text",
    "age_band",
    "sex",
    "fatal",
    "notes",
    "superseded_by",
    "fetched_at",
)

STAT_FIELDS: tuple[str, ...] = (
    "stat_id",
    "source_id",
    "source_url",
    "year",
    "geo_level",
    "geo_code",
    "geo_name",
    "measure",
    "value",
    "suppressed",
    "icd_codes",
    "intent",
    "age_group",
    "sex",
    "race",
    "notes",
    "fetched_at",
)

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

DATE_PRECISIONS = frozenset({"day", "month", "year"})

GEO_PRECISIONS = frozenset(
    {"exact", "beach", "place", "county", "state", "unknown"}
)

WATER_BODY_TYPES = frozenset(
    {
        "ocean",
        "great_lake",
        "inland_lake",
        "river",
        "pool",
        "bathtub",
        "quarry",
        "canal",
        "other",
        "unknown",
    }
)

HAZARDS = frozenset(
    {
        "rip_current",
        "high_surf",
        "sneaker_wave",
        "structural_current",
        "longshore_current",
        "flood",
        "vessel_capsize",
        "fall_overboard",
        "cold_water",
        "submersion_other",
        "unknown",
    }
)

ACTIVITIES = frozenset(
    {
        "swimming",
        "wading",
        "boating",
        "paddling",
        "fishing",
        "vehicle",
        "bathing",
        "unknown",
    }
)

# "intentional" is deliberately absent - see EXCLUDED_ICD_CODES.
INTENTS = frozenset({"unintentional", "undetermined", "other"})

SEXES = frozenset({"M", "F", "U"})

MEASURES = frozenset(
    {
        "deaths",
        "crude_rate",
        "age_adjusted_rate",
        "ed_visits",
        "registered_vessels",
    }
)

#: ICD-10 codes for intentional drowning. Never ingested. If a suicide-method
#: breakdown is ever wanted it needs its own gated page with crisis resources -
#: it is not a filter chip on a public map.
EXCLUDED_ICD_CODES = frozenset({"X71", "X92"})

#: Age bands used by the dashboard filters and by the CDC WONDER age grouping.
AGE_BANDS: tuple[tuple[str, int, int], ...] = (
    ("0-4", 0, 4),
    ("5-14", 5, 14),
    ("15-24", 15, 24),
    ("25-44", 25, 44),
    ("45-64", 45, 64),
    ("65+", 65, 200),
)

#: Precedence when the same death shows up in several sources. Earlier wins.
SOURCE_PRECEDENCE: tuple[str, ...] = (
    "nws_surf_zone",
    "ncei_storm_events",
    "mi_seagrant",
    "uscg_bard",
    "glsrp",
)

STATE_CODES = frozenset(
    """AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN
    MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV
    WI WY PR VI GU AS MP""".split()
)

STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
    "virgin islands": "VI", "guam": "GU", "american samoa": "AS",
    "northern mariana islands": "MP",
    # Aliases publishers actually use for the territories. NWS writes "ASM"
    # for American Samoa and names the individual USVI islands rather than the
    # territory, and without these those rows get dropped for having no
    # resolvable state - a silent undercount in exactly the places already
    # least well covered.
    "asm": "AS", "as": "AS", "amer samoa": "AS", "amer. samoa": "AS",
    "usvi": "VI", "u s virgin islands": "VI", "us virgin islands": "VI",
    "st croix": "VI", "st. croix": "VI", "saint croix": "VI",
    "st thomas": "VI", "st. thomas": "VI", "saint thomas": "VI",
    "st john": "VI", "st. john": "VI", "saint john": "VI",
    "gum": "GU", "saipan": "MP", "cnmi": "MP",
    "puerto rico ": "PR", "pri": "PR",
    "washington dc": "DC", "washington, d.c.": "DC", "d.c.": "DC",
}

GREAT_LAKES = ("lake michigan", "lake superior", "lake huron", "lake erie",
               "lake ontario", "lake st. clair", "lake st clair")

#: Rough bounding boxes (lat_min, lat_max, lon_min, lon_max), deliberately
#: generous - a false positive here just means a shoreline point near a lake
#: gets correctly called a Great Lake, not that an inland lake far away does.
GREAT_LAKES_BOUNDS: tuple[tuple[str, float, float, float, float], ...] = (
    ("Superior", 46.4, 49.0, -92.3, -84.3),
    ("Michigan", 41.6, 46.1, -88.0, -84.7),
    ("Huron", 43.0, 46.4, -84.8, -79.8),
    ("Erie", 41.3, 42.9, -83.5, -78.8),
    ("Ontario", 43.1, 44.3, -79.8, -76.1),
)

#: A real User-Agent with a contact URL, used by every scraping source here.
#: Sites that rate-limit or block deserve to know who is knocking.
USER_AGENT = (
    "cdata-drowning/0.1 (+https://github.com/kenEldridge/cdata; "
    "water-safety research; contact via repository issues)"
)


# ---------------------------------------------------------------------------
# Field-level normalizers
# ---------------------------------------------------------------------------

_AGE_INT_RE = re.compile(r"^\s*(\d{1,3})\s*$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")

_PLACE_STOPWORDS = frozenset({"the", "at", "near", "of", "on", "and"})

# Patterns that would identify a person. Narratives carrying any of these are
# dropped wholesale rather than partially redacted - a half-redacted narrative
# is still a re-identification risk.
_IDENTIFIER_PATTERNS = (
    re.compile(r"https?://", re.I),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    re.compile(r"\b(?:mr|mrs|ms|miss|dr)\.?\s+[A-Z][a-z]+", re.I),
    re.compile(r"\b(?:named|identified as|victim was)\b", re.I),
    re.compile(r"\b\d{1,4}\s+[A-Z][a-z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive)\b"),
)


def normalize_state(value: Any) -> Optional[str]:
    """Coerce a state name or abbreviation to a 2-letter USPS code."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if upper in STATE_CODES:
        return upper
    return STATE_NAMES.get(text.lower().strip("."))


def parse_age(value: Any) -> tuple[Optional[int], Optional[str]]:
    """Split a dirty age cell into ``(age, age_text)``.

    Source cells look like ``"22"``, ``"~22"``, ``"Late 20s"``, ``"unk"``.
    ``age`` is populated only for a clean integer in a plausible range; the
    original text is always preserved verbatim in ``age_text``. Nothing is
    guessed - ``"Late 20s"`` does not become 27.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    match = _AGE_INT_RE.match(text)
    if match:
        age = int(match.group(1))
        if 0 <= age <= 120:
            return age, text
    return None, text


def age_band(age: Optional[int]) -> str:
    """Map an age to a dashboard age band, or ``"unknown"``."""
    if age is None:
        return "unknown"
    for label, low, high in AGE_BANDS:
        if low <= age <= high:
            return label
    return "unknown"


def normalize_sex(value: Any) -> str:
    """Coerce a sex cell to one of :data:`SEXES` (``M`` / ``F`` / ``U``)."""
    if value is None:
        return "U"
    text = str(value).strip().upper()
    if text.startswith("M"):
        return "M"
    if text.startswith("F"):
        return "F"
    candidate = text[:1]
    return candidate if candidate in SEXES else "U"


def classify_water_body(name: Optional[str], place_name: Optional[str] = None) -> str:
    """Best-effort water body classification from free text.

    Returns ``"unknown"`` rather than guessing when nothing matches - an
    unknown is honest, a wrong bucket silently corrupts every chart.
    """
    blob = " ".join(p for p in (name, place_name) if p).lower()
    if not blob:
        return "unknown"
    if any(lake in blob for lake in GREAT_LAKES):
        return "great_lake"
    for needle, kind in (
        ("ocean", "ocean"),
        ("atlantic", "ocean"),
        ("pacific", "ocean"),
        ("gulf", "ocean"),
        ("beach", "ocean"),
        ("sea", "ocean"),
        ("river", "river"),
        ("creek", "river"),
        ("bayou", "river"),
        ("canal", "canal"),
        ("quarry", "quarry"),
        ("pool", "pool"),
        ("bathtub", "bathtub"),
        ("reservoir", "inland_lake"),
        ("pond", "inland_lake"),
        ("lake", "inland_lake"),
    ):
        if needle in blob:
            return kind
    return "unknown"


def reclassify_great_lakes_by_coords(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix ``water_body_type`` for rows sitting on a Great Lake shoreline
    that :func:`classify_water_body` couldn't tell from free text alone.

    NWS forecast-zone names like "ASHTABULA LAKESHORE" or a specific place
    like "Whiting Lakefront Park" don't literally say "Lake Erie"/"Lake
    Michigan", so the text classifier falls back to the generic "lake"
    match (``inland_lake``) or gives up (``unknown``). Coordinates - once a
    row has them, which for most sources is only after geocoding - settle
    it unambiguously. Never overrides a confident non-lake classification
    (ocean, river, pool, ...); only touches the ambiguous buckets.
    """
    for row in rows:
        if row.get("water_body_type") not in ("inland_lake", "unknown"):
            continue
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        for _, lat_min, lat_max, lon_min, lon_max in GREAT_LAKES_BOUNDS:
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                row["water_body_type"] = "great_lake"
                break
    return rows


def normalize_place(value: Any) -> str:
    """Normalize a place name for dedup matching (not for display)."""
    if value is None:
        return ""
    text = _NON_ALNUM_RE.sub(" ", str(value).lower())
    tokens = [t for t in _WS_RE.split(text) if t and t not in _PLACE_STOPWORDS]
    return " ".join(tokens)


def redact_narrative(text: Any) -> Optional[str]:
    """Return a narrative only if it carries no personal identifiers.

    Deliberately blunt: a narrative that trips any identifier pattern is
    dropped entirely rather than partially scrubbed. Losing a note costs
    nothing; leaking one costs a person's privacy.
    """
    if text is None:
        return None
    value = str(text).strip()
    if not value:
        return None
    for pattern in _IDENTIFIER_PATTERNS:
        if pattern.search(value):
            return None
    return value


def is_excluded_icd(codes: Any) -> bool:
    """True if an ICD code string touches an intentional-drowning code."""
    if not codes:
        return False
    text = str(codes).upper()
    return any(code in text for code in EXCLUDED_ICD_CODES)


def _iso_date(value: Any) -> Optional[str]:
    """Coerce a date-ish value to an ISO ``YYYY-MM-DD`` string."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%y", "%d-%b-%Y",
                "%Y%m%d", "%m/%d", "%b %d %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_incident_date(value: Any, year_hint: Optional[int] = None) -> tuple[Optional[str], str]:
    """Parse a source date cell into ``(iso_date, date_precision)``.

    ``year_hint`` fills the year for sources whose tables print ``"7/14"``
    under a year heading. Precision degrades honestly: a row that only gives a
    year comes back as ``("2024-01-01", "year")`` so it still charts by year
    without pretending to a day.
    """
    if value is None or str(value).strip() == "":
        if year_hint:
            return f"{year_hint:04d}-01-01", "year"
        return None, "year"

    text = str(value).strip()

    # Bare "M/D" or "M-D" with a year supplied by the page heading.
    bare = re.match(r"^(\d{1,2})[/-](\d{1,2})$", text)
    if bare and year_hint:
        month, day = int(bare.group(1)), int(bare.group(2))
        try:
            return date(year_hint, month, day).isoformat(), "day"
        except ValueError:
            return f"{year_hint:04d}-01-01", "year"

    iso = _iso_date(text)
    if iso:
        return iso, "day"

    # "July 2024" / "2024-07" -> month precision.
    month_only = re.match(r"^(\d{4})[-/](\d{1,2})$", text)
    if month_only:
        return f"{int(month_only.group(1)):04d}-{int(month_only.group(2)):02d}-01", "month"

    year_only = re.match(r"^(\d{4})$", text)
    if year_only:
        return f"{int(year_only.group(1)):04d}-01-01", "year"

    if year_hint:
        return f"{year_hint:04d}-01-01", "year"
    return None, "year"


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------


def make_incident_id(source_id: str, natural_key: str) -> str:
    """Stable deterministic incident id: ``source_id:sha1(natural_key)[:16]``.

    Hashing the natural key keeps ids a fixed width and keeps free-text place
    names (which can be long and messy) out of the id itself.
    """
    digest = hashlib.sha1(natural_key.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}"


def make_stat_id(source_id: str, year: int, geo_code: str, measure: str,
                 strata: dict[str, Any]) -> str:
    """Stable deterministic stat id including a hash of the strata."""
    payload = json.dumps(strata, sort_keys=True, default=str)
    strata_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{source_id}:{year}:{geo_code}:{measure}:{strata_hash}"


def sanitize_incident(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row onto the canonical incident allowlist.

    Every canonical key is present in the output (missing ones become ``None``)
    and every non-canonical key is dropped. This is the enforcement point for
    "no victim identification": a source that grows a ``victim_name`` column
    cannot push it past this function.
    """
    return {field: row.get(field) for field in INCIDENT_FIELDS}


def sanitize_stat(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row onto the canonical stat allowlist."""
    return {field: row.get(field) for field in STAT_FIELDS}


def build_incident(
    *,
    source_id: str,
    source_url: str,
    natural_key: str,
    date_value: Any = None,
    date_precision: str = "day",
    state: Any = None,
    county_fips: Optional[str] = None,
    place_name: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    geo_precision: str = "unknown",
    water_body_type: Optional[str] = None,
    water_body_name: Optional[str] = None,
    hazard: str = "unknown",
    activity: str = "unknown",
    intent: str = "unintentional",
    age: Any = None,
    age_text: Optional[str] = None,
    sex: Any = "U",
    fatal: bool = True,
    notes: Any = None,
    fetched_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build one canonical ``drowning_incidents`` row.

    Callers pass source-shaped values; this normalizes and validates them, so
    a source class never hand-assembles a canonical dict.
    """
    if intent not in INTENTS:
        # Anything outside the vocabulary (including an "intentional" row that
        # slipped through a source filter) is not silently coerced.
        raise ValueError(f"intent {intent!r} is not one of {sorted(INTENTS)}")

    parsed_age: Optional[int]
    if isinstance(age, int) or age is None:
        parsed_age, parsed_age_text = age, age_text
    else:
        parsed_age, parsed_age_text = parse_age(age)
        parsed_age_text = age_text or parsed_age_text

    iso_date = _iso_date(date_value)

    normalized_state = normalize_state(state)
    wb_type = water_body_type or classify_water_body(water_body_name, place_name)

    row = {
        "incident_id": make_incident_id(source_id, natural_key),
        "source_id": source_id,
        "source_url": source_url,
        "date": iso_date,
        "date_precision": date_precision if date_precision in DATE_PRECISIONS else "year",
        "state": normalized_state,
        "county_fips": county_fips,
        "place_name": (place_name or "").strip(),
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "geo_precision": geo_precision if geo_precision in GEO_PRECISIONS else "unknown",
        "water_body_type": wb_type if wb_type in WATER_BODY_TYPES else "unknown",
        "water_body_name": water_body_name,
        "hazard": hazard if hazard in HAZARDS else "unknown",
        "activity": activity if activity in ACTIVITIES else "unknown",
        "intent": intent,
        "age": parsed_age,
        "age_text": parsed_age_text,
        "age_band": age_band(parsed_age),
        "sex": normalize_sex(sex),
        "fatal": bool(fatal),
        "notes": redact_narrative(notes),
        "superseded_by": None,
        "fetched_at": (fetched_at or datetime.utcnow()).isoformat(),
    }
    return sanitize_incident(row)


def build_stat(
    *,
    source_id: str,
    source_url: str,
    year: int,
    geo_level: str,
    geo_code: str,
    geo_name: str,
    measure: str,
    value: Any = None,
    suppressed: bool = False,
    icd_codes: Optional[str] = None,
    intent: str = "unintentional",
    age_group: str = "All",
    sex: str = "All",
    race: Optional[str] = None,
    notes: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build one canonical ``drowning_stats`` row.

    A suppressed cell keeps ``value=None``. Callers must never substitute zero:
    "fewer than 10 deaths, count withheld" and "no deaths" are different facts.
    """
    if is_excluded_icd(icd_codes):
        raise ValueError(
            f"ICD codes {icd_codes!r} include an intentional-drowning code "
            f"({sorted(EXCLUDED_ICD_CODES)}); these are excluded by policy"
        )
    if measure not in MEASURES:
        raise ValueError(f"measure {measure!r} is not one of {sorted(MEASURES)}")

    numeric: Optional[float] = None
    if not suppressed and value is not None and value != "":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = None

    strata = {
        "intent": intent,
        "age_group": age_group,
        "sex": sex,
        "race": race,
        "icd_codes": icd_codes,
    }

    row = {
        "stat_id": make_stat_id(source_id, year, geo_code, measure, strata),
        "source_id": source_id,
        "source_url": source_url,
        "year": int(year),
        "geo_level": geo_level,
        "geo_code": geo_code,
        "geo_name": geo_name,
        "measure": measure,
        "value": numeric,
        "suppressed": bool(suppressed),
        "icd_codes": icd_codes,
        "intent": intent,
        "age_group": age_group,
        "sex": sex,
        "race": race,
        "notes": notes,
        "fetched_at": (fetched_at or datetime.utcnow()).isoformat(),
    }
    return sanitize_stat(row)


# ---------------------------------------------------------------------------
# Cross-source dedup
# ---------------------------------------------------------------------------


def _precedence_rank(source_id: str) -> int:
    try:
        return SOURCE_PRECEDENCE.index(source_id)
    except ValueError:
        return len(SOURCE_PRECEDENCE)


def _dedup_bucket(row: dict[str, Any]) -> tuple:
    """Coarse bucket key. Date is compared separately with a +/-1 day window."""
    age = row.get("age")
    age_bucket = age // 5 if isinstance(age, int) else None
    return (
        row.get("state"),
        row.get("sex"),
        age_bucket,
        normalize_place(row.get("place_name")),
    )


def _date_ordinal(row: dict[str, Any]) -> Optional[int]:
    iso = row.get("date")
    if not iso:
        return None
    try:
        return date.fromisoformat(str(iso)[:10]).toordinal()
    except ValueError:
        return None


def dedup_incidents(
    rows: Iterable[dict[str, Any]], date_tolerance_days: int = 1
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Mark cross-source duplicates in place and return ``(rows, report)``.

    Losing rows are kept, with ``superseded_by`` pointing at the winner, rather
    than deleted - provenance stays auditable and consumers filter them out at
    prepare time. Matching is on ``(date +/-1d, state, age/5, sex, place)`` with
    the precedence order in :data:`SOURCE_PRECEDENCE`.
    """
    all_rows = [dict(row) for row in rows]
    for row in all_rows:
        row["superseded_by"] = None

    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for row in all_rows:
        buckets.setdefault(_dedup_bucket(row), []).append(row)

    clusters = 0
    superseded = 0
    by_source: dict[str, int] = {}
    details: list[dict[str, Any]] = []

    for bucket_key, members in buckets.items():
        if len(members) < 2:
            continue

        # Cluster within the bucket by date proximity.
        undated = [r for r in members if _date_ordinal(r) is None]
        dated = sorted(
            (r for r in members if _date_ordinal(r) is not None),
            key=_date_ordinal,
        )

        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for row in dated:
            if current and _date_ordinal(row) - _date_ordinal(current[-1]) > date_tolerance_days:
                groups.append(current)
                current = []
            current.append(row)
        if current:
            groups.append(current)
        if len(undated) > 1:
            groups.append(undated)

        for group in groups:
            distinct_sources = {r["source_id"] for r in group}
            if len(group) < 2 or len(distinct_sources) < 2:
                # Two rows from the *same* source in the same place on the same
                # day are two different people, not a duplicate. Only
                # cross-source clusters are deduped.
                continue

            clusters += 1
            group.sort(key=lambda r: (_precedence_rank(r["source_id"]), r["incident_id"]))
            winner = group[0]
            for loser in group[1:]:
                loser["superseded_by"] = winner["incident_id"]
                superseded += 1
                by_source[loser["source_id"]] = by_source.get(loser["source_id"], 0) + 1
            details.append(
                {
                    "winner": winner["incident_id"],
                    "winner_source": winner["source_id"],
                    "date": winner.get("date"),
                    "state": bucket_key[0],
                    "place": winner.get("place_name"),
                    "superseded": [
                        {"incident_id": r["incident_id"], "source_id": r["source_id"]}
                        for r in group[1:]
                    ],
                }
            )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "rows_in": len(all_rows),
        "rows_surviving": len(all_rows) - superseded,
        "clusters": clusters,
        "superseded": superseded,
        "superseded_by_source": by_source,
        "date_tolerance_days": date_tolerance_days,
        "precedence": list(SOURCE_PRECEDENCE),
        "details": details,
    }
    return all_rows, report


def write_dedup_report(report: dict[str, Any], path: Optional[Path] = None) -> Path:
    """Write a dedup report to ``logs/`` (or a caller-supplied path)."""
    if path is None:
        from cdata.config.env import get_settings

        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        path = get_settings().logs_dir / f"drowning_dedup_{stamp}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


__all__ = [
    "INCIDENT_FIELDS",
    "STAT_FIELDS",
    "EXCLUDED_ICD_CODES",
    "SOURCE_PRECEDENCE",
    "USER_AGENT",
    "AGE_BANDS",
    "HAZARDS",
    "WATER_BODY_TYPES",
    "age_band",
    "build_incident",
    "build_stat",
    "classify_water_body",
    "reclassify_great_lakes_by_coords",
    "dedup_incidents",
    "is_excluded_icd",
    "make_incident_id",
    "make_stat_id",
    "normalize_place",
    "normalize_sex",
    "normalize_state",
    "parse_age",
    "parse_incident_date",
    "redact_narrative",
    "sanitize_incident",
    "sanitize_stat",
    "write_dedup_report",
]
