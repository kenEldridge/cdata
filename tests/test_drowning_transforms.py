"""Tests for the drowning canonical schemas, source parsers and dedup.

These cover the parts that are cheap to get subtly wrong: dirty age cells,
the NWS "Other" legend, suppression handling, cross-source dedup precedence,
and - most importantly - the privacy constraints, which are asserted here so
that a future source cannot quietly widen what gets ingested.
"""

import gzip
import io
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from cdata.config.schema import SourceConfig
from cdata.core.registry import get_registry
from cdata.sources.api.safety.cdc_wonder import (
    CDCWonderSource,
    group_codes_by_intent,
)
from cdata.sources.api.safety.ncei_storm_events import (
    WATER_FATALITY_LOCATIONS,
    NCEIStormEventsSource,
)
from cdata.sources.api.safety.uscg_bard import USCGBardSource
from cdata.sources.api.safety.nws_surf_zone import (
    NWSSurfZoneSource,
    _parse_legend,
    _promote_header,
    _published_total,
)
from cdata.transforms.drowning import (
    EXCLUDED_ICD_CODES,
    INCIDENT_FIELDS,
    STAT_FIELDS,
    age_band,
    build_incident,
    build_stat,
    classify_water_body,
    dedup_incidents,
    is_excluded_icd,
    make_incident_id,
    normalize_place,
    normalize_sex,
    normalize_state,
    parse_age,
    parse_incident_date,
    reclassify_great_lakes_by_coords,
    redact_narrative,
    sanitize_incident,
)
from cdata.transforms.geocode import Geocoder, cache_key, normalize_for_gazetteer

FIXTURES = Path(__file__).parent / "fixtures" / "drowning"

NWS_CONFIG = SourceConfig(
    id="nws_surf_zone",
    name="NWS Surf Zone Fatalities",
    type="nws_surf_zone",
    config={"start_year": 2020},
    primary_keys=["incident_id"],
)

NCEI_CONFIG = SourceConfig(
    id="ncei_storm_events",
    name="NCEI Storm Events",
    type="ncei_storm_events",
    config={"start_year": 2024},
    primary_keys=["incident_id"],
)

WONDER_CONFIG = SourceConfig(
    id="cdc_wonder_drowning",
    name="CDC WONDER",
    type="cdc_wonder",
    config={"databases": ["D76"]},
    primary_keys=["stat_id"],
)


# ---------------------------------------------------------------------------
# Field normalizers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_age,expected_text",
    [
        ("22", 22, "22"),
        ("  7 ", 7, "7"),
        ("~22", None, "~22"),
        ("Late 20s", None, "Late 20s"),
        ("unk", None, "unk"),
        ("", None, None),
        (None, None, None),
        ("999", None, "999"),
    ],
)
def test_parse_age_never_guesses(raw, expected_age, expected_text):
    age, text = parse_age(raw)
    assert age == expected_age
    assert text == expected_text


@pytest.mark.parametrize(
    "age,expected",
    [(None, "unknown"), (0, "0-4"), (4, "0-4"), (5, "5-14"), (24, "15-24"),
     (25, "25-44"), (64, "45-64"), (65, "65+"), (101, "65+")],
)
def test_age_band(age, expected):
    assert age_band(age) == expected


def test_normalize_state_handles_names_codes_and_territories():
    assert normalize_state("Michigan") == "MI"
    assert normalize_state("mi") == "MI"
    assert normalize_state("Puerto Rico") == "PR"
    assert normalize_state("District of Columbia") == "DC"
    assert normalize_state("Narnia") is None
    assert normalize_state("") is None


def test_normalize_state_handles_the_territory_aliases_nws_actually_uses():
    # These appear verbatim in the live NWS tables. Without them the rows are
    # dropped for having no resolvable state, undercounting the territories.
    assert normalize_state("ASM") == "AS"
    assert normalize_state("St. Croix") == "VI"
    assert normalize_state("St Croix") == "VI"
    assert normalize_state("Saint Thomas") == "VI"


def test_normalize_sex_collapses_to_three_values():
    assert normalize_sex("Male") == "M"
    assert normalize_sex("f") == "F"
    assert normalize_sex("unknown") == "U"
    assert normalize_sex(None) == "U"


