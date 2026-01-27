"""Environment and settings management."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CDATA_",
        extra="ignore",
    )

    # Paths
    config_dir: Path = Path("./config")
    data_dir: Path = Path("./data")
    logs_dir: Path = Path("./logs")
    sources_module_dir: Path = Path("./sources")

    # API Keys (optional, loaded from .env)
    alphavantage_api_key: Optional[str] = None
    newsapi_key: Optional[str] = None

    # HTTP settings
    http_timeout: int = 30
    http_retries: int = 3

    # Scheduler
    scheduler_timezone: str = "UTC"

    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def sources_config_dir(self) -> Path:
        return self.config_dir / "sources"

    @property
    def jobs_config_dir(self) -> Path:
        return self.config_dir / "jobs"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
