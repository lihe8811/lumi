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

    # Queue (Redis)
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    redis_queue_key: str = Field(default="lumi:jobs", env="REDIS_QUEUE_KEY")

    # arXiv sanity-lite integration
    arxiv_sanity_data_dir: str = Field(
        default="data/arxiv_sanity", env="ARXIV_SANITY_DATA_DIR"
    )
    arxiv_sanity_query: str = Field(
        default=(
            "cat:cs.CV+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.AI+OR+cat:cs.NE+OR+cat:cs.RO"
        ),
        env="ARXIV_SANITY_QUERY",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
