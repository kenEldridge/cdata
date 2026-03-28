"""Tests for geopolitics sources (ACLED, GDELT, ISW RSS)."""

import csv
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cdata.config.schema import SourceConfig
from cdata.core.registry import get_registry
from cdata.sources.api.geopolitics.acled import ACLEDSource
from cdata.sources.api.geopolitics.gdelt import GDELTSource, EVENT_COLUMNS, COUNTRY_FIPS
from cdata.sources.rss.feedparser import RSSSource

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ACLED_CONFIG = SourceConfig(
    id="acled_test",
    name="ACLED Test",
    type="acled",
    config={"countries": ["Ukraine"], "lookback_days": 30},
    primary_keys=["event_id_cnty"],
)

ISW_CONFIG = SourceConfig(
    id="isw_test",
    name="ISW Test",
    type="rss",
    config={"feeds": [{"name": "ISW", "url": "https://www.understandingwar.org/rss.xml"}]},
    primary_keys=["link"],
)

SAMPLE_ACLED_EVENT = {
    "event_id_cnty": "UKR12345",
    "event_date": "2025-03-20",
    "year": "2025",
    "time_precision": "1",
    "disorder_type": "Political violence",
    "event_type": "Battles",
    "sub_event_type": "Armed clash",
    "actor1": "Military Forces of Ukraine",
    "actor2": "Military Forces of Russia",
    "assoc_actor_1": "",
    "assoc_actor_2": "",
    "country": "Ukraine",
    "admin1": "Donetsk",
    "admin2": "Bakhmut",
    "location": "Bakhmut",
    "latitude": "48.5953",
    "longitude": "38.0003",
    "fatalities": "3",
    "source": "Ukraine Armed Forces",
    "source_scale": "National",
    "notes": "Clashes reported near Bakhmut.",
    "civilian_targeting": "",
}

TOKEN_RESPONSE = {"access_token": "test-token-abc", "refresh_token": "refresh-xyz"}


def _mock_token_and_data(events, pages=1):
    """Return a side_effect function that handles token + paginated data requests."""
    call_count = {"n": 0}

    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        if "oauth/token" in str(url):
            resp.json.return_value = TOKEN_RESPONSE
            return resp

        # Data request
        call_count["n"] += 1
        if call_count["n"] <= pages:
            resp.json.return_value = {"data": events}
        else:
            resp.json.return_value = {"data": []}
        return resp

    return side_effect


# ---------------------------------------------------------------------------
# ACLED tests
# ---------------------------------------------------------------------------


def test_acled_registry():
    """Registry can resolve 'acled' source type."""
    # Clear lru_cache so registry picks up current entry points
    get_registry.cache_clear()
    registry = get_registry()
    assert registry.is_registered("acled")
    source = registry.create_source(ACLED_CONFIG)
    assert isinstance(source, ACLEDSource)


@patch("cdata.sources.api.geopolitics.acled.get_settings")
def test_acled_fetch_parses_records(mock_settings):
    """Fetch parses ACLED events into Records with expected fields."""
    mock_settings.return_value = MagicMock(acled_email="test@x.com", acled_password="pw")

    source = ACLEDSource(ACLED_CONFIG)
    events = [SAMPLE_ACLED_EVENT]

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.post = MagicMock(side_effect=_mock_token_and_data(events))
        client.get = MagicMock(side_effect=_mock_token_and_data(events))

        result = source.fetch(**ACLED_CONFIG.config)

    assert result.record_count == 1
    rec = result.records[0]
    assert rec.data["event_id_cnty"] == "UKR12345"
    assert rec.data["country"] == "Ukraine"
    assert rec.data["latitude"] == 48.5953
    assert rec.data["longitude"] == 38.0003
    assert rec.data["fatalities"] == 3
    assert rec.data["event_type"] == "Battles"


