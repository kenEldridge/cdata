"""Place-name geocoding for incident sources, with a file-backed cache.

Resolution order, cheapest first:

1. The source already carries coordinates -> pass through, ``exact``.
2. A local USGS GNIS gazetteer (offline, free, no rate limit) -> ``beach`` /
   ``place`` depending on the matched feature class.
3. Nominatim, at 1 request/second with a real User-Agent -> ``place``.
4. Unresolved -> ``lat``/``lon`` stay ``None`` and precision drops to
   ``state``.

Rule 4 matters: a row is **never dropped** because it will not geocode, and an
unresolved row is **never** placed at a state centroid as though that were the
incident location. The dashboard renders those as an "unmapped" count instead.

The cache is a plain JSON file under ``data/cache/geocode.json``, keyed by
``sha1(place_name|state)``, and is meant to be committed so CI and other
machines do not re-geocode.
"""

import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from cdata.transforms.drowning import USER_AGENT, normalize_state

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: GNIS feature classes worth indexing for water-incident place names.
GNIS_FEATURE_CLASSES = frozenset(
    {"Beach", "Lake", "Stream", "Reservoir", "Bay", "Channel", "Park",
     "Rapids", "Falls", "Canal", "Harbor", "Island", "Populated Place"}
)

#: Feature classes that imply a beach-level (rather than town-level) fix.
_BEACH_CLASSES = frozenset({"Beach", "Bay", "Channel", "Harbor"})

_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")
_NOISE_TOKENS = frozenset(
    {"beach", "park", "pier", "state", "county", "area", "the", "at", "near",
     "north", "south", "east", "west", "n", "s", "e", "w"}
)


def cache_key(place_name: str, state: Optional[str]) -> str:
    """Stable cache key: ``sha1("place|ST")``."""
    return hashlib.sha1(f"{place_name}|{state or ''}".encode()).hexdigest()


def normalize_for_gazetteer(name: str) -> str:
    """Normalize a place name for gazetteer lookup."""
    text = _NON_ALNUM_RE.sub(" ", (name or "").lower())
    return _WS_RE.sub(" ", text).strip()


def _loosen(name: str) -> str:
    """Drop generic tokens so ``"North Cocoa Beach Park"`` matches ``"Cocoa"``."""
    tokens = [t for t in normalize_for_gazetteer(name).split(" ")
              if t and t not in _NOISE_TOKENS]
    return " ".join(tokens)


