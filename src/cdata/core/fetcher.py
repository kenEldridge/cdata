"""Fetch orchestrator."""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from cdata.config import get_settings, load_sources, load_jobs
from cdata.config.schema import JobConfig, SourceConfig, StorageBackend as StorageBackendEnum
from cdata.core.registry import get_registry
from cdata.models import FetchResult, FetchStatus
from cdata.storage import ParquetStorage, CSVStorage, JSONStorage
from cdata.storage.base import StorageBackend


console = Console()


class Fetcher:
    """Orchestrates data fetching and storage."""

    def __init__(self):
        self.settings = get_settings()
        self.registry = get_registry()

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
        result = source.fetch(**merged_kwargs)

        if save and result.records:
            storage = self._get_storage(storage_backend)
            storage.append(result.records, config.id)

        return result

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
        result = source.fetch(**merged_kwargs)
        result.job_id = config.id

        if result.records:
            storage = self._get_storage(
                config.storage.backend,
                config.storage.path,
            )
            storage.append(
                result.records,
                f"{config.source}_{config.id}",
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
