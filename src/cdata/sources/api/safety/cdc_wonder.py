"""CDC WONDER mortality source (Layer A, aggregate).

The national trend backbone: drowning deaths and rates by year, age group and
sex, from the Underlying Cause of Death files.

    POST https://wonder.cdc.gov/controller/datarequest/{DB_ID}
    form fields: request_xml=<xml>, accept_datause_restrictions=true

No auth. Three things constrain this source and are enforced here:

* **Sub-national queries are blocked over the API.** National only. State-level
  rates have to come from WISQARS or a manual WONDER UI export - asking this
  source for a state breakdown raises rather than silently returning national
  numbers labelled as state ones.
* **Rate limit: 15 seconds between requests.** WONDER states this itself in the
  HTTP 429 body: "API/XML requests must have at least 15 seconds between
  consecutive requests." The default here is 20s for headroom. (Some
  documentation quotes one query per two minutes; the server's own message is
  the number trusted here.) The data changes annually, so the caller should
  still cache - see the-derple-dex's ``scripts/fetch_cache.py``.
* **Suppressed cells are data.** WONDER returns ``Suppressed`` / ``Unreliable``
  / ``Not Applicable`` for small cells. Those become ``value=None,
  suppressed=True`` - never zero, never interpolated.

Intentional drowning (``X71``, ``X92``) is never queried.

.. note::

   **Verified against a live query on 2026-09-10.** The original template
   sent only ~10 fields and returned HTTP 500 with contradictory-looking
   errors. The actual cause: WONDER's server expects the *entire* form
   state - every dimension's ``O_``/``V_``/``F_``/``I_``/``finder-stage``
   quad, even when every one of them is just ``*All*`` - not just the
   fields that vary per query. The three-bug theory this docstring used to
   describe (``V_D76.Vx``/``O_ucd``/``I_``-vs-``F_`` conflicts) was a red
   herring; ``I_*`` fields are just display-only echo text, not toggles.

   The correct field values only exist once WONDER's client-side JS runs
   the Finder controls (confirmed by CDC's own API help page, which tells
   API users to build the query in the web UI and use its "API Options"
   button - there is no way to derive them from a static page fetch). The
   fixture below was built by driving the real form in a headless browser,
   capturing the exact POST it sent, and confirming the equivalent
   ``request_xml`` round-trips through this stateless API. A year-grouped,
   ``W65-W74``, ``D158`` query for 2019 returned 3,692 deaths at a crude
   rate of 1.1 per 100,000 - matches published NCHS figures.
"""

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

import httpx

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource
from cdata.transforms.drowning import (
    EXCLUDED_ICD_CODES,
    USER_AGENT,
    build_stat,
    is_excluded_icd,
)

WONDER_URL = "https://wonder.cdc.gov/controller/datarequest/{db_id}"
WONDER_HELP_URL = "https://wonder.cdc.gov/wonder/help/wonder-api.html"

TEMPLATE_PATH = Path(__file__).parent / "fixtures" / "wonder_ucd_template.xml"

#: Database ids. D76 is the settled 1999-2020 file; D158 is 2018-present
#: (single race). Confirm against WONDER_HELP_URL before trusting a new one.
DATABASE_YEARS = {
    "D76": (1999, 2020),
    "D158": (2018, datetime.utcnow().year - 1),
    "D176": (2018, datetime.utcnow().year),
}

#: Cosmetic dataset_code/dataset_label/dataset_vintage fields WONDER's form
#: sends alongside every request. Not validated server-side (confirmed by
#: live probing), but included since they're part of the real payload.
DATABASE_LABELS = {
    "D76": "Underlying Cause of Death, 1999-2020",
    "D158": "Underlying Cause of Death, 2018-2024, Single Race",
    "D176": "Underlying Cause of Death, 2018-2024, Single Race",
}

#: Group-by field numbers, keyed the same across the UCD-family databases
#: (confirmed for D76 and D158 by live probing). "year" is the one
#: multi-level field (Year/Month) and needs a "-level1" suffix to mean
#: "Year"; age_group/sex/race are single-level and take the bare code.
_GROUP_BY_FIELD_NUMBERS = {
    "year": ("V1", "-level1"),
    "age_group": ("V5", ""),
    "sex": ("V7", ""),
    "race": ("V8", ""),
}


