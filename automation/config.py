"""
automation/config.py

Platform-wide runtime configuration. All modules import from here.
Never read os.environ directly anywhere else in the codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NetBoxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETBOX_", env_file=".env", extra="ignore")

    url: str = Field(..., description="Base URL e.g. http://localhost:8080")
    token: SecretStr = Field(..., description="API token — never logged")
    verify_ssl: bool = Field(default=True)
    timeout: int = Field(default=30, ge=1, le=120)

    @field_validator("url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class ScrapliSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCRAPLI_")

    platform: str = Field(default="cisco_iosxe")
    auth_strict_key: bool = Field(default=False)
    timeout_socket: int = Field(default=15)
    timeout_transport: int = Field(default=30)
    timeout_ops: int = Field(default=60)
    ssh_config_file: bool = Field(default=True)


class NornirSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NORNIR_")

    num_workers: int = Field(default=10, ge=1, le=100)
    runner_plugin: Literal["threaded", "serial"] = Field(default="threaded")


class PrometheusSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROMETHEUS_")

    pushgateway_url: str = Field(default="http://localhost:9091")
    job_name: str = Field(default="network_automation")
    push_enabled: bool = Field(default=False)


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLLAMA_")

    base_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="llama3")
    timeout: int = Field(default=120)
    enabled: bool = Field(default=False)


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    netbox: NetBoxSettings = Field(default_factory=NetBoxSettings)
    scrapli: ScrapliSettings = Field(default_factory=ScrapliSettings)
    nornir: NornirSettings = Field(default_factory=NornirSettings)
    prometheus: PrometheusSettings = Field(default_factory=PrometheusSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)

    environment: Literal["lab", "staging", "production"] = Field(default="lab")
    dry_run: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    rollback_on_failure: bool = Field(default=True)
    drift_detection_enabled: bool = Field(default=True)
    ai_enabled: bool = Field(default=False)


@lru_cache(maxsize=1)
def get_settings() -> PlatformSettings:
    """
    Cached singleton. Call get_settings.cache_clear() in tests
    that mutate environment variables.
    """
    return PlatformSettings()
