from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "GuardianCam Security Orchestrator"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    api_base_url: str = "http://localhost:8000"
    metrics_collection_enabled: bool = True
    metrics_collection_interval_seconds: int = Field(default=30, ge=5, le=3600)
    metrics_retention_days: int = Field(default=30, ge=1, le=365)

    # Explicit test/demo control. Empty means no synthetic event IDs.

    # SDA is the only production Vision implementation.
    vision_engine: Literal["sda"] = "sda"
    vision_device: str = "auto"
    vision_fps: float = Field(default=15.0, gt=0)
    vision_identity_enabled: bool = False
    vision_identity_process_priority: Literal["normal", "below_normal"] = "normal"
    vision_identity_cpu_affinity: tuple[int, ...] | None = None
    vision_allow_unblurred_event_snapshot: bool = False

    # SDA-backed enrollment encoder settings.
    vision_identity_provider: Literal["auto", "cpu", "cuda", "directml"] = "auto"
    vision_insightface_root: Path = Path.home() / ".insightface"

    @field_validator("vision_engine", mode="before")
    @classmethod
    def validate_vision_engine(cls, value: Any) -> str:
        return "sda"

    @field_validator("vision_device")
    @classmethod
    def validate_vision_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"auto", "cpu", "cuda", "amd", "intel"}:
            return normalized
        raise ValueError("VISION_DEVICE must be auto, cpu, cuda, amd, or intel")


    # LLM
    gemini_api_key: str = ""
    model_name: str = "gemini-3.5-flash-lite"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    alert_agent_enabled: bool = False
    alert_agent_model: str = "gemini-3.5-flash-lite"
    alert_agent_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    alert_agent_queue_capacity: int = Field(default=32, ge=1, le=1000)
    alert_agent_max_attempts: int = Field(default=2, ge=1, le=5)
    alert_agent_max_tool_steps: int = Field(default=4, ge=1, le=8)
    alert_agent_shutdown_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    unknown_incident_merge_seconds: int = Field(default=120, ge=60, le=3600)
    fall_incident_merge_seconds: int = Field(default=90, ge=60, le=3600)
    alert_agent_review_milestones: str = "1,2,5,10,20,50"

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"


@lru_cache
def get_settings() -> Settings:
    return Settings()
