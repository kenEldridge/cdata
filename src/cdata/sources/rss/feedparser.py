"""RSS/Atom feed source using feedparser."""

from datetime import datetime
from typing import Any
from time import mktime

import feedparser

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class RSSSource(BaseSource):
    """RSS/Atom feed data source."""

    source_type = "rss"

    def __init__(self, config: SourceConfig):
        super().__init__(config)

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch items from RSS/Atom feeds.

        Args:
            feeds: List of feed configs with 'name' and 'url' keys
            url: Single feed URL (alternative to feeds)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        feeds = kwargs.get("feeds", [])
        single_url = kwargs.get("url")

        if single_url:
            feeds = [{"name": "feed", "url": single_url}]

        for feed_config in feeds:
            feed_name = feed_config.get("name", "unknown")
            feed_url = feed_config.get("url")

            if not feed_url:
                errors.append(f"No URL for feed: {feed_name}")
                continue

            try:
                parsed = feedparser.parse(feed_url)

                if parsed.bozo and parsed.bozo_exception:
                    errors.append(f"Parse error for {feed_name}: {parsed.bozo_exception}")

                for entry in parsed.entries:
                    published = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime.fromtimestamp(mktime(entry.published_parsed))
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        published = datetime.fromtimestamp(mktime(entry.updated_parsed))

                    record = self._create_record(
                        data={
                            "feed_name": feed_name,
                            "feed_url": feed_url,
                            "title": getattr(entry, "title", ""),
                            "link": getattr(entry, "link", ""),
                            "summary": getattr(entry, "summary", ""),
                            "author": getattr(entry, "author", None),
                            "published": published.isoformat() if published else None,
                            "id": getattr(entry, "id", getattr(entry, "link", "")),
                        },
                        metadata={"feed_title": parsed.feed.get("title", feed_name)},
                    )
                    records.append(record)

            except Exception as e:
                errors.append(f"Error fetching {feed_name}: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by parsing a known feed."""
        try:
            parsed = feedparser.parse("https://news.ycombinator.com/rss")
            return len(parsed.entries) > 0
        except Exception:
            return False