@patch("cdata.sources.api.geopolitics.acled.get_settings")
def test_acled_fetch_pagination(mock_settings):
    """Fetch consumes multiple pages of results."""
    mock_settings.return_value = MagicMock(acled_email="test@x.com", acled_password="pw")

    source = ACLEDSource(ACLED_CONFIG)
    page1 = [SAMPLE_ACLED_EVENT] * 5000  # full page
    page2 = [SAMPLE_ACLED_EVENT] * 100  # partial page (last)

    page_num = {"current": 0}

    def get_side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        page_num["current"] += 1
        if page_num["current"] == 1:
            resp.json.return_value = {"data": page1}
        elif page_num["current"] == 2:
            resp.json.return_value = {"data": page2}
        else:
            resp.json.return_value = {"data": []}
        return resp

    def post_side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = TOKEN_RESPONSE
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.post = MagicMock(side_effect=post_side_effect)
        client.get = MagicMock(side_effect=get_side_effect)

        result = source.fetch(**ACLED_CONFIG.config)

    assert result.record_count == 5100


@patch("cdata.sources.api.geopolitics.acled.get_settings")
def test_acled_auth_error(mock_settings):
    """Missing credentials produce a clean error, not a crash."""
    mock_settings.return_value = MagicMock(acled_email=None, acled_password=None)

    source = ACLEDSource(ACLED_CONFIG)
    result = source.fetch(**ACLED_CONFIG.config)

    assert result.error is not None
    assert "ACLED credentials not set" in result.error


