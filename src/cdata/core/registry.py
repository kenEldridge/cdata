"""Plugin registry for data sources."""

import importlib.util
import inspect
import sys
from functools import lru_cache
from importlib.metadata import entry_points
from pathlib import Path
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
    from cdata.config.env import get_settings

    registry = SourceRegistry()
    _register_builtin_sources(registry)
    _load_custom_sources(registry, get_settings().sources_module_dir)
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

    try:
        from cdata.sources.api.financial.sec_edgar import SECEDGARSource
        registry.register("sec_edgar", SECEDGARSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.financial.nic_bhc import NICBHCSource
        registry.register("nic_bhc", NICBHCSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.geopolitics.acled import ACLEDSource
        registry.register("acled", ACLEDSource)
    except ImportError:
        pass

    try:
        from cdata.sources.api.geopolitics.gdelt import GDELTSource
        registry.register("gdelt", GDELTSource)
    except ImportError:
        pass


def _load_custom_sources(registry: SourceRegistry, sources_dir: Path) -> None:
    """Load custom source classes from a directory of .py files."""
    sources_dir = sources_dir.resolve()
    if not sources_dir.is_dir():
        return

    for py_file in sorted(sources_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = py_file.stem
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            continue

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            continue

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseSource)
                and obj is not BaseSource
                and hasattr(obj, "source_type")
                and obj.source_type != "base"
            ):
                registry.register(obj.source_type, obj)