def test_classify_water_body_prefers_great_lakes_and_admits_ignorance():
    assert classify_water_body("Lake Michigan") == "great_lake"
    assert classify_water_body(None, "Cocoa Beach") == "ocean"
    assert classify_water_body("Colorado River") == "river"
    assert classify_water_body("Lake Wobegon") == "inland_lake"
    assert classify_water_body(None, "") == "unknown"
    assert classify_water_body("somewhere damp") == "unknown"


def test_reclassify_great_lakes_by_coords_settles_ambiguous_zone_names():
    # "ASHTABULA LAKESHORE" is an NWS zone name that never says "Erie" -
    # classify_water_body alone can't know it's a Great Lake. Real coords
    # (only available post-geocode) settle it.
    rows = [
        {"place_name": "ASHTABULA LAKESHORE", "water_body_type": "inland_lake",
         "lat": 41.9, "lon": -80.8},
        # Lake Norman, NC - a genuine inland lake, must NOT get relabeled.
        {"place_name": "Lake Norman", "water_body_type": "inland_lake",
         "lat": 35.53, "lon": -80.95},
        # No coordinates yet - left alone, not guessed at.
        {"place_name": "SOUTHERN LAKE", "water_body_type": "inland_lake",
         "lat": None, "lon": None},
        # Already confidently classified - never overridden even if the
        # coordinates happen to fall in a Great Lakes box.
        {"place_name": "Cocoa Beach", "water_body_type": "ocean",
         "lat": 45.0, "lon": -87.0},
    ]
    reclassify_great_lakes_by_coords(rows)
    assert rows[0]["water_body_type"] == "great_lake"
    assert rows[1]["water_body_type"] == "inland_lake"
    assert rows[2]["water_body_type"] == "inland_lake"
    assert rows[3]["water_body_type"] == "ocean"


def test_parse_incident_date_precision_degrades_honestly():
    assert parse_incident_date("6/14", year_hint=2024) == ("2024-06-14", "day")
    assert parse_incident_date("2024-06-14") == ("2024-06-14", "day")
    assert parse_incident_date("2024-06") == ("2024-06-01", "month")
    assert parse_incident_date("2024") == ("2024-01-01", "year")
    assert parse_incident_date("", year_hint=2024) == ("2024-01-01", "year")
    assert parse_incident_date("2/30", year_hint=2024) == ("2024-01-01", "year")


def test_normalize_place_is_stable_for_dedup():
    assert normalize_place("Cocoa Beach") == normalize_place("  cocoa   beach! ")
    assert normalize_place("The Beach at Port Sheldon") == "beach port sheldon"


# ---------------------------------------------------------------------------
# Privacy constraints (plan section 7) - these are the non-negotiable ones
# ---------------------------------------------------------------------------


def test_sanitize_incident_drops_non_canonical_fields():
    dirty = {
        "incident_id": "x:1",
        "source_id": "nws_surf_zone",
        "victim_name": "Jane Doe",
        "home_address": "1 Main St",
        "obituary_url": "https://example.com/obit",
    }
    clean = sanitize_incident(dirty)
    assert set(clean) == set(INCIDENT_FIELDS)
    assert "victim_name" not in clean
    assert "home_address" not in clean
    assert "obituary_url" not in clean


def test_build_incident_emits_exactly_the_canonical_fields():
    row = build_incident(
        source_id="nws_surf_zone",
        source_url="https://www.weather.gov/safety/ripcurrent-fatalities",
        natural_key="2024-06-14|FL|Cocoa Beach|M|22",
        date_value="2024-06-14",
        state="FL",
        place_name="Cocoa Beach",
        hazard="rip_current",
        age=22,
        sex="M",
    )
    assert set(row) == set(INCIDENT_FIELDS)
    assert row["age_band"] == "15-24"
    assert row["water_body_type"] == "ocean"
    assert row["intent"] == "unintentional"
    assert row["superseded_by"] is None


@pytest.mark.parametrize(
    "narrative",
    [
        "Victim was identified as a local resident",
        "See https://news.example.com/story for details",
        "Contact family at someone@example.com",
        "Mr. Smith entered the water",
        "Call 555-123-4567 for information",
        "Lived at 12 Ocean Street",
    ],
)
def test_redact_narrative_drops_anything_identifying(narrative):
    assert redact_narrative(narrative) is None