class Geocoder:
    """Gazetteer-first geocoder with a JSON cache and a Nominatim fallback.

    Args:
        cache_path: JSON cache file. Defaults to ``<data_dir>/cache/geocode.json``.
        gnis_dir: Directory holding USGS GNIS Domestic Names ``.txt``/``.csv``
            files. Defaults to ``<data_dir>/reference/gnis``. Missing is fine -
            the gazetteer is simply skipped.
        use_nominatim: Whether the network fallback is allowed at all. Set
            ``False`` in tests and in CI runs that must stay offline.
        min_seconds_between_requests: Nominatim's usage policy is 1 req/sec.
        max_nominatim_requests: Per-run budget for network lookups. At 1
            req/sec an uncached first run would stall a build for minutes, so
            the budget lets the committed cache fill over several runs instead.
            ``None`` means unlimited.
    """

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        gnis_dir: Optional[Path] = None,
        use_nominatim: bool = True,
        min_seconds_between_requests: float = 1.0,
        max_nominatim_requests: Optional[int] = None,
    ):
        from cdata.config.env import get_settings

        settings = get_settings()
        self.cache_path = Path(cache_path or settings.cache_dir / "geocode.json")
        self.gnis_dir = Path(gnis_dir or settings.data_dir / "reference" / "gnis")
        self.use_nominatim = use_nominatim
        self.min_seconds_between_requests = min_seconds_between_requests
        self.max_nominatim_requests = max_nominatim_requests
        self._nominatim_requests = 0
        self._deferred = False

        self._cache: dict[str, Any] = self._load_cache()
        self._gazetteer: Optional[dict[tuple[str, str], dict[str, Any]]] = None
        self._last_request = 0.0
        self.stats = {"lookups": 0, "resolved": 0, "cache_hits": 0,
                      "gazetteer_hits": 0, "nominatim_hits": 0, "unresolved": 0}

    # -- cache ------------------------------------------------------------

    def _load_cache(self) -> dict[str, Any]:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save_cache(self) -> None:
        """Persist the cache. Callers should invoke this once per run."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, indent=1, sort_keys=True), encoding="utf-8"
        )

    # -- gazetteer --------------------------------------------------------

    def _load_gazetteer(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Index the local GNIS files by ``(normalized_name, state)``.

        GNIS Domestic Names files are pipe-delimited with a header row. The
        columns have been renamed across releases, so lookups are by header
        name with a couple of known aliases rather than by position.
        """
        if self._gazetteer is not None:
            return self._gazetteer

        index: dict[tuple[str, str], dict[str, Any]] = {}
        if not self.gnis_dir.is_dir():
            self._gazetteer = index
            return index

        name_keys = ("feature_name", "FEATURE_NAME")
        class_keys = ("feature_class", "FEATURE_CLASS")
        # The current National File ships "state_name" (full name, e.g.
        # "Florida") - "state_alpha" doesn't exist in it. Older/topical
        # extracts have used the abbreviation under either name, so both
        # are kept and run through normalize_state() either way.
        state_keys = ("state_alpha", "STATE_ALPHA", "state_name", "STATE_NAME")
        lat_keys = ("prim_lat_dec", "PRIM_LAT_DEC")
        lon_keys = ("prim_long_dec", "PRIM_LONG_DEC")

        def pick(row: dict[str, str], keys: tuple[str, ...]) -> str:
            for key in keys:
                if row.get(key):
                    return row[key]
            return ""

        for path in sorted(self.gnis_dir.glob("*")):
            if path.suffix.lower() not in (".txt", ".csv", ".psv"):
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    reader = csv.DictReader(handle, delimiter="|")
                    for row in reader:
                        feature_class = pick(row, class_keys)
                        if feature_class not in GNIS_FEATURE_CLASSES:
                            continue
                        state = normalize_state(pick(row, state_keys)) or ""
                        name = pick(row, name_keys)
                        try:
                            lat = float(pick(row, lat_keys))
                            lon = float(pick(row, lon_keys))
                        except ValueError:
                            continue
                        if not name or not state:
                            continue
                        entry = {
                            "lat": lat,
                            "lon": lon,
                            "feature_class": feature_class,
                            "matched_name": name,
                        }
                        index.setdefault((normalize_for_gazetteer(name), state), entry)
                        loose = _loosen(name)
                        if loose:
                            index.setdefault((loose, state), entry)
            except OSError:
                continue

        self._gazetteer = index
        return index

    def _gazetteer_lookup(self, place_name: str, state: str) -> Optional[dict[str, Any]]:
        index = self._load_gazetteer()
        if not index:
            return None
        for candidate in (normalize_for_gazetteer(place_name), _loosen(place_name)):
            if not candidate:
                continue
            hit = index.get((candidate, state))
            if hit:
                precision = "beach" if hit["feature_class"] in _BEACH_CLASSES else "place"
                return {"lat": hit["lat"], "lon": hit["lon"],
                        "geo_precision": precision, "provider": "gnis"}
        return None

    # -- nominatim --------------------------------------------------------

    def _nominatim_lookup(self, place_name: str, state: str) -> Optional[dict[str, Any]]:
        if not self.use_nominatim:
            return None
        if (
            self.max_nominatim_requests is not None
            and self._nominatim_requests >= self.max_nominatim_requests
        ):
            # Deferred, not unresolvable - do not poison the cache with a
            # negative result that would stop it ever being retried.
            self._deferred = True
            self.stats["deferred"] = self.stats.get("deferred", 0) + 1
            return None
        self._nominatim_requests += 1

        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_seconds_between_requests:
            time.sleep(self.min_seconds_between_requests - elapsed)
        self._last_request = time.monotonic()

        try:
            response = httpx.get(
                NOMINATIM_URL,
                params={
                    "q": f"{place_name}, {state}, USA",
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None

        if not payload:
            return None
        try:
            return {
                "lat": float(payload[0]["lat"]),
                "lon": float(payload[0]["lon"]),
                "geo_precision": "place",
                "provider": "nominatim",
            }
        except (KeyError, ValueError, TypeError):
            return None

    # -- public API -------------------------------------------------------

    def geocode(self, place_name: str, state: Any) -> Optional[dict[str, Any]]:
        """Resolve ``(place_name, state)``. Returns ``None`` if unresolved."""
        self.stats["lookups"] += 1
        state_code = normalize_state(state)
        if not place_name or not state_code:
            self.stats["unresolved"] += 1
            return None

        key = cache_key(place_name, state_code)
        if key in self._cache:
            self.stats["cache_hits"] += 1
            result = self._cache[key]
        else:
            self._deferred = False
            result = (
                self._gazetteer_lookup(place_name, state_code)
                or self._nominatim_lookup(place_name, state_code)
            )
            # Negative results are cached too, so a place that genuinely does
            # not resolve is not re-queried on every single build. A lookup
            # merely deferred by the per-run budget is left uncached so the
            # next run picks it up.
            if not self._deferred:
                self._cache[key] = result
            if result is not None:
                bucket = "gazetteer_hits" if result["provider"] == "gnis" else "nominatim_hits"
                self.stats[bucket] += 1

        if result is None:
            self.stats["unresolved"] += 1
        else:
            self.stats["resolved"] += 1
        return result

    def enrich(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fill ``lat``/``lon``/``geo_precision`` on canonical incident rows.

        Rows that already carry coordinates are left alone. Rows that cannot be
        resolved keep null coordinates and drop to ``state`` precision - they
        stay in the dataset and still count in every aggregate.
        """
        for row in rows:
            if row.get("lat") is not None and row.get("lon") is not None:
                continue
            hit = self.geocode(row.get("place_name", ""), row.get("state"))
            if hit:
                row["lat"] = hit["lat"]
                row["lon"] = hit["lon"]
                row["geo_precision"] = hit["geo_precision"]
            else:
                row["lat"] = None
                row["lon"] = None
                row["geo_precision"] = "state" if row.get("state") else "unknown"
        return rows

    def resolution_rate(self) -> float:
        """Share of lookups this run that produced coordinates."""
        if not self.stats["lookups"]:
            return 0.0
        return self.stats["resolved"] / self.stats["lookups"]


__all__ = ["Geocoder", "cache_key", "normalize_for_gazetteer",
           "GNIS_FEATURE_CLASSES"]
