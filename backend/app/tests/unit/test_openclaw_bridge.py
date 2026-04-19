from __future__ import annotations

import asyncio

import pytest
import httpx

from app.config import AppConfig
from app.services.openclaw_bridge import OpenClawBridgeService


class FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, headers: dict, json: dict):
        request = httpx.Request("POST", url, json=json)
        payload = {
            "id": "resp_1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Tagged reply"}],
                }
            ],
        }
        return httpx.Response(status_code=200, json=payload, request=request)


@pytest.mark.asyncio
async def test_send_and_poll_are_cursored_and_idempotent(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    cfg = AppConfig(
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
    cfg.ensure_directories()
    service = OpenClawBridgeService(cfg)

    monkeypatch.setattr(
        "app.services.openclaw_bridge.httpx.AsyncClient",
        lambda timeout=15: FakeAsyncClient(),
    )

    send = await service.send("ping")
    assert send.accepted is True

    first = await service.poll()
    deadline = 1.0
    while len(first.events) == 0 and deadline > 0:
        await asyncio.sleep(0.05)
        deadline -= 0.05
        first = await service.poll(cursor=first.cursor)
    assert len(first.events) == 1
    assert first.events[0].requestId == send.requestId
    assert "Tagged reply" in first.events[0].text

    second = await service.poll(cursor=first.cursor)
    assert len(second.events) == 0
