"""Tests for cdata.sources."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from cdata.config.schema import SourceConfig
from cdata.models import FetchStatus
from cdata.sources.base import BaseSource
from cdata.sources.rss.feedparser import RSSSource
from cdata.sources.scraping.generic import ScrapingSource


class ConcreteSource(BaseSource):
    """Concrete implementation of BaseSource for testing."""

    source_type = "test"

    def fetch(self, **kwargs):
        started_at = datetime.utcnow()
        records = [
            self._create_record({"item": i}, {"index": i})
            for i in range(kwargs.get("count", 3))
        ]
        return self._create_result(records, started_at)

    def test_connection(self) -> bool:
        return True


class TestBaseSource:
    """Tests for BaseSource abstract class."""

    def test_init(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        assert source.source_id == "test_source"
        assert source.config == sample_source_config

    def test_create_record(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        record = source._create_record(
            data={"key": "value"},
            metadata={"extra": "info"},
        )
        assert record.source_id == "test_source"
        assert record.data == {"key": "value"}
        assert record.metadata == {"extra": "info"}

    def test_create_result_success(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        started_at = datetime.utcnow()
        records = [source._create_record({"x": 1})]

        result = source._create_result(records, started_at)
        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 1
        assert result.error is None

    def test_create_result_failed(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        started_at = datetime.utcnow()

        result = source._create_result([], started_at, error="Connection failed")
        assert result.status == FetchStatus.FAILED
        assert result.error == "Connection failed"

    def test_create_result_partial(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        started_at = datetime.utcnow()
        records = [source._create_record({"x": 1})]

        result = source._create_result(records, started_at, error="Some items failed")
        assert result.status == FetchStatus.PARTIAL
        assert result.record_count == 1
        assert result.error is not None

    def test_fetch(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        result = source.fetch(count=5)

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 5

    def test_test_connection(self, sample_source_config: SourceConfig):
        source = ConcreteSource(sample_source_config)
        assert source.test_connection() is True


class TestRSSSource:
    """Tests for RSSSource."""

    @pytest.fixture
    def rss_config(self) -> SourceConfig:
        return SourceConfig(
            id="test_rss",
            name="Test RSS",
            type="rss",
            config={},
        )

    @pytest.fixture
    def mock_feed(self):
        """Create a mock feed parser response."""
        mock = MagicMock()
        mock.bozo = False
        mock.bozo_exception = None
        mock.feed = {"title": "Test Feed"}
        mock.entries = [
            MagicMock(
                title="Article 1",
                link="https://example.com/1",
                summary="Summary 1",
                author="Author 1",
                published_parsed=(2025, 1, 15, 10, 0, 0, 0, 0, 0),
                id="entry-1",
            ),
            MagicMock(
                title="Article 2",
                link="https://example.com/2",
                summary="Summary 2",
                author=None,
                published_parsed=None,
                updated_parsed=(2025, 1, 14, 9, 0, 0, 0, 0, 0),
                id="entry-2",
            ),
        ]
        return mock

    def test_fetch_single_url(self, rss_config: SourceConfig, mock_feed):
        source = RSSSource(rss_config)

        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch(url="https://example.com/feed.xml")

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 2
        assert result.records[0].data["title"] == "Article 1"

    def test_fetch_multiple_feeds(self, rss_config: SourceConfig, mock_feed):
        source = RSSSource(rss_config)

        feeds = [
            {"name": "Feed 1", "url": "https://example.com/feed1.xml"},
            {"name": "Feed 2", "url": "https://example.com/feed2.xml"},
        ]

        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch(feeds=feeds)

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 4  # 2 entries per feed

    def test_fetch_with_parse_error(self, rss_config: SourceConfig):
        source = RSSSource(rss_config)

        mock_feed = MagicMock()
        mock_feed.bozo = True
        mock_feed.bozo_exception = Exception("Parse error")
        mock_feed.feed = {}
        mock_feed.entries = []

        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch(url="https://example.com/bad.xml")

        # Should still succeed (partial) with error noted
        assert "Parse error" in (result.error or "")

    def test_fetch_missing_url(self, rss_config: SourceConfig):
        source = RSSSource(rss_config)

        feeds = [{"name": "No URL Feed"}]
        result = source.fetch(feeds=feeds)

        assert result.error is not None
        assert "No URL" in result.error

    def test_test_connection(self, rss_config: SourceConfig):
        source = RSSSource(rss_config)

        mock_feed = MagicMock()
        mock_feed.entries = [MagicMock()]

        with patch("feedparser.parse", return_value=mock_feed):
            assert source.test_connection() is True

    def test_test_connection_failure(self, rss_config: SourceConfig):
        source = RSSSource(rss_config)

        mock_feed = MagicMock()
        mock_feed.entries = []

        with patch("feedparser.parse", return_value=mock_feed):
            assert source.test_connection() is False


class TestScrapingSource:
    """Tests for ScrapingSource."""

    @pytest.fixture
    def scraping_config(self) -> SourceConfig:
        return SourceConfig(
            id="test_scraper",
            name="Test Scraper",
            type="scraping",
            config={},
        )

    @pytest.fixture
    def mock_response(self):
        """Create a mock HTTP response."""
        mock = MagicMock()
        mock.text = """
        <html>
            <body>
                <div class="item">Item 1</div>
                <div class="item">Item 2</div>
                <a href="https://example.com/link">Link</a>
            </body>
        </html>
        """
        mock.status_code = 200
        mock.raise_for_status = MagicMock()
        return mock

    @pytest.fixture
    def mock_client(self, mock_response):
        """Create a mock httpx Client."""
        client = MagicMock()
        client.get.return_value = mock_response
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    def test_fetch_single_selector(self, scraping_config: SourceConfig, mock_client):
        source = ScrapingSource(scraping_config)

        with patch("httpx.Client", return_value=mock_client):
            result = source.fetch(
                url="https://example.com",
                selectors={"title": "div.item"},
                multiple=False,
            )

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 1
        assert "Item 1" in result.records[0].data["title"]

    def test_fetch_multiple_items(self, scraping_config: SourceConfig, mock_client):
        source = ScrapingSource(scraping_config)

        with patch("httpx.Client", return_value=mock_client):
            result = source.fetch(
                url="https://example.com",
                selectors={"item": "div.item"},
                multiple=True,
            )

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 2

    def test_fetch_with_attrs(self, scraping_config: SourceConfig, mock_client):
        source = ScrapingSource(scraping_config)

        with patch("httpx.Client", return_value=mock_client):
            result = source.fetch(
                url="https://example.com",
                selectors={"link": "a"},
                attrs={"link": "href"},
                multiple=False,
            )

        assert result.status == FetchStatus.SUCCESS
        assert "https://example.com/link" in result.records[0].data["link"]

    def test_fetch_missing_url(self, scraping_config: SourceConfig):
        source = ScrapingSource(scraping_config)
        result = source.fetch(selectors={"x": "div"})

        assert result.status == FetchStatus.FAILED
        assert "No URL" in result.error

    def test_fetch_missing_selectors(self, scraping_config: SourceConfig):
        source = ScrapingSource(scraping_config)
        result = source.fetch(url="https://example.com")

        assert result.status == FetchStatus.FAILED
        assert "No selectors" in result.error

    def test_fetch_http_error(self, scraping_config: SourceConfig):
        source = ScrapingSource(scraping_config)

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            result = source.fetch(url="https://example.com", selectors={"x": "div"})

        assert result.status == FetchStatus.FAILED
        assert "Connection refused" in result.error

    def test_test_connection(self, scraping_config: SourceConfig):
        source = ScrapingSource(scraping_config)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            assert source.test_connection() is True

    def test_test_connection_failure(self, scraping_config: SourceConfig):
        source = ScrapingSource(scraping_config)

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            assert source.test_connection() is False
