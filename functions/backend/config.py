"""
Configuration and settings for the refactored backend.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for the FastAPI service."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_prefix: str = Field(default="/api")

    # Database (Postgres expected)
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")

    # S3-compatible storage (Tencent COS)
    cos_endpoint: Optional[str] = Field(default=None, env="COS_ENDPOINT")
    cos_region: Optional[str] = Field(default=None, env="COS_REGION")
    cos_bucket: Optional[str] = Field(default=None, env="COS_BUCKET")
    aws_access_key_id: Optional[str] = Field(
        default=None, env="AWS_ACCESS_KEY_ID"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None, env="AWS_SECRET_ACCESS_KEY"
    )

    # LLM / Gemini
    gemini_api_key: Optional[str] = Field(default=None, env="GEMINI_API_KEY")

    # Development toggles
    use_in_memory_backends: bool = Field(
        default=False, env="LUMI_USE_IN_MEMORY_BACKENDS"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
