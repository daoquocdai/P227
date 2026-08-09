from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VISION_ROOT = Path(__file__).resolve().parent / "vision"


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

    # Explicit test/demo control. Empty means the production mock emits no events.
    mock_vision_event_frame_ids: str = ""

    # Vision. Mock remains the safe default; Legacy imports and models are lazy.
    vision_engine: Literal["mock", "legacy"] = "mock"
    vision_device: str = "auto"
    vision_legacy_yolo_path: Path = VISION_ROOT / "yolov8n.pt"
    vision_legacy_config_path: Path = (
        VISION_ROOT / "work_dir" / "fall_detection" / "ntu25-bone" / "config.yaml"
    )
    vision_legacy_checkpoint_path: Path = (
        VISION_ROOT / "work_dir" / "fall_detection" / "ntu25-bone" / "runs-best_val.pt"
    )
    vision_legacy_known_faces_dir: Path = VISION_ROOT / "register face"
    vision_legacy_identity_enabled: bool = False
    vision_legacy_insightface_root: Path = Path.home() / ".insightface"
    vision_temporal_target_sample_rate: float = Field(default=15.0, gt=0)
    vision_temporal_buffer_capacity: int = Field(default=8, ge=2, multiple_of=2)

    @field_validator("vision_device")
    @classmethod
    def validate_vision_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"auto", "cpu", "cuda"}:
            return normalized
        if normalized.startswith("cuda:") and normalized[5:].isdigit():
            return normalized
        raise ValueError("VISION_DEVICE must be auto, cpu, cuda, or cuda:N")

    # LLM
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"


@lru_cache
def get_settings() -> Settings:
    return Settings()
