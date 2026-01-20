"""Tests for cdata.core modules."""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cdata.config.schema import (
    JobConfig,
    ScheduleConfig,
    ScheduleType,
    SourceConfig,
    StorageBackend as StorageBackendEnum,
    StorageConfig,
)
from cdata.core.registry import SourceRegistry
from cdata.models import FetchResult, FetchStatus, Record
from cdata.sources.base import BaseSource


class MockSource(BaseSource):
    """Mock source for testing."""

    source_type = "mock"

    def fetch(self, **kwargs: Any) -> FetchResult:
        started_at = datetime.utcnow()
        count = kwargs.get("count", 2)
        records = [
            self._create_record({"item": i, "value": i * 10})
            for i in range(count)
        ]
        return self._create_result(records, started_at)

    def test_connection(self) -> bool:
        return True


class FailingSource(BaseSource):
    """Source that always fails for testing."""

    source_type = "failing"

    def fetch(self, **kwargs: Any) -> FetchResult:
        started_at = datetime.utcnow()
        return self._create_result([], started_at, error="Always fails")

    def test_connection(self) -> bool:
        return False


class TestSourceRegistry:
    """Tests for SourceRegistry."""

    def test_register_and_get(self):
        registry = SourceRegistry()
        registry.register("mock", MockSource)

        cls = registry.get_source_class("mock")
        assert cls is MockSource

    def test_get_unregistered(self):
        registry = SourceRegistry()
        cls = registry.get_source_class("nonexistent")
        assert cls is None

    def test_create_source(self):
        registry = SourceRegistry()
        registry.register("mock", MockSource)

        config = SourceConfig(id="test", name="Test", type="mock")
        source = registry.create_source(config)

        assert source is not None
        assert isinstance(source, MockSource)

    def test_create_source_unknown_type(self):
        registry = SourceRegistry()
        config = SourceConfig(id="test", name="Test", type="unknown")
        source = registry.create_source(config)

        assert source is None

    def test_list_source_types(self):
        registry = SourceRegistry()
        registry.register("mock", MockSource)
        registry.register("failing", FailingSource)

        types = registry.list_source_types()
        assert "mock" in types
        assert "failing" in types

    def test_is_registered(self):
        registry = SourceRegistry()
        registry.register("mock", MockSource)

        assert registry.is_registered("mock") is True
        assert registry.is_registered("nonexistent") is False