def test_redact_narrative_keeps_structured_provenance():
    assert redact_narrative("Rip Current (direct)") == "Rip Current (direct)"
    assert redact_narrative("   ") is None


def test_intentional_icd_codes_are_rejected_everywhere():
    assert EXCLUDED_ICD_CODES == {"X71", "X92"}
    assert is_excluded_icd("X71")
    assert is_excluded_icd("W65-W74,X92")
    assert not is_excluded_icd("W65-W74")

    with pytest.raises(ValueError):
        build_stat(
            source_id="cdc_wonder_drowning",
            source_url="https://wonder.cdc.gov/",
            year=2019,
            geo_level="national",
            geo_code="US",
            geo_name="United States",
            measure="deaths",
            value=100,
            icd_codes="X71",
        )


def test_build_incident_rejects_an_out_of_vocabulary_intent():
    with pytest.raises(ValueError):
        build_incident(
            source_id="nws_surf_zone",
            source_url="https://example.gov",
            natural_key="k",
            intent="intentional",
        )


def test_suppressed_stat_keeps_a_null_value_never_zero():
    row = build_stat(
        source_id="cdc_wonder_drowning",
        source_url="https://wonder.cdc.gov/",
        year=2019,
        geo_level="national",
        geo_code="US",
        geo_name="United States",
        measure="deaths",
        value=None,
        suppressed=True,
        icd_codes="W65-W74",
    )
    assert set(row) == set(STAT_FIELDS)
    assert row["suppressed"] is True
    assert row["value"] is None
    assert row["value"] != 0


def test_stat_ids_are_deterministic_and_strata_sensitive():
    def make(sex):
        return build_stat(
            source_id="cdc_wonder_drowning",
            source_url="https://wonder.cdc.gov/",
            year=2019, geo_level="national", geo_code="US",
            geo_name="United States", measure="deaths", value=10,
            icd_codes="W65-W74", age_group="1-4 years", sex=sex,
        )["stat_id"]

    assert make("Female") == make("Female")
    assert make("Female") != make("Male")


def test_incident_ids_are_deterministic():
    assert make_incident_id("s", "key") == make_incident_id("s", "key")
    assert make_incident_id("s", "key") != make_incident_id("s", "other")
    assert make_incident_id("s", "key").startswith("s:")


# ---------------------------------------------------------------------------
# NWS surf zone parsing
# ---------------------------------------------------------------------------


@pytest.fixture
def nws_html():
    return (FIXTURES / "nws_surf_zone_2024.html").read_text(encoding="utf-8")


def test_parse_legend_reads_the_page_rather_than_a_hardcoded_map(nws_html):
    legend = _parse_legend(nws_html)
    assert legend["1"] == "longshore_current"
    assert legend["4"] == "structural_current"
    assert legend["5"] == "high_surf"


def test_promote_header_handles_a_td_header_row(nws_html):
    # The live page marks the header with <td>, so read_html hands back integer
    # column labels with the header sitting in row 0.
    import io

    import pandas as pd

    raw = pd.read_html(io.StringIO(nws_html))[0]
    assert list(raw.columns) == list(range(10))

    promoted = _promote_header(raw)
    assert "location" in promoted.columns
    assert "st" in promoted.columns
    assert "other (see key)" in promoted.columns


def test_promote_header_rejects_an_unrelated_table():
    import pandas as pd

    assert _promote_header(pd.DataFrame({"a": [1], "b": [2]})) is None


def test_published_total_is_read_from_the_page(nws_html):
    # The acceptance check for this source is "does the parsed count match the
    # table's own Total row", so that number has to be machine-readable.
    assert _published_total(nws_html) == 6


def test_nws_rows_skip_padding_total_and_legend_rows(nws_html):
    source = NWSSurfZoneSource(NWS_CONFIG)
    rows = source._rows_from_html(nws_html, 2024)
    assert len(rows) == 6
    assert len(rows) == _published_total(nws_html)
    assert all(row["location"] for row in rows)
    assert not any(row["location"].lower().startswith("total") for row in rows)
    assert not any(row["location"].lower().startswith("key:") for row in rows)


