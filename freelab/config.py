"""Configuration helpers for the freelab package."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseSettings, Field, validator


load_dotenv(override=False)


class Settings(BaseSettings):
    """Application configuration derived from environment variables."""

    db_url: Optional[str] = Field(default=None, env="DB_URL")
    access_token: Optional[str] = Field(default=None, env="ACCESS_TOKEN")
    selenium_headless: bool = Field(default=True, env="SELENIUM_HEADLESS")
    hash_salt: str = Field(default="freelab", env="HASH_SALT")
    start_url: Optional[str] = Field(default=None, env="START_URL")
    categories: List[str] = Field(default_factory=list, env="CATEGORY")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @validator("selenium_headless", pre=True)
    def _parse_bool(cls, value: object) -> bool:  # noqa: D401
        """Allow truthy and falsy string representations for booleans."""

        if isinstance(value, bool):
            return value
        if value is None:
            return True
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @validator("categories", pre=True)
    def _split_categories(cls, value: object) -> List[str]:  # noqa: D401
        """Support comma separated category lists."""

        if not value:
            return []
        if isinstance(value, list):
            return value
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @property
    def database_url(self) -> str:
        """Return the configured database URL, defaulting to SQLite."""

        if self.db_url:
            return self.db_url
        data_dir = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{data_dir / 'freelab.sqlite3'}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()


settings = get_settings()