class TestFetcher:
    """Tests for Fetcher class."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry."""
        registry = SourceRegistry()
        registry.register("mock", MockSource)
        registry.register("failing", FailingSource)
        return registry

    @pytest.fixture
    def mock_sources(self) -> list[SourceConfig]:
        """Create mock source configs."""
        return [
            SourceConfig(id="source1", name="Source 1", type="mock", config={"count": 3}),
            SourceConfig(id="source2", name="Source 2", type="mock", config={"count": 5}),
            SourceConfig(id="fail_source", name="Failing", type="failing"),
        ]

    @pytest.fixture
    def mock_jobs(self) -> list[JobConfig]:
        """Create mock job configs."""
        return [
            JobConfig(
                id="job1",
                source="source1",
                schedule=ScheduleConfig(type=ScheduleType.INTERVAL, hours=1),
                storage=StorageConfig(backend=StorageBackendEnum.PARQUET),
            ),
            JobConfig(
                id="job2",
                source="source2",
            ),
        ]

    def test_fetch_source(self, mock_registry, mock_sources, temp_dir: Path):
        """Test fetching from a source by ID."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir
        mock_settings.config_dir = temp_dir
        mock_settings.sources_config_dir = temp_dir / "sources"
        mock_settings.jobs_config_dir = temp_dir / "jobs"

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=mock_sources):

            fetcher = Fetcher()
            result = fetcher.fetch_source("source1", save=False)

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 3

    def test_fetch_source_not_found(self, mock_registry, temp_dir: Path):
        """Test fetching from nonexistent source."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=[]):

            fetcher = Fetcher()
            result = fetcher.fetch_source("nonexistent")

        assert result.status == FetchStatus.FAILED
        assert "not found" in result.error

    def test_fetch_source_config(self, mock_registry, temp_dir: Path):
        """Test fetching using source config directly."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        config = SourceConfig(id="direct", name="Direct", type="mock", config={"count": 4})

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            result = fetcher.fetch_source_config(config, save=False)

        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 4

    def test_fetch_source_config_unknown_type(self, mock_registry, temp_dir: Path):
        """Test fetching with unknown source type."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        config = SourceConfig(id="unknown", name="Unknown", type="unknown_type")

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            result = fetcher.fetch_source_config(config, save=False)

        assert result.status == FetchStatus.FAILED
        assert "Unknown source type" in result.error

    def test_fetch_source_with_save(self, mock_registry, mock_sources, temp_dir: Path):
        """Test fetching and saving data."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=mock_sources):

            fetcher = Fetcher()
            result = fetcher.fetch_source("source1", save=True)

        assert result.status == FetchStatus.SUCCESS
        assert (temp_dir / "source1.parquet").exists()

    def test_run_job(self, mock_registry, mock_sources, mock_jobs, temp_dir: Path):
        """Test running a job by ID."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=mock_sources), \
             patch("cdata.core.fetcher.load_jobs", return_value=mock_jobs):

            fetcher = Fetcher()
            result = fetcher.run_job("job1")

        assert result.status == FetchStatus.SUCCESS
        assert result.job_id == "job1"

    def test_run_job_not_found(self, mock_registry, temp_dir: Path):
        """Test running nonexistent job."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_jobs", return_value=[]):

            fetcher = Fetcher()
            result = fetcher.run_job("nonexistent")

        assert result.status == FetchStatus.FAILED
        assert "not found" in result.error

    def test_run_job_source_not_found(self, mock_registry, temp_dir: Path):
        """Test running job with missing source."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        jobs = [JobConfig(id="job1", source="missing_source")]

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_jobs", return_value=jobs), \
             patch("cdata.core.fetcher.load_sources", return_value=[]):

            fetcher = Fetcher()
            result = fetcher.run_job("job1")

        assert result.status == FetchStatus.FAILED
        assert "Source" in result.error and "not found" in result.error

    def test_test_source(self, mock_registry, mock_sources, temp_dir: Path):
        """Test testing a source connection."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=mock_sources):

            fetcher = Fetcher()
            assert fetcher.test_source("source1") is True

    def test_test_source_failing(self, mock_registry, mock_sources, temp_dir: Path):
        """Test testing a failing source connection."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=mock_sources):

            fetcher = Fetcher()
            assert fetcher.test_source("fail_source") is False

    def test_test_source_not_found(self, mock_registry, temp_dir: Path):
        """Test testing nonexistent source."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry), \
             patch("cdata.core.fetcher.load_sources", return_value=[]):

            fetcher = Fetcher()
            assert fetcher.test_source("nonexistent") is False

    def test_get_storage_parquet(self, mock_registry, temp_dir: Path):
        """Test getting parquet storage backend."""
        from cdata.core.fetcher import Fetcher
        from cdata.storage.parquet import ParquetStorage

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            storage = fetcher._get_storage(StorageBackendEnum.PARQUET)

        assert isinstance(storage, ParquetStorage)

    def test_get_storage_csv(self, mock_registry, temp_dir: Path):
        """Test getting CSV storage backend."""
        from cdata.core.fetcher import Fetcher
        from cdata.storage.csv import CSVStorage

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            storage = fetcher._get_storage(StorageBackendEnum.CSV)

        assert isinstance(storage, CSVStorage)

    def test_get_storage_json(self, mock_registry, temp_dir: Path):
        """Test getting JSON storage backend."""
        from cdata.core.fetcher import Fetcher
        from cdata.storage.json import JSONStorage

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            storage = fetcher._get_storage(StorageBackendEnum.JSON)

        assert isinstance(storage, JSONStorage)

    def test_get_storage_custom_path(self, mock_registry, temp_dir: Path):
        """Test getting storage with custom path."""
        from cdata.core.fetcher import Fetcher

        mock_settings = MagicMock()
        mock_settings.raw_data_dir = temp_dir

        custom_path = temp_dir / "custom"

        with patch("cdata.core.fetcher.get_settings", return_value=mock_settings), \
             patch("cdata.core.fetcher.get_registry", return_value=mock_registry):

            fetcher = Fetcher()
            storage = fetcher._get_storage(StorageBackendEnum.PARQUET, path=str(custom_path))

        assert storage.base_path == custom_path