def test_nws_flag_columns_collapse_into_one_hazard(nws_html):
    source = NWSSurfZoneSource(NWS_CONFIG)
    hazards = {
        row["location"]: row["hazard"]
        for row in source._rows_from_html(nws_html, 2024)
    }
    assert hazards["Cocoa Beach"] == "rip_current"
    assert hazards["Ocean Beach"] == "high_surf"
    assert hazards["Cannon Beach"] == "sneaker_wave"
    assert hazards["Port Sheldon, Lake Michigan"] == "longshore_current"
    assert hazards["Grand Haven Pier"] == "structural_current"
    assert hazards["Wrightsville Beach"] == "unknown"


def test_nws_incidents_are_canonical_and_carry_dirty_ages_verbatim(nws_html):
    source = NWSSurfZoneSource(NWS_CONFIG)
    started = datetime(2026, 1, 1)
    incidents = [
        source._incident_from_html_row(row, "https://example.gov", started)
        for row in source._rows_from_html(nws_html, 2024)
    ]
    assert all(set(inc) == set(INCIDENT_FIELDS) for inc in incidents)

    by_place = {inc["place_name"]: inc for inc in incidents}
    cocoa = by_place["Cocoa Beach"]
    assert cocoa["date"] == "2024-06-14"
    assert cocoa["state"] == "FL"
    assert cocoa["age"] == 22
    assert cocoa["water_body_type"] == "ocean"

    ocean_beach = by_place["Ocean Beach"]
    assert ocean_beach["age"] is None
    assert ocean_beach["age_text"] == "Late 20s"
    assert ocean_beach["age_band"] == "unknown"

    port_sheldon = by_place["Port Sheldon, Lake Michigan"]
    assert port_sheldon["water_body_type"] == "great_lake"

    # Nothing is mapped yet - the geocoder runs later and never invents a point.
    assert all(inc["lat"] is None for inc in incidents)
    assert all(inc["geo_precision"] == "unknown" for inc in incidents)


# ---------------------------------------------------------------------------
# NCEI storm events parsing
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, content: bytes):
        self.content = content


class _StubClient:
    """Serves the fixture CSVs, gzipped, in place of the NCEI bulk files."""

    def __init__(self, mapping: dict[str, bytes]):
        self._mapping = mapping

    def get(self, url, **_kwargs):
        for key, content in self._mapping.items():
            if key in url:
                return _StubResponse(content)
        raise AssertionError(f"unexpected URL {url}")


def _gzip_fixture(name: str) -> bytes:
    raw = (FIXTURES / name).read_bytes()
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as handle:
        handle.write(raw)
    return buffer.getvalue()


@pytest.fixture
def ncei_incidents():
    source = NCEIStormEventsSource(NCEI_CONFIG)
    client = _StubClient(
        {
            "details": _gzip_fixture("ncei_details_2024.csv"),
            "fatalities": _gzip_fixture("ncei_fatalities_2024.csv"),
        }
    )
    urls = {
        "details": "https://example.gov/StormEvents_details-ftp_v1.0_d2024_c20250101.csv.gz",
        "fatalities": "https://example.gov/StormEvents_fatalities-ftp_v1.0_d2024_c20250101.csv.gz",
    }
    unknown: dict[str, int] = {}
    incidents = source._incidents_for_year(
        client, 2024, urls,
        {"rip current", "high surf", "flash flood", "flood"},
        datetime(2026, 1, 1), unknown,
    )
    return incidents, unknown


def test_ncei_filters_to_water_event_types_and_water_fatality_locations(ncei_incidents):
    incidents, unknown = ncei_incidents
    # Rip Current + High Surf + Flash Flood survive; the tornado is dropped by
    # event type, and the "Ball Field" fatality by fatality location.
    assert len(incidents) == 3
    assert "BALL FIELD" in unknown
    assert "MOBILE/TRAILER HOME" not in unknown  # its event type filtered first


def test_ncei_rows_carry_real_coordinates(ncei_incidents):
    incidents, _ = ncei_incidents
    assert all(inc["lat"] is not None and inc["lon"] is not None for inc in incidents)
    assert all(inc["geo_precision"] == "exact" for inc in incidents)