@patch("cdata.sources.api.geopolitics.acled.get_settings")
def test_acled_test_connection(mock_settings):
    """test_connection() returns True on a successful 1-record response."""
    mock_settings.return_value = MagicMock(acled_email="test@x.com", acled_password="pw")

    source = ACLEDSource(ACLED_CONFIG)

    def post_side_effect(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = TOKEN_RESPONSE
        return resp

    def get_side_effect(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": [SAMPLE_ACLED_EVENT]}
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.post = MagicMock(side_effect=post_side_effect)
        client.get = MagicMock(side_effect=get_side_effect)

        assert source.test_connection() is True


# ---------------------------------------------------------------------------
# ISW / RSS tests
# ---------------------------------------------------------------------------


def test_isw_config_loads():
    """geopolitics.yaml loads and contains ISW source config."""
    import yaml

    config_path = Path(__file__).resolve().parents[1] / "config" / "sources" / "geopolitics.yaml"
    assert config_path.exists(), f"Missing {config_path}"

    with open(config_path) as f:
        data = yaml.safe_load(f)

    source_ids = [s["id"] for s in data["sources"]]
    assert "isw_assessments" in source_ids

    isw = next(s for s in data["sources"] if s["id"] == "isw_assessments")
    assert isw["type"] == "rss"
    assert isw["primary_keys"] == ["link"]


def test_rss_test_connection_uses_config():
    """RSSSource.test_connection() uses the configured feed URL, not Hacker News."""
    source = RSSSource(ISW_CONFIG)

    with patch("feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(entries=[MagicMock()])
        source.test_connection()

    mock_parse.assert_called_once_with("https://www.understandingwar.org/rss.xml")


# ---------------------------------------------------------------------------
# GDELT tests
# ---------------------------------------------------------------------------

GDELT_CONFIG = SourceConfig(
    id="gdelt_test",
    name="GDELT Test",
    type="gdelt",
    config={"countries": ["Ukraine", "Russia"], "lookback_days": 1, "quad_classes": [3, 4], "min_mentions": 1},
    primary_keys=["GLOBALEVENTID"],
)


def _make_gdelt_zip(rows: list[dict[str, str]]) -> bytes:
    """Build a GDELT-style ZIP containing a tab-delimited CSV."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_buf = io.StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=EVENT_COLUMNS, delimiter="\t", extrasaction="ignore")
        for row in rows:
            full_row = {c: "" for c in EVENT_COLUMNS}
            full_row.update(row)
            writer.writerow(full_row)
        zf.writestr("test.export.CSV", csv_buf.getvalue())
    return buf.getvalue()


SAMPLE_GDELT_EVENT = {
    "GLOBALEVENTID": "1234567890",
    "SQLDATE": "20260328",
    "Year": "2026",
    "Actor1Code": "RUS",
    "Actor1Name": "RUSSIA",
    "Actor1CountryCode": "RS",
    "Actor1Type1Code": "MIL",
    "Actor2Code": "UKR",
    "Actor2Name": "UKRAINE",
    "Actor2CountryCode": "UP",
    "Actor2Type1Code": "MIL",
    "EventCode": "190",
    "EventBaseCode": "190",
    "EventRootCode": "19",
    "QuadClass": "4",
    "GoldsteinScale": "-10.0",
    "NumMentions": "15",
    "NumSources": "8",
    "AvgTone": "-5.2",
    "ActionGeo_FullName": "Donetsk, Ukraine",
    "ActionGeo_CountryCode": "UP",
    "ActionGeo_Lat": "48.0",
    "ActionGeo_Long": "37.8",
    "DATEADDED": "20260328120000",
    "SOURCEURL": "https://example.com/article",
}


def test_gdelt_registry():
    """Registry can resolve 'gdelt' source type."""
    get_registry.cache_clear()
    registry = get_registry()
    assert registry.is_registered("gdelt")
    source = registry.create_source(GDELT_CONFIG)
    assert isinstance(source, GDELTSource)


def test_gdelt_fetch_parses_records():
    """Fetch parses GDELT events into Records with expected fields."""
    source = GDELTSource(GDELT_CONFIG)
    zip_data = _make_gdelt_zip([SAMPLE_GDELT_EVENT])

    def mock_get(url, **kwargs):
        resp = MagicMock()
        if "lastupdate" in url or "masterfile" in url:
            resp.status_code = 200
            resp.text = "test"
            return resp
        resp.status_code = 200
        resp.content = zip_data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get = MagicMock(side_effect=mock_get)
        result = source.fetch(**GDELT_CONFIG.config)

    assert result.record_count > 0
    rec = result.records[0]
    assert rec.data["GLOBALEVENTID"] == "1234567890"
    assert rec.data["Actor1CountryCode"] == "RS"
    assert rec.data["Actor2CountryCode"] == "UP"
    assert rec.data["QuadClass"] == 4
    assert rec.data["GoldsteinScale"] == -10.0
    assert rec.data["NumMentions"] == 15


def test_gdelt_filters_by_country():
    """Events not involving configured countries are excluded."""
    source = GDELTSource(GDELT_CONFIG)
    # Event in China, not Ukraine/Russia
    china_event = {**SAMPLE_GDELT_EVENT, "GLOBALEVENTID": "999", "Actor1CountryCode": "CH",
                   "Actor2CountryCode": "CH", "ActionGeo_CountryCode": "CH"}
    zip_data = _make_gdelt_zip([SAMPLE_GDELT_EVENT, china_event])

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = zip_data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get = MagicMock(side_effect=mock_get)
        result = source.fetch(**GDELT_CONFIG.config)

    # All records should be the Ukraine/Russia event, not China
    for rec in result.records:
        assert rec.data["GLOBALEVENTID"] == "1234567890"


def test_gdelt_filters_by_quad_class():
    """Events with wrong QuadClass are excluded."""
    source = GDELTSource(GDELT_CONFIG)
    cooperation_event = {**SAMPLE_GDELT_EVENT, "GLOBALEVENTID": "888", "QuadClass": "1"}
    zip_data = _make_gdelt_zip([SAMPLE_GDELT_EVENT, cooperation_event])

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = zip_data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get = MagicMock(side_effect=mock_get)
        result = source.fetch(**GDELT_CONFIG.config)

    for rec in result.records:
        assert rec.data["QuadClass"] in (3, 4)


def test_gdelt_test_connection():
    """test_connection() returns True when last-update file is available."""
    source = GDELTSource(GDELT_CONFIG)

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "12345 abc http://data.gdeltproject.org/gdeltv2/20260328120000.export.CSV.zip"
        return resp

    with patch("httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get = MagicMock(side_effect=mock_get)
        assert source.test_connection() is True


def test_gdelt_fips_mapping():
    """Country names resolve to correct FIPS codes."""
    source = GDELTSource(GDELT_CONFIG)
    codes = source._resolve_fips_codes(["Ukraine", "Russia", "Palestine"])
    assert "UP" in codes
    assert "RS" in codes
    assert "GZ" in codes
    assert "WE" in codes  # Palestine has two codes


def test_gdelt_config_in_yaml():
    """geopolitics.yaml contains GDELT source config."""
    import yaml
    config_path = Path(__file__).resolve().parents[1] / "config" / "sources" / "geopolitics.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    source_ids = [s["id"] for s in data["sources"]]
    assert "gdelt_conflict_events" in source_ids
    gdelt = next(s for s in data["sources"] if s["id"] == "gdelt_conflict_events")
    assert gdelt["type"] == "gdelt"
    assert gdelt["primary_keys"] == ["GLOBALEVENTID"]
