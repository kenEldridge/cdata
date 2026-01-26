"""Plugin registry for data sources."""

from functools import lru_cache
from importlib.metadata import entry_points
from typing import Optional, Type

from cdata.config.schema import SourceConfig
from cdata.sources.base import BaseSource


class SourceRegistry:
    """Registry for discovering and instantiating data sources."""

    def __init__(self):
        self._sources: dict[str, Type[BaseSource]] = {}
        self._loaded = False

    def register(self, source_type: str, source_class: Type[BaseSource]) -> None:
        """Register a source class."""
        self._sources[source_type] = source_class

    def _load_entry_points(self) -> None:
        """Load sources from entry points."""
        if self._loaded:
            return

        try:
            eps = entry_points(group="cdata.sources")
            for ep in eps:
                try:
                    source_class = ep.load()
                    self._sources[ep.name] = source_class
                except Exception:
                    pass
        except Exception:
            pass

        self._loaded = True

    def get_source_class(self, source_type: str) -> Optional[Type[BaseSource]]:
        """Get a source class by type."""
        self._load_entry_points()
        return self._sources.get(source_type)

    def create_source(self, config: SourceConfig) -> Optional[BaseSource]:
        """Create a source instance from config."""
        source_class = self.get_source_class(config.type)
        if source_class is None:
            return None
        return source_class(config)

    def list_source_types(self) -> list[str]:
        """List all registered source types."""
        self._load_entry_points()
        return sorted(self._sources.keys())

    def is_registered(self, source_type: str) -> bool:
        """Check if a source type is registered."""
        self._load_entry_points()
        return source_type in self._sources


@lru_cache
def get_registry() -> SourceRegistry:
    """Get the global source registry."""
    registry = SourceRegistry()
    _register_builtin_sources(registry)
    return registry


def _register_builtin_sources(registry: SourceRegistry) -> None:
    """Register built-in sources directly."""
    try:
        from cdata.sources.api.financial.yfinance import YFinanceSource
        registry.register("yfinance", YFinanceSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.financial.fred import FREDSource
        registry.register("fred", FREDSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.financial.bls import BLSSource
        registry.register("bls", BLSSource)
    except ImportError:
        pass

    try:
        from cdata.sources.rss.feedparser import RSSSource
        registry.register("rss", RSSSource)
    except ImportError:
        pass

    try:
        from cdata.sources.linked_data.sparql import SPARQLSource
        registry.register("sparql", SPARQLSource)
    except ImportError:
        pass

    try:
        from cdata.sources.scraping.generic import ScrapingSource
        registry.register("scraping", ScrapingSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.financial.fed_stress import FedStressSource
        registry.register("fed_stress", FedStressSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.financial.ffiec import FFIECSource
        registry.register("ffiec", FFIECSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.sports.espn_cbb import ESPNCBBSource
        registry.register("espn_cbb", ESPNCBBSource)
    except ImportError:
        pass
