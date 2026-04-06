"""Settings loaded from env vars (prefix ``WATCHER_``) or a local ``.env``."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WATCHER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://watcher:watcher@localhost:5432/watcher"
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    slack_webhook_url: str | None = None
    alerts_enabled: bool = False
    check_interval_seconds: int = 60
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