def test_ncei_maps_hazard_activity_and_county_fips(ncei_incidents):
    incidents, _ = ncei_incidents
    by_place = {inc["place_name"]: inc for inc in incidents}

    brevard = by_place["BREVARD"]
    assert brevard["hazard"] == "rip_current"
    assert brevard["activity"] == "swimming"
    assert brevard["county_fips"] == "12009"
    assert brevard["date"] == "2024-06-14"
    assert brevard["state"] == "FL"

    bexar = by_place["BEXAR"]
    assert bexar["hazard"] == "flood"
    assert bexar["activity"] == "vehicle"


def test_ncei_does_not_ingest_the_free_text_narratives(ncei_incidents):
    incidents, _ = ncei_incidents
    for incident in incidents:
        assert set(incident) == set(INCIDENT_FIELDS)
        assert "swimmer was pulled offshore" not in (incident["notes"] or "")
        assert incident["notes"].endswith(("(direct)", "(indirect)"))


# ---------------------------------------------------------------------------
# USCG BARD parsing
# ---------------------------------------------------------------------------


BARD_CONFIG = SourceConfig(
    id="uscg_bard", name="USCG BARD", type="uscg_bard", config={},
    primary_keys=["incident_id"],
)


@pytest.fixture
def bard_incidents():
    source = USCGBardSource(BARD_CONFIG)
    client = _StubClient(
        {
            "Accidents": (FIXTURES / "bard_accidents_sample.csv").read_bytes(),
            "Deaths": (FIXTURES / "bard_deaths_sample.csv").read_bytes(),
        }
    )
    return source._incidents_for_period(
        client, "https://example/Accidents.csv", "https://example/Deaths.csv",
        datetime(2026, 1, 1),
    )


def test_bard_keeps_only_drowning_deaths_with_a_valid_state(bard_incidents):
    # NC-2020-0999 dies of a heart attack (excluded); XX-2020-0001 drowns but
    # has an unrecognized state code (excluded). The two real Lake Norman
    # drownings (NC-2020-0020, NC-2022-0016) survive.
    assert len(bard_incidents) == 2
    by_bardid = {row["place_name"] + row["date"]: row for row in bard_incidents}
    row = by_bardid["Mooresville2020-05-03"]
    assert row["water_body_name"] == "LAKE NORMAN"
    assert row["water_body_type"] == "inland_lake"
    assert row["state"] == "NC"


def test_bard_fixes_known_water_body_name_typos(bard_incidents):
    # NC-2022-0016's real NameOfBodyOfWater is "LAKKE NORMAN" - confirmed by
    # inspecting the actual raw file while chasing why a real 2022 Lake
    # Norman death wasn't grouping with the rest under one name.
    row = next(r for r in bard_incidents if r["place_name"] == "LONG ISLAND")
    assert row["water_body_name"] == "LAKE NORMAN"
    assert row["water_body_type"] == "inland_lake"


def test_bard_only_trusts_coordinates_flagged_confident(bard_incidents):
    row = bard_incidents[0]
    assert row["lat"] == pytest.approx(35.526943)
    assert row["lon"] == pytest.approx(-80.940277)
    assert row["geo_precision"] == "exact"


def test_bard_maps_accident_event_to_hazard_and_activity(bard_incidents):
    row = bard_incidents[0]
    assert row["hazard"] == "fall_overboard"
    assert row["activity"] == "boating"


def test_bard_does_not_ingest_the_free_text_narrative_or_gender_guess(bard_incidents):
    row = bard_incidents[0]
    assert set(row) == set(INCIDENT_FIELDS)
    assert "fell from a boat" not in (row["notes"] or "")
    assert row["sex"] == "U"


def test_water_fatality_location_set_is_explicit():
    # Guards against someone widening the filter without thinking about it.
    assert "IN WATER" in WATER_FATALITY_LOCATIONS
    assert "BALL FIELD" not in WATER_FATALITY_LOCATIONS


# ---------------------------------------------------------------------------
# CDC WONDER parsing
# ---------------------------------------------------------------------------


def test_wonder_expands_ranges_and_strips_excluded_codes():
    source = CDCWonderSource(WONDER_CONFIG)
    expanded = source._expand_icd(["W65-W68", "X71", "Y21"])
    assert expanded == ["W65", "W66", "W67", "W68", "Y21"]


