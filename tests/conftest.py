"""Pytest fixtures for cdata tests."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest

from cdata.config.schema import SourceConfig, JobConfig, ScheduleConfig, ScheduleType, StorageConfig
from cdata.models import Record, FetchResult, FetchStatus


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_records() -> list[Record]:
    """Create sample records for testing."""
    return [
        Record(
            source_id="test_source",
            fetched_at=datetime(2025, 1, 1, 12, 0, 0),
            data={"name": "Alice", "value": 100},
            metadata={"batch": 1},
        ),
        Record(
            source_id="test_source",
            fetched_at=datetime(2025, 1, 1, 12, 0, 1),
            data={"name": "Bob", "value": 200},
            metadata={"batch": 1},
        ),
        Record(
            source_id="test_source",
            fetched_at=datetime(2025, 1, 1, 12, 0, 2),
            data={"name": "Charlie", "value": 300},
            metadata={"batch": 1},
        ),
    ]


@pytest.fixture
def sample_partitioned_records() -> list[Record]:
    """Create sample records with partition keys."""
    return [
        Record(
            source_id="test_source",
            data={"category": "A", "name": "Item1", "value": 10},
        ),
        Record(
            source_id="test_source",
            data={"category": "A", "name": "Item2", "value": 20},
        ),
        Record(
            source_id="test_source",
            data={"category": "B", "name": "Item3", "value": 30},
        ),
        Record(
            source_id="test_source",
            data={"category": "B", "name": "Item4", "value": 40},
        ),
    ]


@pytest.fixture
def sample_source_config() -> SourceConfig:
    """Create a sample source configuration."""
    return SourceConfig(
        id="test_source",
        name="Test Source",
        type="rss",
        enabled=True,
        config={"url": "https://example.com/feed.xml"},
        description="A test source",
    )


@pytest.fixture
def sample_job_config() -> JobConfig:
    """Create a sample job configuration."""
    return JobConfig(
        id="test_job",
        source="test_source",
        enabled=True,
        schedule=ScheduleConfig(
            type=ScheduleType.INTERVAL,
            hours=1,
        ),
        storage=StorageConfig(),
        description="A test job",
    )


@pytest.fixture
def sample_fetch_result(sample_records: list[Record]) -> FetchResult:
    """Create a sample fetch result."""
    return FetchResult(
        source_id="test_source",
        status=FetchStatus.SUCCESS,
        started_at=datetime(2025, 1, 1, 12, 0, 0),
        completed_at=datetime(2025, 1, 1, 12, 0, 5),
        records=sample_records,
    )
