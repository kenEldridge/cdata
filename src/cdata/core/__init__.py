"""Core functionality for cdata."""

from cdata.core.registry import SourceRegistry, get_registry
from cdata.core.fetcher import Fetcher
from cdata.core.index import IndexManager, DataIndex, DatasetEntry, get_index_manager

__all__ = [
    "SourceRegistry",
    "get_registry",
    "Fetcher",
    "IndexManager",
    "DataIndex",
    "DatasetEntry",
    "get_index_manager",
]