def test_wonder_groups_codes_by_intent():
    groups = group_codes_by_intent(["W65", "W74", "V90", "Y21"])
    assert groups["unintentional"] == ["W65", "W74", "V90"]
    assert groups["undetermined"] == ["Y21"]


def test_wonder_request_xml_is_templated_not_hand_authored():
    source = CDCWonderSource(WONDER_CONFIG)
    xml = source._build_request_xml("D76", ["W65", "W66"], [2019, 2020],
                                    ["year", "age_group", "sex"])
    assert "{{" not in xml
    assert "<value>W65</value>" in xml
    assert "<value>2019</value>" in xml
    assert "<value>D76.V1-level1</value>" in xml
    assert "<value>D76.V5</value>" in xml
    assert "<value>D76.V7</value>" in xml
    assert "accept_datause_restrictions" in xml


def test_wonder_parses_suppressed_cells_as_suppressed_not_zero():
    source = CDCWonderSource(WONDER_CONFIG)
    xml = (FIXTURES / "wonder_response.xml").read_text(encoding="utf-8")
    rows = source.parse_response(
        xml, ["year", "age_group", "sex"], "W65-W74", "unintentional",
        "https://wonder.cdc.gov/controller/datarequest/D76", datetime(2026, 1, 1),
    )

    deaths = {
        (r["year"], r["age_group"], r["sex"]): r
        for r in rows if r["measure"] == "deaths"
    }
    assert deaths[(2019, "1-4 years", "Female")]["value"] == 371.0
    assert deaths[(2019, "1-4 years", "Female")]["suppressed"] is False

    suppressed = deaths[(2019, "85+ years", "Female")]
    assert suppressed["suppressed"] is True
    assert suppressed["value"] is None

    # Population is a denominator, not one of our published measures.
    assert {r["measure"] for r in rows} == {"deaths", "crude_rate", "age_adjusted_rate"}


def test_wonder_carries_labels_forward_on_continuation_rows():
    source = CDCWonderSource(WONDER_CONFIG)
    xml = (FIXTURES / "wonder_response.xml").read_text(encoding="utf-8")
    rows = source.parse_response(
        xml, ["year", "age_group", "sex"], "W65-W74", "unintentional",
        "https://wonder.cdc.gov/", datetime(2026, 1, 1),
    )
    male = [r for r in rows if r["sex"] == "Male" and r["measure"] == "deaths"]
    assert len(male) == 1
    # WONDER omitted the repeated year and age labels on that row.
    assert male[0]["year"] == 2019
    assert male[0]["age_group"] == "1-4 years"
    assert male[0]["value"] == 512.0


def test_wonder_refuses_a_state_grouping():
    # State/county grouping is blocked by WONDER's API. Failing loudly beats
    # returning national numbers labelled as state ones.
    source = CDCWonderSource(WONDER_CONFIG)
    result = source.fetch(groupings=[["year", "state"]])
    assert result.record_count == 0
    assert "state" in (result.error or "").lower()

    result = source.fetch(group_by=["year", "state"])
    assert result.record_count == 0
    assert "state" in (result.error or "").lower()


def test_wonder_throttles_after_a_failed_request_too():
    # A failed query still counts against WONDER's rate limit. Keying the
    # throttle off successful queries turns one error into a cascade of 429s.
    source = CDCWonderSource(WONDER_CONFIG)
    sleeps = []

    with patch("cdata.sources.api.safety.cdc_wonder.time.sleep", sleeps.append):
        with patch.object(source, "_build_request_xml", return_value="<x/>"):
            with patch("httpx.Client.post", side_effect=RuntimeError("boom")):
                result = source.fetch(
                    databases=["D76"],
                    groupings=[["year"], ["year", "age_group"]],
                    min_seconds_between_requests=20,
                    start_year=2019, end_year=2019,
                )

    assert result.record_count == 0
    # Four queries attempted (2 intents x 2 groupings), all failed; the first
    # goes straight out and each of the other three waits.
    assert len(sleeps) == 3
    assert all(0 < value <= 20 for value in sleeps)


def test_wonder_requires_a_year_in_every_grouping():
    source = CDCWonderSource(WONDER_CONFIG)
    result = source.fetch(groupings=[["age_group"]])
    assert result.record_count == 0
    assert "year" in (result.error or "")


