from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    app_host: str
    app_port: int
    app_origin: str
    data_dir: Path
    image_dir: Path
    upload_dir: Path
    xai_api_key: str | None
    xai_api_base: str
    xai_image_model: str
    xai_timeout_seconds: int
    openclaw_base_url: str
    openclaw_session_key: str
    openclaw_model: str
    openclaw_auth_mode: str
    openclaw_auth_token: str | None
    openclaw_timeout_seconds: int
    openclaw_poll_interval_seconds: int
    image_job_timeout_seconds: int
    memory_inactivity_minutes: int
    memory_default_enabled: bool
    nsfw_default_enabled: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        default_data_dir = (Path(__file__).resolve().parents[1] / "data").resolve()
        data_dir = Path(os.getenv("APP_DATA_DIR", str(default_data_dir))).resolve()
        return cls(
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8787")),
            app_origin=os.getenv("APP_ORIGIN", "http://127.0.0.1:5173"),
            data_dir=data_dir,
            image_dir=data_dir / "images",
            upload_dir=data_dir / "uploads",
            xai_api_key=os.getenv("XAI_API_KEY"),
            xai_api_base=os.getenv("XAI_API_BASE", "https://api.x.ai/v1"),
            xai_image_model=os.getenv("XAI_IMAGE_MODEL", "grok-imagine-image"),
            xai_timeout_seconds=int(os.getenv("XAI_TIMEOUT_SECONDS", "45")),
            openclaw_base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:8080"),
            openclaw_session_key=os.getenv("OPENCLAW_SESSION_KEY", "desktop-assistant-mvp1"),
            openclaw_model=os.getenv("OPENCLAW_MODEL", "openclaw"),
            openclaw_auth_mode=os.getenv("OPENCLAW_AUTH_MODE", "token"),
            openclaw_auth_token=os.getenv("OPENCLAW_AUTH_TOKEN"),
            openclaw_timeout_seconds=int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "45")),
            openclaw_poll_interval_seconds=int(os.getenv("OPENCLAW_POLL_INTERVAL_SECONDS", "5")),
            image_job_timeout_seconds=int(os.getenv("IMAGE_JOB_TIMEOUT_SECONDS", "45")),
            memory_inactivity_minutes=int(os.getenv("MEMORY_INACTIVITY_MINUTES", "30")),
            memory_default_enabled=_bool_env("MEMORY_ENABLED_DEFAULT", True),
            nsfw_default_enabled=_bool_env("NSFW_ENABLED_DEFAULT", True),
        )

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.image_dir, self.upload_dir):
            directory.mkdir(parents=True, exist_ok=True)
