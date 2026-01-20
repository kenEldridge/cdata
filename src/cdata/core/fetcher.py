"""Fetch orchestrator."""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from cdata.config import get_settings, load_sources, load_jobs
from cdata.config.schema import JobConfig, SourceConfig, StorageBackend as StorageBackendEnum
from cdata.core.registry import get_registry
from cdata.core.index import get_index_manager
from cdata.models import FetchResult, FetchStatus
from cdata.storage import ParquetStorage, CSVStorage, JSONStorage
from cdata.storage.base import StorageBackend


console = Console()


class Fetcher:
    """Orchestrates data fetching and storage."""

    def __init__(self):
        self.settings = get_settings()
        self.registry = get_registry()
        self.index_manager = get_index_manager()

    def _get_storage(self, backend: StorageBackendEnum, path: Optional[str] = None) -> StorageBackend:
        """Get storage backend instance."""
        base_path = Path(path) if path else self.settings.raw_data_dir

        if backend == StorageBackendEnum.PARQUET:
            return ParquetStorage(base_path)
        elif backend == StorageBackendEnum.CSV:
            return CSVStorage(base_path)
        elif backend == StorageBackendEnum.JSON:
            return JSONStorage(base_path)
        else:
            return ParquetStorage(base_path)

    def fetch_source(
        self,
        source_id: str,
        save: bool = True,
        **kwargs: Any,
    ) -> FetchResult:
        """Fetch data from a source by ID."""
        sources = load_sources()
        source_config = next((s for s in sources if s.id == source_id), None)

        if source_config is None:
            return FetchResult(
                source_id=source_id,
                status=FetchStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error=f"Source '{source_id}' not found",
            )

        return self.fetch_source_config(source_config, save=save, **kwargs)

    def fetch_source_config(
        self,
        config: SourceConfig,
        save: bool = True,
        storage_backend: StorageBackendEnum = StorageBackendEnum.PARQUET,
        **kwargs: Any,
    ) -> FetchResult:
        """Fetch data using a source config."""
        source = self.registry.create_source(config)

        if source is None:
            return FetchResult(
                source_id=config.id,
                status=FetchStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error=f"Unknown source type: {config.type}",
            )

        merged_kwargs = {**config.config, **kwargs}

        # For incremental sources, pass the last record date
        if config.incremental:
            existing = self.index_manager.get_dataset(config.id, "raw")
            if existing and existing.last_record_date:
                merged_kwargs["since"] = existing.last_record_date

        result = source.fetch(**merged_kwargs)

        if save and result.records:
            storage = self._get_storage(storage_backend)
            file_path = storage.append(result.records, config.id, config.primary_keys)

            # Update index
            df = storage.read(config.id)

            # Compute last_record_date from data
            last_record_date = self._get_last_record_date(df, config.primary_keys)

            self.index_manager.update_dataset(
                name=config.id,
                source_id=config.id,
                location="raw",
                file_path=file_path,
                record_count=len(df),
                columns=list(df.columns),
                description=config.description,
                primary_keys=config.primary_keys,
                last_record_date=last_record_date,
            )

        return result

    def _get_last_record_date(
        self,
        df: "pd.DataFrame",
        primary_keys: Optional[list[str]] = None,
    ) -> Optional[datetime]:
        """Extract the most recent date from the data."""
        import pandas as pd

        if df.empty:
            return None

        # Look for common date columns
        date_columns = ["date", "published", "timestamp", "created_at", "fetched_at", "_fetched_at"]

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

    def run_job(self, job_id: str, **kwargs: Any) -> FetchResult:
        """Run a job by ID."""
        jobs = load_jobs()
        job_config = next((j for j in jobs if j.id == job_id), None)

        if job_config is None:
            return FetchResult(
                source_id="unknown",
                job_id=job_id,
                status=FetchStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error=f"Job '{job_id}' not found",
            )

        return self.run_job_config(job_config, **kwargs)

    def run_job_config(self, config: JobConfig, **kwargs: Any) -> FetchResult:
        """Run a job using a job config."""
        sources = load_sources()
        source_config = next((s for s in sources if s.id == config.source), None)

        if source_config is None:
            return FetchResult(
                source_id=config.source,
                job_id=config.id,
                status=FetchStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error=f"Source '{config.source}' not found for job '{config.id}'",
            )

        source = self.registry.create_source(source_config)

        if source is None:
            return FetchResult(
                source_id=config.source,
                job_id=config.id,
                status=FetchStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error=f"Unknown source type: {source_config.type}",
            )

        merged_kwargs = {**source_config.config, **kwargs}

        # For incremental sources, pass the last record date
        dataset_name = f"{config.source}_{config.id}"
        if source_config.incremental:
            existing = self.index_manager.get_dataset(dataset_name, "raw")
            if existing and existing.last_record_date:
                merged_kwargs["since"] = existing.last_record_date

        result = source.fetch(**merged_kwargs)
        result.job_id = config.id

        if result.records:
            storage = self._get_storage(
                config.storage.backend,
                config.storage.path,
            )
            file_path = storage.append(result.records, dataset_name, source_config.primary_keys)

            # Update index
            df = storage.read(dataset_name)
            last_record_date = self._get_last_record_date(df, source_config.primary_keys)

            self.index_manager.update_dataset(
                name=dataset_name,
                source_id=config.source,
                location="raw",
                file_path=file_path,
                record_count=len(df),
                columns=list(df.columns),
                description=config.description,
                primary_keys=source_config.primary_keys,
                last_record_date=last_record_date,
            )

        return result

    def test_source(self, source_id: str) -> bool:
        """Test connectivity to a source."""
        sources = load_sources()
        source_config = next((s for s in sources if s.id == source_id), None)

        if source_config is None:
            return False

        source = self.registry.create_source(source_config)
        if source is None:
            return False

        return source.test_connection()