def test_wonder_ungrouped_dimensions_come_back_as_all():
    # The ["year"] pass is what produces the national headline number, so its
    # rows must be labelled "All" rather than left blank.
    source = CDCWonderSource(WONDER_CONFIG)
    xml = (
        '<page><response><data-table>'
        '<r><c l="2019"/><c v="4,012"/><c v="330,000,000"/>'
        '<c v="1.2"/><c v="1.2"/></r>'
        '</data-table></response></page>'
    )
    rows = source.parse_response(
        xml, ["year"], "W65-W74", "unintentional",
        "https://wonder.cdc.gov/", datetime(2026, 1, 1),
    )
    deaths = next(r for r in rows if r["measure"] == "deaths")
    assert deaths["value"] == 4012.0
    assert deaths["age_group"] == "All"
    assert deaths["sex"] == "All"
    assert deaths["geo_level"] == "national"


def test_wonder_refuses_excluded_icd_codes():
    source = CDCWonderSource(WONDER_CONFIG)
    result = source.fetch(icd_codes=["W65-W74", "X71"])
    assert result.record_count == 0
    assert "X71" in (result.error or "")


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def _incident(source_id, key, date_value, place, state="MI", age=17, sex="M"):
    return build_incident(
        source_id=source_id,
        source_url="https://example.gov",
        natural_key=key,
        date_value=date_value,
        state=state,
        place_name=place,
        hazard="rip_current",
        age=age,
        sex=sex,
    )


def test_dedup_prefers_nws_and_keeps_losers_for_provenance():
    rows = [
        _incident("ncei_storm_events", "a", "2024-08-03", "Port Sheldon"),
        _incident("nws_surf_zone", "b", "2024-08-03", "Port Sheldon"),
    ]
    deduped, report = dedup_incidents(rows)

    winner = next(r for r in deduped if r["source_id"] == "nws_surf_zone")
    loser = next(r for r in deduped if r["source_id"] == "ncei_storm_events")
    assert winner["superseded_by"] is None
    assert loser["superseded_by"] == winner["incident_id"]

    # Nothing was deleted.
    assert len(deduped) == 2
    assert report["clusters"] == 1
    assert report["superseded"] == 1
    assert report["rows_surviving"] == 1


def test_dedup_tolerates_a_one_day_date_difference():
    rows = [
        _incident("nws_surf_zone", "a", "2024-08-03", "Port Sheldon"),
        _incident("ncei_storm_events", "b", "2024-08-04", "Port Sheldon"),
    ]
    _deduped, report = dedup_incidents(rows)
    assert report["superseded"] == 1


def test_dedup_does_not_merge_across_a_two_day_gap():
    rows = [
        _incident("nws_surf_zone", "a", "2024-08-03", "Port Sheldon"),
        _incident("ncei_storm_events", "b", "2024-08-06", "Port Sheldon"),
    ]
    _deduped, report = dedup_incidents(rows)
    assert report["superseded"] == 0


def test_dedup_never_merges_two_rows_from_the_same_source():
    # Two people can drown at the same beach on the same day. One source
    # reporting both is not a duplicate.
    rows = [
        _incident("nws_surf_zone", "a", "2024-08-03", "Port Sheldon", sex="M"),
        _incident("nws_surf_zone", "b", "2024-08-03", "Port Sheldon", sex="M"),
    ]
    _deduped, report = dedup_incidents(rows)
    assert report["superseded"] == 0


def test_dedup_separates_different_people_by_age_bucket_and_sex():
    rows = [
        _incident("nws_surf_zone", "a", "2024-08-03", "Port Sheldon", age=17),
        _incident("ncei_storm_events", "b", "2024-08-03", "Port Sheldon", age=41),
        _incident("ncei_storm_events", "c", "2024-08-03", "Port Sheldon",
                  age=17, sex="F"),
    ]
    _deduped, report = dedup_incidents(rows)
    assert report["superseded"] == 0


# ---------------------------------------------------------------------------
# Geocoder
# ---------------------------------------------------------------------------


def test_geocode_cache_key_is_stable():
    assert cache_key("Cocoa Beach", "FL") == cache_key("Cocoa Beach", "FL")
    assert cache_key("Cocoa Beach", "FL") != cache_key("Cocoa Beach", "CA")


def test_normalize_for_gazetteer():
    assert normalize_for_gazetteer("Grand Haven Pier!") == "grand haven pier"


