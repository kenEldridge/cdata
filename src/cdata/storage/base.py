"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from cdata.models import Record


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def extension(self) -> str:
        """File extension for this storage type."""
        ...

    @abstractmethod
    def write(
        self,
        records: list[Record],
        name: str,
        partition_by: Optional[list[str]] = None,
    ) -> Path:
        """Write records to storage.

        Args:
            records: List of records to write
            name: Dataset name
            partition_by: Optional columns to partition by

        Returns:
            Path to written data
        """
        ...

    @abstractmethod
    def read(
        self,
        name: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame:
        """Read data from storage.

        Args:
            name: Dataset name
            filters: Optional filters to apply

        Returns:
            DataFrame with the data
        """
        ...

    @abstractmethod
    def append(
        self,
        records: list[Record],
        name: str,
        primary_keys: Optional[list[str]] = None,
    ) -> Path:
        """Append records to existing data.

        Args:
            records: List of records to append
            name: Dataset name
            primary_keys: Columns for deduplication

        Returns:
            Path to data
        """
        ...

    def exists(self, name: str) -> bool:
        """Check if a dataset exists."""
        path = self.base_path / f"{name}.{self.extension}"
        return path.exists() or (self.base_path / name).exists()

    def delete(self, name: str) -> bool:
        """Delete a dataset."""
        path = self.base_path / f"{name}.{self.extension}"
        if path.exists():
            path.unlink()
            return True
        dir_path = self.base_path / name
        if dir_path.exists():
            import shutil
            shutil.rmtree(dir_path)
            return True
        return False

    def list_datasets(self) -> list[str]:
        """List all datasets in storage."""
        datasets = []
        for path in self.base_path.iterdir():
            if path.is_file() and path.suffix == f".{self.extension}":
                datasets.append(path.stem)
            elif path.is_dir() and not path.name.startswith("."):
                datasets.append(path.name)
        return sorted(datasets)

    def _records_to_dataframe(self, records: list[Record]) -> pd.DataFrame:
        """Convert records to a DataFrame."""
        if not records:
            return pd.DataFrame()

        rows = []
        for record in records:
            row = {
                "_source_id": record.source_id,
                "_fetched_at": record.fetched_at,
                **record.data,
            }
            rows.append(row)

        return pd.DataFrame(rows)

    def _deduplicate(
        self,
        df: pd.DataFrame,
        primary_keys: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """Deduplicate DataFrame, keeping the most recent record.

        Args:
            df: DataFrame to deduplicate
            primary_keys: Columns that define uniqueness. If None, no dedup.

        Returns:
            Deduplicated DataFrame
        """
        if df.empty or not primary_keys:
            return df

        # Check that all primary keys exist in the dataframe
        missing_keys = [k for k in primary_keys if k not in df.columns]
        if missing_keys:
            return df

        # Sort by _fetched_at descending so we keep the most recent
        if "_fetched_at" in df.columns:
            df = df.sort_values("_fetched_at", ascending=False)

        # Drop duplicates, keeping first (most recent)
        df = df.drop_duplicates(subset=primary_keys, keep="first")

        # Re-sort by primary keys for consistent ordering
        df = df.sort_values(primary_keys).reset_index(drop=True)

        return df