def _group_by_code(db_id: str, field: str) -> str:
    number, suffix = _GROUP_BY_FIELD_NUMBERS[field]
    return f"{db_id}.{number}{suffix}"

#: Cell values WONDER uses in place of a number.
SUPPRESSION_MARKERS = frozenset(
    {"suppressed", "unreliable", "not applicable", "missing", "na", ""}
)

#: Code points ICD-10 never assigned, that a naive numeric range expansion
#: would otherwise invent. Verified live against WONDER, which rejects them
#: outright: "Invalid 'ICD-10 Codes' codes were found: 'W71, W72'". The
#: W65-W74 drowning block genuinely skips these two - not a typo to "fix".
NONEXISTENT_ICD_CODES = frozenset({"W71", "W72"})

#: ICD code prefix -> intent. Codes are queried one intent group at a time so
#: that undetermined-intent drownings (Y21) never get folded into the
#: unintentional headline number.
ICD_INTENTS = {
    "W65": "unintentional", "W66": "unintentional", "W67": "unintentional",
    "W68": "unintentional", "W69": "unintentional", "W70": "unintentional",
    "W73": "unintentional", "W74": "unintentional",
    "V90": "unintentional", "V92": "unintentional",
    "Y21": "undetermined",
}


def group_codes_by_intent(codes: list[str]) -> dict[str, list[str]]:
    """Bucket expanded ICD codes by the intent they represent."""
    groups: dict[str, list[str]] = {}
    for code in codes:
        intent = ICD_INTENTS.get(code, "other")
        groups.setdefault(intent, []).append(code)
    return groups


_NUMERIC_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