def test_unresolved_rows_are_kept_and_never_placed_at_a_centroid(tmp_path):
    geocoder = Geocoder(
        cache_path=tmp_path / "geocode.json",
        gnis_dir=tmp_path / "gnis",
        use_nominatim=False,
    )
    rows = [
        _incident("nws_surf_zone", "a", "2024-08-03", "Nowhere In Particular"),
    ]
    enriched = geocoder.enrich(rows)

    assert len(enriched) == 1                       # never dropped
    assert enriched[0]["lat"] is None               # never invented
    assert enriched[0]["geo_precision"] == "state"  # honest about precision


def test_geocoder_passes_through_rows_that_already_have_coordinates(tmp_path):
    geocoder = Geocoder(
        cache_path=tmp_path / "geocode.json",
        gnis_dir=tmp_path / "gnis",
        use_nominatim=False,
    )
    row = _incident("ncei_storm_events", "a", "2024-06-14", "Brevard", state="FL")
    row["lat"], row["lon"], row["geo_precision"] = 28.32, -80.6076, "exact"
    geocoder.enrich([row])
    assert row["lat"] == 28.32
    assert row["geo_precision"] == "exact"
    assert geocoder.stats["lookups"] == 0


def test_geocoder_resolves_from_a_local_gnis_file(tmp_path):
    gnis_dir = tmp_path / "gnis"
    gnis_dir.mkdir()
    (gnis_dir / "NationalFile.txt").write_text(
        "feature_id|feature_name|feature_class|state_alpha|prim_lat_dec|prim_long_dec\n"
        "1|Cocoa Beach|Beach|FL|28.3200|-80.6076\n"
        "2|Port Sheldon|Populated Place|MI|42.9430|-86.2100\n",
        encoding="utf-8",
    )
    geocoder = Geocoder(
        cache_path=tmp_path / "geocode.json",
        gnis_dir=gnis_dir,
        use_nominatim=False,
    )
    hit = geocoder.geocode("Cocoa Beach", "FL")
    assert hit["provider"] == "gnis"
    assert hit["geo_precision"] == "beach"
    assert hit["lat"] == pytest.approx(28.32)

    inland = geocoder.geocode("Port Sheldon", "Michigan")
    assert inland["geo_precision"] == "place"

    geocoder.save_cache()
    assert (tmp_path / "geocode.json").exists()

    # A second geocoder reads the committed cache rather than re-resolving.
    reloaded = Geocoder(
        cache_path=tmp_path / "geocode.json",
        gnis_dir=tmp_path / "empty",
        use_nominatim=False,
    )
    assert reloaded.geocode("Cocoa Beach", "FL")["lat"] == pytest.approx(28.32)
    assert reloaded.stats["cache_hits"] == 1


def test_geocoder_handles_state_name_column_not_just_state_alpha(tmp_path):
    """USGS's current National File ships "state_name" (full name), not
    "state_alpha" - confirmed by downloading and inspecting the real file.
    A gazetteer built against only "state_alpha" would index every row
    under an empty state key and never match anything.
    """
    gnis_dir = tmp_path / "gnis"
    gnis_dir.mkdir()
    (gnis_dir / "NationalFile.txt").write_text(
        "feature_id|feature_name|feature_class|state_name|prim_lat_dec|prim_long_dec\n"
        "1|Cocoa Beach|Beach|Florida|28.3200|-80.6076\n",
        encoding="utf-8",
    )
    geocoder = Geocoder(
        cache_path=tmp_path / "geocode.json", gnis_dir=gnis_dir, use_nominatim=False,
    )
    hit = geocoder.geocode("Cocoa Beach", "FL")
    assert hit is not None
    assert hit["provider"] == "gnis"
    assert hit["lat"] == pytest.approx(28.32)


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_type,expected",
    [
        ("nws_surf_zone", NWSSurfZoneSource),
        ("ncei_storm_events", NCEIStormEventsSource),
        ("cdc_wonder", CDCWonderSource),
        ("uscg_bard", USCGBardSource),
    ],
)
def test_drowning_sources_are_registered(source_type, expected):
    registry = get_registry()
    assert registry.is_registered(source_type)
    assert registry.get_source_class(source_type) is expected
