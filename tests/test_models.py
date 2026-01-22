"""Tests for cdata.models."""

from datetime import datetime

import pytest

from cdata.models import FetchStatus, Record, FetchResult, Dataset


class TestFetchStatus:
    """Tests for FetchStatus enum."""

    def test_status_values(self):
        assert FetchStatus.SUCCESS.value == "success"
        assert FetchStatus.PARTIAL.value == "partial"
        assert FetchStatus.FAILED.value == "failed"

    def test_status_is_string(self):
        assert isinstance(FetchStatus.SUCCESS, str)
        assert FetchStatus.SUCCESS == "success"


class TestRecord:
    """Tests for Record model."""

    def test_create_basic_record(self):
        record = Record(
            source_id="test",
            data={"key": "value"},
        )
        assert record.source_id == "test"
        assert record.data == {"key": "value"}
        assert isinstance(record.fetched_at, datetime)
        assert record.metadata == {}

    def test_record_with_metadata(self):
        now = datetime(2025, 1, 15, 10, 30, 0)
        record = Record(
            source_id="test",
            fetched_at=now,
            data={"price": 100.50},
            metadata={"symbol": "AAPL"},
        )
        assert record.fetched_at == now
        assert record.metadata == {"symbol": "AAPL"}

    def test_record_with_nested_data(self):
        record = Record(
            source_id="test",
            data={
                "user": {"name": "Alice", "age": 30},
                "items": [1, 2, 3],
            },
        )
        assert record.data["user"]["name"] == "Alice"
        assert record.data["items"] == [1, 2, 3]


class TestFetchResult:
    """Tests for FetchResult model."""

    def test_create_success_result(self):
        now = datetime.utcnow()
        record = Record(source_id="test", data={"x": 1})
        result = FetchResult(
            source_id="test",
            status=FetchStatus.SUCCESS,
            started_at=now,
            completed_at=now,
            records=[record],
        )
        assert result.status == FetchStatus.SUCCESS
        assert result.record_count == 1
        assert result.error is None

    def test_record_count_auto_calculated(self):
        now = datetime.utcnow()
        records = [
            Record(source_id="test", data={"x": i})
            for i in range(5)
        ]
        result = FetchResult(
            source_id="test",
            status=FetchStatus.SUCCESS,
            started_at=now,
            completed_at=now,
            records=records,
        )
        assert result.record_count == 5

    def test_failed_result_with_error(self):
        now = datetime.utcnow()
        result = FetchResult(
            source_id="test",
            status=FetchStatus.FAILED,
            started_at=now,
            completed_at=now,
            error="Connection timeout",
        )
        assert result.status == FetchStatus.FAILED
        assert result.error == "Connection timeout"
        assert result.record_count == 0

    def test_partial_result(self):
        now = datetime.utcnow()
        records = [Record(source_id="test", data={"x": 1})]
        result = FetchResult(
            source_id="test",
            status=FetchStatus.PARTIAL,
            started_at=now,
            completed_at=now,
            records=records,
            error="Some items failed to fetch",
        )
        assert result.status == FetchStatus.PARTIAL
        assert result.record_count == 1
        assert result.error is not None

    def test_result_with_job_id(self):
        now = datetime.utcnow()
        result = FetchResult(
            source_id="test",
            job_id="daily_fetch",
            status=FetchStatus.SUCCESS,
            started_at=now,
            completed_at=now,
        )
        assert result.job_id == "daily_fetch"

    def test_result_metadata(self):
        now = datetime.utcnow()
        result = FetchResult(
            source_id="test",
            status=FetchStatus.SUCCESS,
            started_at=now,
            completed_at=now,
            metadata={"api_calls": 3, "rate_limited": False},
        )
        assert result.metadata["api_calls"] == 3


class TestDataset:
    """Tests for Dataset model."""

    def test_create_dataset(self):
        now = datetime.utcnow()
        dataset = Dataset(
            name="stocks",
            source_id="yfinance",
            path="/data/raw/stocks.parquet",
            format="parquet",
            created_at=now,
            updated_at=now,
            record_count=1000,
            size_bytes=50000,
        )
        assert dataset.name == "stocks"
        assert dataset.format == "parquet"
        assert dataset.record_count == 1000
        assert dataset.partitions == []

    def test_dataset_with_partitions(self):
        now = datetime.utcnow()
        dataset = Dataset(
            name="stocks_partitioned",
            source_id="yfinance",
            path="/data/raw/stocks_partitioned",
            format="parquet",
            created_at=now,
            updated_at=now,
            record_count=5000,
            size_bytes=200000,
            partitions=["symbol", "date"],
        )
        assert dataset.partitions == ["symbol", "date"]
