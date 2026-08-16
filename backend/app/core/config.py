"""Central application configuration (spec §20.3).

Secrets and connection details come from environment variables only; no real
credential is allowed in source. Missing required values in production must
fail fast instead of falling back to development defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录的 .env（config.py 位于 backend/app/core/，向上三级即仓库根）。
_REPO_ENV = Path(__file__).resolve().parents[3] / ".env"
_ENV_FILE = _REPO_ENV if _REPO_ENV.is_file() else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: str = "development"  # development | test | production
    app_base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+asyncpg://airesearcher:airesearcher@localhost:5432/airesearcher"
    redis_url: str = "redis://localhost:6379/0"

    jwt_signing_key: str = "dev-insecure-change-me"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    minio_endpoint: str = "localhost:9000"
    minio_secure: bool = False
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_assets: str = "assets"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "ai-researcher"

    milvus_uri: str = "http://localhost:19530"

    max_upload_bytes: int = 500 * 1024 * 1024  # 单个资产大小上限（spec §19.4）

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Optional external providers. Unset means "not configured"; the platform
    # must surface PROVIDER_NOT_CONFIGURED rather than fabricate success.
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    ocr_provider: str | None = None
    experiment_runner_endpoint: str | None = None
    otel_exporter_otlp_endpoint: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    def validate_for_production(self) -> None:
        """Fail fast on clearly unsafe production configuration."""
        if not self.is_production:
            return
        if self.jwt_signing_key in {"dev-insecure-change-me", ""}:
            raise RuntimeError("JWT_SIGNING_KEY must be set in production")
        if self.database_url.startswith("sqlite"):
            raise RuntimeError("SQLite is not a supported production database")


@lru_cache
def get_settings() -> Settings:
    return Settings()
