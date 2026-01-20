"""Tests for cdata.storage backends."""

from pathlib import Path

import pandas as pd
import pytest

from cdata.models import Record
from cdata.storage.parquet import ParquetStorage
from cdata.storage.csv import CSVStorage
from cdata.storage.json import JSONStorage


class TestParquetStorage:
    """Tests for ParquetStorage backend."""

    def test_extension(self, temp_dir: Path):
        storage = ParquetStorage(temp_dir)
        assert storage.extension == "parquet"

    def test_write_and_read(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_records, "test_data")

        df = storage.read("test_data")
        assert len(df) == 3
        assert "name" in df.columns
        assert "_source_id" in df.columns
        assert "_fetched_at" in df.columns

    def test_write_empty_records(self, temp_dir: Path):
        storage = ParquetStorage(temp_dir)
        path = storage.write([], "empty")
        assert not (temp_dir / "empty.parquet").exists()

    def test_read_nonexistent(self, temp_dir: Path):
        storage = ParquetStorage(temp_dir)
        df = storage.read("nonexistent")
        assert df.empty

    def test_append(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_records[:2], "test_data")
        storage.append(sample_records[2:], "test_data")

        df = storage.read("test_data")
        assert len(df) == 3

    def test_append_to_nonexistent(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.append(sample_records, "new_data")

        df = storage.read("new_data")
        assert len(df) == 3

    def test_exists(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        assert not storage.exists("test_data")

        storage.write(sample_records, "test_data")
        assert storage.exists("test_data")

    def test_delete(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_records, "test_data")
        assert storage.exists("test_data")

        result = storage.delete("test_data")
        assert result is True
        assert not storage.exists("test_data")

    def test_delete_nonexistent(self, temp_dir: Path):
        storage = ParquetStorage(temp_dir)
        result = storage.delete("nonexistent")
        assert result is False

    def test_list_datasets(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_records, "data1")
        storage.write(sample_records, "data2")

        datasets = storage.list_datasets()
        assert "data1" in datasets
        assert "data2" in datasets

    def test_write_with_partition(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_partitioned_records, "partitioned", partition_by=["category"])

        assert (temp_dir / "partitioned").is_dir()
        df = storage.read("partitioned")
        assert len(df) == 4

    def test_read_with_filter(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        storage.write(sample_partitioned_records, "partitioned", partition_by=["category"])

        df = storage.read("partitioned", filters={"category": "A"})
        assert len(df) == 2
        assert all(df["category"] == "A")


class TestCSVStorage:
    """Tests for CSVStorage backend."""

    def test_extension(self, temp_dir: Path):
        storage = CSVStorage(temp_dir)
        assert storage.extension == "csv"

    def test_write_and_read(self, temp_dir: Path, sample_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_records, "test_data")

        df = storage.read("test_data")
        assert len(df) == 3
        assert "name" in df.columns

    def test_write_empty_records(self, temp_dir: Path):
        storage = CSVStorage(temp_dir)
        path = storage.write([], "empty")
        assert not (temp_dir / "empty.csv").exists()

    def test_read_nonexistent(self, temp_dir: Path):
        storage = CSVStorage(temp_dir)
        df = storage.read("nonexistent")
        assert df.empty

    def test_append(self, temp_dir: Path, sample_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_records[:2], "test_data")
        storage.append(sample_records[2:], "test_data")

        df = storage.read("test_data")
        assert len(df) == 3

    def test_exists(self, temp_dir: Path, sample_records: list[Record]):
        storage = CSVStorage(temp_dir)
        assert not storage.exists("test_data")

        storage.write(sample_records, "test_data")
        assert storage.exists("test_data")

    def test_delete(self, temp_dir: Path, sample_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_records, "test_data")

        result = storage.delete("test_data")
        assert result is True
        assert not storage.exists("test_data")

    def test_list_datasets(self, temp_dir: Path, sample_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_records, "data1")
        storage.write(sample_records, "data2")

        datasets = storage.list_datasets()
        assert "data1" in datasets
        assert "data2" in datasets

    def test_write_with_partition(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_partitioned_records, "partitioned", partition_by=["category"])

        assert (temp_dir / "partitioned").is_dir()
        df = storage.read("partitioned")
        assert len(df) == 4

    def test_read_with_filter(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = CSVStorage(temp_dir)
        storage.write(sample_partitioned_records, "test_filter")

        df = storage.read("test_filter", filters={"category": "A"})
        assert len(df) == 2


class TestJSONStorage:
    """Tests for JSONStorage backend."""

    def test_extension(self, temp_dir: Path):
        storage = JSONStorage(temp_dir)
        assert storage.extension == "json"

    def test_write_and_read(self, temp_dir: Path, sample_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_records, "test_data")

        df = storage.read("test_data")
        assert len(df) == 3
        assert "name" in df.columns

    def test_write_empty_records(self, temp_dir: Path):
        storage = JSONStorage(temp_dir)
        path = storage.write([], "empty")
        assert not (temp_dir / "empty.json").exists()

    def test_read_nonexistent(self, temp_dir: Path):
        storage = JSONStorage(temp_dir)
        df = storage.read("nonexistent")
        assert df.empty

    def test_append(self, temp_dir: Path, sample_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_records[:2], "test_data")
        storage.append(sample_records[2:], "test_data")

        df = storage.read("test_data")
        assert len(df) == 3

    def test_exists(self, temp_dir: Path, sample_records: list[Record]):
        storage = JSONStorage(temp_dir)
        assert not storage.exists("test_data")

        storage.write(sample_records, "test_data")
        assert storage.exists("test_data")

    def test_delete(self, temp_dir: Path, sample_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_records, "test_data")

        result = storage.delete("test_data")
        assert result is True
        assert not storage.exists("test_data")

    def test_list_datasets(self, temp_dir: Path, sample_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_records, "data1")
        storage.write(sample_records, "data2")

        datasets = storage.list_datasets()
        assert "data1" in datasets
        assert "data2" in datasets

    def test_write_with_partition(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_partitioned_records, "partitioned", partition_by=["category"])

        assert (temp_dir / "partitioned").is_dir()
        df = storage.read("partitioned")
        assert len(df) == 4

    def test_read_with_filter(self, temp_dir: Path, sample_partitioned_records: list[Record]):
        storage = JSONStorage(temp_dir)
        storage.write(sample_partitioned_records, "test_filter")

        df = storage.read("test_filter", filters={"category": "B"})
        assert len(df) == 2


class TestStorageRecordsToDataframe:
    """Tests for _records_to_dataframe conversion."""

    def test_empty_records(self, temp_dir: Path):
        storage = ParquetStorage(temp_dir)
        df = storage._records_to_dataframe([])
        assert df.empty

    def test_records_include_metadata_columns(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        df = storage._records_to_dataframe(sample_records)

        assert "_source_id" in df.columns
        assert "_fetched_at" in df.columns
        assert all(df["_source_id"] == "test_source")

    def test_records_data_flattened(self, temp_dir: Path, sample_records: list[Record]):
        storage = ParquetStorage(temp_dir)
        df = storage._records_to_dataframe(sample_records)

        assert "name" in df.columns
        assert "value" in df.columns
        assert list(df["name"]) == ["Alice", "Bob", "Charlie"]
