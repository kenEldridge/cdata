"""Pydantic schemas for configuration files."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class StorageBackend(str, Enum):
    """Storage backend types."""

    PARQUET = "parquet"
    CSV = "csv"
    JSON = "json"


class ScheduleType(str, Enum):
    """Schedule types for jobs."""

    CRON = "cron"
    INTERVAL = "interval"


class ScheduleConfig(BaseModel):
    """Schedule configuration for a job."""

    type: ScheduleType
    expression: Optional[str] = None  # For cron
    seconds: Optional[int] = None  # For interval
    minutes: Optional[int] = None
    hours: Optional[int] = None


class StorageConfig(BaseModel):
    """Storage configuration for a job."""

    backend: StorageBackend = StorageBackend.PARQUET
    path: Optional[str] = None
    partition_by: Optional[list[str]] = None


class SourceConfig(BaseModel):
    """Configuration for a data source."""

    id: str
    name: str
    type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class JobConfig(BaseModel):
    """Configuration for a scheduled fetch job."""

    id: str
    source: str
    enabled: bool = True
    schedule: Optional[ScheduleConfig] = None
    storage: StorageConfig = Field(default_factory=StorageConfig)
    description: Optional[str] = None


class FavoriteEntity(BaseModel):
    """A tracked favorite entity."""

    id: str
    name: str
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FavoritesConfig(BaseModel):
    """Configuration for tracked favorites."""

    entities: list[FavoriteEntity] = Field(default_factory=list)


class SourcesFile(BaseModel):
    """Schema for sources YAML file."""

    sources: list[SourceConfig] = Field(default_factory=list)


class JobsFile(BaseModel):
    """Schema for jobs YAML file."""

    jobs: list[JobConfig] = Field(default_factory=list)
