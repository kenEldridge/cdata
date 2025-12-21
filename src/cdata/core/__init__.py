"""Core functionality for cdata."""

from cdata.core.registry import SourceRegistry, get_registry
from cdata.core.fetcher import Fetcher

__all__ = [
    "SourceRegistry",
    "get_registry",
    "Fetcher",
]