class CDCWonderSource(BaseSource):
    """CDC WONDER Underlying Cause of Death source.

    Config keys:
        databases: WONDER database ids to query, in order (default ["D158", "D76"])
        icd_codes: ICD-10 codes/ranges to request
        groupings: list of group-by combinations, each up to three of
            year / age_group / sex / race. One query is issued per
            (database, intent group, grouping). The default runs a
            ``["year"]`` pass, which is the only way to get a true national
            total - WONDER emits no totals row when you group by age or sex,
            and age-adjusted rates cannot be summed back up from strata.
        group_by: single-grouping alias for ``groupings``
        min_seconds_between_requests: rate-limit floor (default 20; WONDER
            itself asks for at least 15 seconds between requests)
        start_year / end_year: year window (defaults to each database's range)

    Cost: a cold fetch is ``databases x intent groups x groupings`` queries,
    each 20 seconds apart - about three minutes with the defaults. Still too
    slow to sit in every build, which is why the-derple-dex caches the result
    for 90 days and commits the cache.
    """

    source_type = "cdc_wonder"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._headers = {"User-Agent": USER_AGENT}
        self._last_request = 0.0

    # -- request building -------------------------------------------------

    @staticmethod
    def _expand_icd(codes: list[str]) -> list[str]:
        """Expand ``"W65-W74"`` into the individual codes WONDER expects.

        WONDER's own value list is per-code, so a range has to be spelled out.
        Any expansion that lands on an excluded intentional-drowning code, or
        on a code ICD-10 never assigned within the range, is dropped - which
        is why a range is never passed through verbatim.
        """
        expanded: list[str] = []
        for code in codes:
            text = str(code).strip().upper()
            match = re.match(r"^([A-Z])(\d{2})\s*-\s*([A-Z])(\d{2})$", text)
            if match and match.group(1) == match.group(3):
                letter = match.group(1)
                for number in range(int(match.group(2)), int(match.group(4)) + 1):
                    expanded.append(f"{letter}{number:02d}")
            else:
                expanded.append(text)
        return [
            c for c in expanded
            if c not in EXCLUDED_ICD_CODES and c not in NONEXISTENT_ICD_CODES
        ]

    def _build_request_xml(
        self, db_id: str, icd_codes: list[str], years: list[int], group_by: list[str]
    ) -> str:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")

        slots = [_group_by_code(db_id, g) for g in group_by]
        while len(slots) < 3:
            slots.append("*None*")

        icd_block = "\n".join(f"    <value>{code}</value>" for code in icd_codes)
        year_block = "\n".join(f"    <value>{year}</value>" for year in years)
        icd_label = ",".join(icd_codes) if icd_codes else "*All*"
        year_label = ",".join(str(y) for y in years) if years else "*All*"

        return (
            template.replace("{{DB}}", db_id)
            .replace("{{DATASET_LABEL}}", DATABASE_LABELS.get(db_id, db_id))
            .replace("{{DATASET_VINTAGE}}", str(DATABASE_YEARS.get(db_id, (0, 0))[1]))
            .replace("{{GROUP_BY_1}}", slots[0])
            .replace("{{GROUP_BY_2}}", slots[1])
            .replace("{{GROUP_BY_3}}", slots[2])
            .replace("{{ICD_CODES}}", icd_block)
            .replace("{{ICD_LABEL}}", icd_label)
            .replace("{{YEAR_VALUES}}", year_block)
            .replace("{{YEAR_LABEL}}", year_label)
        )

    def _throttle(self, min_seconds: float) -> None:
        """Sleep so consecutive WONDER queries stay ``min_seconds`` apart.

        The first request of a run does not wait; every one after it does,
        whether or not the previous one succeeded.
        """
        if self._last_request:
            elapsed = time.monotonic() - self._last_request
            if elapsed < min_seconds:
                time.sleep(min_seconds - elapsed)
        self._last_request = time.monotonic()

    # -- response parsing -------------------------------------------------

    @staticmethod
    def _parse_cell(text: Optional[str]) -> tuple[Optional[float], bool]:
        """Return ``(value, suppressed)`` for one WONDER data cell."""
        value = (text or "").strip()
        if value.lower() in SUPPRESSION_MARKERS:
            return None, True
        if _NUMERIC_RE.match(value):
            return float(value.replace(",", "")), False
        return None, True

    def parse_response(
        self,
        xml_text: str,
        group_by: list[str],
        icd_label: str,
        intent: str,
        source_url: str,
        started_at: datetime,
    ) -> list[dict[str, Any]]:
        """Turn a WONDER XML response into canonical ``drowning_stats`` rows.

        Results live under ``data-table`` as ``<r>`` rows of ``<c>`` cells: the
        leading cells are the group-by labels (carried in each cell's ``l``
        attribute) and the trailing ones are the measures (``v``).
        """
        root = ElementTree.fromstring(xml_text)
        table = root.find(".//data-table")
        if table is None:
            return []

        measures = ["deaths", "population", "crude_rate", "age_adjusted_rate"]
        rows: list[dict[str, Any]] = []
        carried: list[str] = [""] * len(group_by)

        for row_element in table.findall("r"):
            cells = row_element.findall("c")
            labels: list[str] = []
            values: list[str] = []
            for cell in cells:
                label = cell.get("l")
                if label is not None and len(labels) < len(group_by):
                    labels.append(label)
                else:
                    values.append(cell.get("v", ""))

            # WONDER omits repeated group-by labels on continuation rows.
            for position in range(len(group_by)):
                if position < len(labels) and labels[position]:
                    carried[position] = labels[position]
            strata = dict(zip(group_by, carried))

            year_text = strata.get("year", "")
            if not re.match(r"^\d{4}$", year_text.strip()):
                continue
            year = int(year_text)

            for position, measure in enumerate(measures):
                if position >= len(values):
                    break
                if measure == "population":
                    continue  # denominator, not a published measure of ours
                value, suppressed = self._parse_cell(values[position])
                rows.append(
                    build_stat(
                        source_id=self.source_id,
                        source_url=source_url,
                        year=year,
                        geo_level="national",
                        geo_code="US",
                        geo_name="United States",
                        measure=measure,
                        value=value,
                        suppressed=suppressed,
                        icd_codes=icd_label,
                        intent=intent,
                        age_group=strata.get("age_group") or "All",
                        sex=strata.get("sex") or "All",
                        race=strata.get("race"),
                        fetched_at=started_at,
                    )
                )
        return rows

    # -- BaseSource -------------------------------------------------------

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch national drowning mortality as canonical aggregate records."""
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        databases = list(kwargs.get("databases") or ["D158", "D76"])
        raw_icd = list(kwargs.get("icd_codes") or ["W65-W74", "V90", "V92", "Y21"])
        min_seconds = float(kwargs.get("min_seconds_between_requests", 20))

        groupings = kwargs.get("groupings")
        if not groupings:
            single = kwargs.get("group_by")
            groupings = [list(single)] if single else [["year"], ["year", "age_group"]]

        for grouping in groupings:
            if any(g not in _GROUP_BY_FIELD_NUMBERS for g in grouping):
                return self._create_result(
                    records, started_at,
                    error=(
                        f"grouping {grouping} includes a field WONDER's API "
                        f"cannot group on. Sub-national (state/county) grouping "
                        f"is blocked over the API; use WISQARS for state rates."
                    ),
                )
            if "year" not in grouping:
                return self._create_result(
                    records, started_at,
                    error=f"grouping {grouping} must include 'year'",
                )

        for code in raw_icd:
            if is_excluded_icd(code):
                return self._create_result(
                    records, started_at,
                    error=(
                        f"icd_codes includes an intentional-drowning code "
                        f"({sorted(EXCLUDED_ICD_CODES)}); these are excluded by policy"
                    ),
                )

        icd_codes = self._expand_icd(raw_icd)
        if not icd_codes:
            return self._create_result(
                records, started_at, error="No usable ICD codes after exclusions"
            )
        intent_groups = group_codes_by_intent(icd_codes)

        queries_made = 0
        seen_stat_ids: set[str] = set()

        with httpx.Client(
            timeout=300, follow_redirects=True, headers=self._headers
        ) as client:
            for db_id in databases:
                db_start, db_end = DATABASE_YEARS.get(db_id, (1999, datetime.utcnow().year))
                start_year = int(kwargs.get("start_year", db_start))
                end_year = int(kwargs.get("end_year", db_end))
                years = list(range(max(start_year, db_start), min(end_year, db_end) + 1))
                if not years:
                    continue

                url = WONDER_URL.format(db_id=db_id)

                # One query per intent group per grouping. Folding Y21
                # (undetermined) into the W65-W74 total would misstate the
                # headline number, and a grouped query returns no totals row -
                # hence the separate ["year"] pass.
                for intent, group_codes in sorted(intent_groups.items()):
                    icd_label = ",".join(group_codes)

                    for grouping in groupings:
                        request_xml = self._build_request_xml(
                            db_id, group_codes, years, grouping
                        )

                        # Throttle on requests *sent*, not on requests that
                        # succeeded: a failed query still counts against
                        # WONDER's rate limit, and keying off success turns one
                        # error into a cascade of 429s.
                        self._throttle(min_seconds)
                        try:
                            response = client.post(
                                url,
                                data={
                                    "request_xml": request_xml,
                                    "accept_datause_restrictions": "true",
                                },
                            )
                            response.raise_for_status()
                            queries_made += 1
                            parsed = self.parse_response(
                                response.text, grouping, icd_label, intent,
                                url, started_at,
                            )
                        except Exception as exc:
                            errors.append(f"{db_id}/{intent}/{grouping}: {exc}")
                            continue

                        if not parsed:
                            errors.append(
                                f"{db_id}/{intent}/{grouping}: response "
                                f"contained no data-table rows"
                            )
                            continue

                        for stat in parsed:
                            # Databases overlap (D158 begins before D76 ends);
                            # the first database queried wins for a duplicate.
                            if stat["stat_id"] in seen_stat_ids:
                                continue
                            seen_stat_ids.add(stat["stat_id"])
                            records.append(
                                self._create_record(
                                    data=stat,
                                    metadata={"layer": "stats", "database": db_id},
                                )
                            )

        return self._create_result(
            records,
            started_at,
            error="; ".join(errors) if errors else None,
            metadata={
                "databases_queried": databases,
                "groupings": [list(g) for g in groupings],
                "queries_made": queries_made,
                "icd_codes_expanded": icd_codes,
                "excluded_icd_codes": sorted(EXCLUDED_ICD_CODES),
                "api_documentation": WONDER_HELP_URL,
                "caveat": (
                    "National totals only - CDC WONDER's API blocks state and "
                    "county queries. Small cells are suppressed by CDC and are "
                    "reported as suppressed, not as zero."
                ),
            },
        )

    def test_connection(self) -> bool:
        """Cheapest real request: GET the WONDER API help page.

        A single-cell data query would be a truer test, but it burns one of the
        one-per-two-minutes budget every time anyone runs ``cdata sources test``.
        """
        try:
            with httpx.Client(
                timeout=20, follow_redirects=True, headers=self._headers
            ) as client:
                response = client.get(WONDER_HELP_URL)
                return response.status_code == 200
        except Exception:
            return False
