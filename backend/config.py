"""Explicit prototype configuration; real-provider mode is opt-in."""
import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MERIDIAN_", extra="ignore")

    database_path: str | Path = "var/meridian.sqlite3"
    provider_mode: Literal["deterministic", "openai"] = "deterministic"
    provider_model: str = "gpt-4.1"
    provider_api_key: str | None = None
    auth_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    token_lifetime_seconds: int = Field(default=3600, ge=60)
    request_deadline_ms: int = Field(default=3800, ge=50, le=30000)
    provider_timeout_ms: int = Field(default=2500, ge=20, le=30000)
    diagnostics_enabled: bool = False
    diagnostics_retention_seconds: int = Field(default=3600, ge=60, le=86400)
    diagnostics_access_key: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"]
