from __future__ import annotations

import pytest

from app.config import AppConfig
from app.services.memory_service import MemoryService
from app.storage import read_json


def _cfg(tmp_path, inactivity_minutes: int = 30) -> AppConfig:
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
        memory_inactivity_minutes=inactivity_minutes,
        memory_default_enabled=True,
        nsfw_default_enabled=True,
    )


@pytest.mark.asyncio
async def test_per_turn_write_is_blocked_until_flush(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    service = MemoryService(cfg)
    await service.record_turn(turn_id="t1", user_text="I want to ship fast", assistant_text="ok")
    stored = read_json(cfg.data_dir / "memory_items.json", [])
    assert stored == []


@pytest.mark.asyncio
async def test_inactivity_trigger_writes_summary(tmp_path) -> None:
    cfg = _cfg(tmp_path, inactivity_minutes=0)
    cfg.ensure_directories()
    service = MemoryService(cfg)
    await service.record_turn(turn_id="t1", user_text="I need to finish this today", assistant_text="ok")
    result = await service.maybe_flush_for_inactivity(memory_enabled=True)
    assert result is not None
    assert result.writtenCount >= 1


@pytest.mark.asyncio
async def test_memory_disabled_blocks_inactivity_flush(tmp_path) -> None:
    cfg = _cfg(tmp_path, inactivity_minutes=0)
    cfg.ensure_directories()
    service = MemoryService(cfg)
    await service.record_turn(turn_id="t1", user_text="I prefer vim", assistant_text="noted")
    result = await service.maybe_flush_for_inactivity(memory_enabled=False)
    assert result is None
