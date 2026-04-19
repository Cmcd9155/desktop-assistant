from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        app_host="127.0.0.1",
        app_port=8787,
        app_origin="http://127.0.0.1:5173",
        data_dir=data_dir,
        image_dir=data_dir / "images",
        upload_dir=data_dir / "uploads",
        xai_api_key=None,
        xai_api_base="https://api.x.ai/v1",
        xai_image_model="grok-imagine-image",
        xai_timeout_seconds=10,
        openclaw_base_url="http://127.0.0.1:9090",
        openclaw_session_key="test-session",
        openclaw_model="openclaw",
        openclaw_auth_mode="token",
        openclaw_auth_token=None,
        openclaw_timeout_seconds=5,
        openclaw_poll_interval_seconds=1,
        image_job_timeout_seconds=5,
        memory_inactivity_minutes=30,
        memory_default_enabled=True,
        nsfw_default_enabled=True,
    )


@pytest.fixture
def client(app_config: AppConfig) -> TestClient:
    app = create_app(app_config)
    with TestClient(app) as test_client:
        yield test_client
