"""YAML configuration file loading."""

from pathlib import Path
from typing import Optional

import yaml

from cdata.config.env import get_settings
from cdata.config.schema import (
    FavoritesConfig,
    JobConfig,
    JobsFile,
    SourceConfig,
    SourcesFile,
)


def load_yaml(path: Path) -> dict:
    """Load a YAML file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_sources(config_dir: Optional[Path] = None) -> list[SourceConfig]:
    """Load all source configurations from the sources directory."""
    settings = get_settings()
    sources_dir = config_dir or settings.sources_config_dir

    sources: list[SourceConfig] = []

    if not sources_dir.exists():
        return sources

    for yaml_file in sources_dir.glob("*.yaml"):
        data = load_yaml(yaml_file)
        if data:
            parsed = SourcesFile.model_validate(data)
            sources.extend(parsed.sources)

    return sources


def load_jobs(config_dir: Optional[Path] = None) -> list[JobConfig]:
    """Load all job configurations from the jobs directory."""
    settings = get_settings()
    jobs_dir = config_dir or settings.jobs_config_dir

    jobs: list[JobConfig] = []

    if not jobs_dir.exists():
        return jobs

    for yaml_file in jobs_dir.glob("*.yaml"):
        data = load_yaml(yaml_file)
        if data:
            parsed = JobsFile.model_validate(data)
            jobs.extend(parsed.jobs)

    return jobs


def load_favorites(config_dir: Optional[Path] = None) -> FavoritesConfig:
    """Load favorites configuration."""
    settings = get_settings()
    config_dir = config_dir or settings.config_dir
    favorites_path = config_dir / "favorites.yaml"

    data = load_yaml(favorites_path)
    return FavoritesConfig.model_validate(data) if data else FavoritesConfig()


def get_source_by_id(source_id: str) -> Optional[SourceConfig]:
    """Get a source configuration by its ID."""
    sources = load_sources()
    for source in sources:
        if source.id == source_id:
            return source
    return None


def get_job_by_id(job_id: str) -> Optional[JobConfig]:
    """Get a job configuration by its ID."""
    jobs = load_jobs()
    for job in jobs:
        if job.id == job_id:
            return job
    return None
