"""Dataset index/catalog management."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from cdata.config import get_settings


class DatasetEntry(BaseModel):
    """Metadata entry for a dataset in the index."""

    name: str
    source_id: str
    location: str  # "raw" or "processed"
    file_path: str
    format: str = "parquet"
    record_count: int
    file_size_bytes: int
    columns: list[str] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    first_fetched: datetime
    last_updated: datetime
    last_record_date: Optional[datetime] = None  # Most recent date in data (for incremental)
    fetch_count: int = 1
    description: Optional[str] = None


class DataIndex(BaseModel):
    """The full dataset index/catalog."""

    version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    datasets: dict[str, DatasetEntry] = Field(default_factory=dict)


class IndexManager:
    """Manages the dataset index."""

    def __init__(self, index_path: Optional[Path] = None):
        settings = get_settings()
        self.index_path = index_path or settings.data_dir / "index.json"
        self._index: Optional[DataIndex] = None

    def _load(self) -> DataIndex:
        """Load index from disk."""
        if self.index_path.exists():
            with open(self.index_path) as f:
                data = json.load(f)
                return DataIndex.model_validate(data)
        return DataIndex()

    def _save(self) -> None:
        """Save index to disk."""
        if self._index is None:
            return
        self._index.generated_at = datetime.utcnow()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "w") as f:
            json.dump(self._index.model_dump(mode="json"), f, indent=2, default=str)

    @property
    def index(self) -> DataIndex:
        """Get the current index, loading from disk if needed."""
        if self._index is None:
            self._index = self._load()
        return self._index

    def update_dataset(
        self,
        name: str,
        source_id: str,
        location: str,
        file_path: Path,
        record_count: int,
        columns: list[str],
        description: Optional[str] = None,
        primary_keys: Optional[list[str]] = None,
        last_record_date: Optional[datetime] = None,
    ) -> DatasetEntry:
        """Update or create a dataset entry in the index."""
        now = datetime.utcnow()
        file_size = file_path.stat().st_size if file_path.exists() else 0

        key = f"{location}/{name}"
        existing = self.index.datasets.get(key)

        if existing:
            entry = DatasetEntry(
                name=name,
                source_id=source_id,
                location=location,
                file_path=str(file_path),
                record_count=record_count,
                file_size_bytes=file_size,
                columns=columns,
                primary_keys=primary_keys or existing.primary_keys,
                first_fetched=existing.first_fetched,
                last_updated=now,
                last_record_date=last_record_date or existing.last_record_date,
                fetch_count=existing.fetch_count + 1,
                description=description or existing.description,
            )
        else:
            entry = DatasetEntry(
                name=name,
                source_id=source_id,
                location=location,
                file_path=str(file_path),
                record_count=record_count,
                file_size_bytes=file_size,
                columns=columns,
                primary_keys=primary_keys or [],
                first_fetched=now,
                last_updated=now,
                last_record_date=last_record_date,
                fetch_count=1,
                description=description,
            )

        self.index.datasets[key] = entry
        self._save()
        return entry

    def remove_dataset(self, name: str, location: str = "raw") -> bool:
        """Remove a dataset from the index."""
        key = f"{location}/{name}"
        if key in self.index.datasets:
            del self.index.datasets[key]
            self._save()
            return True
        return False

    def get_dataset(self, name: str, location: str = "raw") -> Optional[DatasetEntry]:
        """Get a dataset entry by name."""
        key = f"{location}/{name}"
        return self.index.datasets.get(key)

    def list_datasets(self, location: Optional[str] = None) -> list[DatasetEntry]:
        """List all datasets, optionally filtered by location."""
        entries = list(self.index.datasets.values())
        if location:
            entries = [e for e in entries if e.location == location]
        return sorted(entries, key=lambda e: e.last_updated, reverse=True)

    def rebuild(self) -> int:
        """Rebuild the index by scanning data directories."""
        import pandas as pd
        from cdata.config import load_sources

        settings = get_settings()
        sources = {s.id: s for s in load_sources()}

        # Clear existing index
        self._index = DataIndex()
        count = 0

        for location, data_dir in [("raw", settings.raw_data_dir), ("processed", settings.processed_data_dir)]:
            if not data_dir.exists():
                continue

            for parquet_file in data_dir.glob("*.parquet"):
                name = parquet_file.stem
                try:
                    df = pd.read_parquet(parquet_file)
                    source_config = sources.get(name)

                    # Get primary keys from source config
                    primary_keys = source_config.primary_keys if source_config else None

                    # Compute last record date
                    last_record_date = self._compute_last_record_date(df)

                    self.update_dataset(
                        name=name,
                        source_id=name,
                        location=location,
                        file_path=parquet_file,
                        record_count=len(df),
                        columns=list(df.columns),
                        description=source_config.description if source_config else None,
                        primary_keys=primary_keys,
                        last_record_date=last_record_date,
                    )
                    count += 1
                except Exception:
                    continue

        return count

    def _compute_last_record_date(self, df: "pd.DataFrame") -> Optional[datetime]:
        """Extract the most recent date from the data."""
        import pandas as pd

        if df.empty:
            return None

        # Look for common date columns
        date_columns = ["date", "published", "timestamp", "created_at", "_fetched_at"]

        for col in date_columns:
            if col in df.columns:
                try:
                    dates = pd.to_datetime(df[col], errors="coerce")
                    max_date = dates.max()
                    if pd.notna(max_date):
                        return max_date.to_pydatetime()
                except Exception:
                    continue

        return None


def get_index_manager() -> IndexManager:
    """Get the global index manager."""
    return IndexManager()
