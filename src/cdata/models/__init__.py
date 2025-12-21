"""Data models for cdata."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class FetchStatus(str, Enum):
    """Status of a fetch operation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class Record(BaseModel):
    """A single data record from a source."""

    source_id: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchResult(BaseModel):
    """Result of a fetch operation."""

    source_id: str
    job_id: Optional[str] = None
    status: FetchStatus
    started_at: datetime
    completed_at: datetime
    records: list[Record] = Field(default_factory=list)
    record_count: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.records and self.record_count == 0:
            self.record_count = len(self.records)


class Dataset(BaseModel):
    """Metadata about a stored dataset."""

    name: str
    source_id: str
    path: str
    format: str
    created_at: datetime
    updated_at: datetime
    record_count: int
    size_bytes: int
    partitions: list[str] = Field(default_factory=list)


__all__ = [
    "FetchStatus",
    "Record",
    "FetchResult",
    "Dataset",
]
