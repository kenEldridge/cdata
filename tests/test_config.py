"""Tests for cdata.config.schema."""

import pytest
from pydantic import ValidationError

from cdata.config.schema import (
    StorageBackend,
    ScheduleType,
    ScheduleConfig,
    StorageConfig,
    SourceConfig,
    JobConfig,
    FavoriteEntity,
    FavoritesConfig,
    SourcesFile,
    JobsFile,
)


class TestStorageBackend:
    """Tests for StorageBackend enum."""

    def test_backend_values(self):
        assert StorageBackend.PARQUET.value == "parquet"
        assert StorageBackend.CSV.value == "csv"
        assert StorageBackend.JSON.value == "json"


class TestScheduleType:
    """Tests for ScheduleType enum."""

    def test_schedule_types(self):
        assert ScheduleType.CRON.value == "cron"
        assert ScheduleType.INTERVAL.value == "interval"


class TestScheduleConfig:
    """Tests for ScheduleConfig model."""

    def test_cron_schedule(self):
        schedule = ScheduleConfig(
            type=ScheduleType.CRON,
            expression="0 18 * * 1-5",
        )
        assert schedule.type == ScheduleType.CRON
        assert schedule.expression == "0 18 * * 1-5"

    def test_interval_schedule_hours(self):
        schedule = ScheduleConfig(
            type=ScheduleType.INTERVAL,
            hours=2,
        )
        assert schedule.type == ScheduleType.INTERVAL
        assert schedule.hours == 2

    def test_interval_schedule_minutes(self):
        schedule = ScheduleConfig(
            type=ScheduleType.INTERVAL,
            minutes=30,
        )
        assert schedule.minutes == 30

    def test_interval_schedule_seconds(self):
        schedule = ScheduleConfig(
            type=ScheduleType.INTERVAL,
            seconds=300,
        )
        assert schedule.seconds == 300


class TestStorageConfig:
    """Tests for StorageConfig model."""

    def test_default_storage(self):
        config = StorageConfig()
        assert config.backend == StorageBackend.PARQUET
        assert config.path is None
        assert config.partition_by is None

    def test_csv_storage_with_path(self):
        config = StorageConfig(
            backend=StorageBackend.CSV,
            path="/custom/path",
        )
        assert config.backend == StorageBackend.CSV
        assert config.path == "/custom/path"

    def test_partitioned_storage(self):
        config = StorageConfig(
            backend=StorageBackend.PARQUET,
            partition_by=["date", "symbol"],
        )
        assert config.partition_by == ["date", "symbol"]


class TestSourceConfig:
    """Tests for SourceConfig model."""

    def test_minimal_source(self):
        config = SourceConfig(
            id="my_source",
            name="My Source",
            type="rss",
        )
        assert config.id == "my_source"
        assert config.enabled is True
        assert config.config == {}

    def test_full_source(self):
        config = SourceConfig(
            id="stocks",
            name="Stock Data",
            type="yfinance",
            enabled=True,
            config={"symbols": ["AAPL", "GOOGL"], "period": "1y"},
            description="Daily stock prices",
        )
        assert config.type == "yfinance"
        assert config.config["symbols"] == ["AAPL", "GOOGL"]
        assert config.description == "Daily stock prices"

    def test_disabled_source(self):
        config = SourceConfig(
            id="test",
            name="Test",
            type="test",
            enabled=False,
        )
        assert config.enabled is False

    def test_source_requires_id(self):
        with pytest.raises(ValidationError):
            SourceConfig(name="Test", type="rss")  # type: ignore

    def test_source_requires_name(self):
        with pytest.raises(ValidationError):
            SourceConfig(id="test", type="rss")  # type: ignore

    def test_source_requires_type(self):
        with pytest.raises(ValidationError):
            SourceConfig(id="test", name="Test")  # type: ignore


class TestJobConfig:
    """Tests for JobConfig model."""

    def test_minimal_job(self):
        config = JobConfig(
            id="job1",
            source="source1",
        )
        assert config.id == "job1"
        assert config.source == "source1"
        assert config.enabled is True
        assert config.schedule is None
        assert config.storage.backend == StorageBackend.PARQUET

    def test_scheduled_job(self):
        config = JobConfig(
            id="daily_stocks",
            source="yfinance",
            schedule=ScheduleConfig(
                type=ScheduleType.CRON,
                expression="0 18 * * 1-5",
            ),
        )
        assert config.schedule is not None
        assert config.schedule.type == ScheduleType.CRON

    def test_job_with_custom_storage(self):
        config = JobConfig(
            id="job1",
            source="source1",
            storage=StorageConfig(
                backend=StorageBackend.JSON,
                path="/custom/path",
            ),
        )
        assert config.storage.backend == StorageBackend.JSON


class TestFavoriteEntity:
    """Tests for FavoriteEntity model."""

    def test_minimal_favorite(self):
        fav = FavoriteEntity(
            id="aapl",
            name="Apple Inc.",
        )
        assert fav.id == "aapl"
        assert fav.sources == []
        assert fav.metadata == {}

    def test_favorite_with_sources(self):
        fav = FavoriteEntity(
            id="btc",
            name="Bitcoin",
            sources=["yfinance", "coinbase"],
            metadata={"symbol": "BTC-USD", "category": "crypto"},
        )
        assert "yfinance" in fav.sources
        assert fav.metadata["category"] == "crypto"


class TestFavoritesConfig:
    """Tests for FavoritesConfig model."""

    def test_empty_favorites(self):
        config = FavoritesConfig()
        assert config.entities == []

    def test_favorites_with_entities(self):
        config = FavoritesConfig(
            entities=[
                FavoriteEntity(id="aapl", name="Apple"),
                FavoriteEntity(id="googl", name="Google"),
            ]
        )
        assert len(config.entities) == 2


class TestSourcesFile:
    """Tests for SourcesFile model."""

    def test_empty_sources_file(self):
        file = SourcesFile()
        assert file.sources == []

    def test_sources_file_with_sources(self):
        file = SourcesFile(
            sources=[
                SourceConfig(id="s1", name="Source 1", type="rss"),
                SourceConfig(id="s2", name="Source 2", type="yfinance"),
            ]
        )
        assert len(file.sources) == 2


class TestJobsFile:
    """Tests for JobsFile model."""

    def test_empty_jobs_file(self):
        file = JobsFile()
        assert file.jobs == []

    def test_jobs_file_with_jobs(self):
        file = JobsFile(
            jobs=[
                JobConfig(id="j1", source="s1"),
                JobConfig(id="j2", source="s2"),
            ]
        )
        assert len(file.jobs) == 2
