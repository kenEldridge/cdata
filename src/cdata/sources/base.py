"""Abstract base class for data sources."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, FetchStatus, Record


class BaseSource(ABC):
    """Abstract base class for all data sources."""

    source_type: str = "base"

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.id

    @abstractmethod
    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch data from the source.

        Args:
            **kwargs: Source-specific fetch parameters

        Returns:
            FetchResult containing the fetched records
        """
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Test connectivity to the source.

        Returns:
            True if connection is successful
        """
        ...

    def _create_result(
        self,
        records: list[Record],
        started_at: datetime,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> FetchResult:
        """Helper to create a FetchResult."""
        status = FetchStatus.SUCCESS if not error else FetchStatus.FAILED
        if error and records:
            status = FetchStatus.PARTIAL

        return FetchResult(
            source_id=self.source_id,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            records=records,
            record_count=len(records),
            error=error,
            metadata=metadata or {},
        )

    def _create_record(self, data: dict[str, Any], metadata: Optional[dict[str, Any]] = None) -> Record:
        """Helper to create a Record."""
        return Record(
            source_id=self.source_id,
            data=data,
            metadata=metadata or {},
        )
