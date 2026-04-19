from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.xai_image_client import ImageGenerationResult


def _config(tmp_path: Path, inactivity_minutes: int = 30) -> AppConfig:
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


@pytest.mark.integration
def test_text_first_turn_returns_before_image_completes(tmp_path) -> None:
    app = create_app(_config(tmp_path))

    async def delayed_generate(**kwargs):
        await asyncio.sleep(0.25)
        return ImageGenerationResult(image_bytes=b"abc", moderated=False, error_code=None)

    app.state.image_service._xai_client.generate_or_edit = delayed_generate

    with TestClient(app) as client:
        start = time.perf_counter()
        response = client.post("/api/chat/turn", json={"message": "hello"})
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < 0.2
        job_id = response.json()["imageJobId"]

        deadline = time.time() + 3
        status = ""
        while time.time() < deadline:
            image_response = client.get(f"/api/chat/image/{job_id}")
            status = image_response.json()["status"]
            if status == "completed":
                break
            time.sleep(0.05)
        assert status == "completed"


@pytest.mark.integration
def test_moderation_fallback_keeps_previous_valid_image(tmp_path) -> None:
    app = create_app(_config(tmp_path))

    async def good_image(**kwargs):
        return ImageGenerationResult(image_bytes=b"first", moderated=False, error_code=None)

    async def moderated_image(**kwargs):
        return ImageGenerationResult(image_bytes=None, moderated=True, error_code="moderated")

    with TestClient(app) as client:
        app.state.image_service._xai_client.generate_or_edit = good_image
        first_turn = client.post("/api/chat/turn", json={"message": "turn1"}).json()
        time.sleep(0.1)
        first_image = client.get(f"/api/chat/image/{first_turn['imageJobId']}").json()
        assert first_image["status"] == "completed"
        assert first_image["imageUrl"]

        app.state.image_service._xai_client.generate_or_edit = moderated_image
        second_turn = client.post("/api/chat/turn", json={"message": "turn2"}).json()
        time.sleep(0.1)
        second_image = client.get(f"/api/chat/image/{second_turn['imageJobId']}").json()
        assert second_image["status"] == "moderated"
        assert second_image["imageUrl"] == first_image["imageUrl"]


@pytest.mark.integration
def test_openclaw_tagged_response_ingested_once(monkeypatch, tmp_path) -> None:
    app = create_app(_config(tmp_path))

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, headers: dict, json: dict):
            payload = {
                "id": "resp_test",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hello from bridge"}],
                    }
                ],
            }
            return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    with TestClient(app) as client:
        monkeypatch.setattr("app.services.openclaw_bridge.httpx.AsyncClient", lambda timeout=15: FakeAsyncClient())
        send = client.post("/api/openclaw/send", json={"text": "ping"}).json()
        assert send["accepted"] is True
        first = client.get("/api/openclaw/poll").json()
        deadline = time.time() + 1.0
        while len(first["events"]) == 0 and time.time() < deadline:
            time.sleep(0.05)
            first = client.get(f"/api/openclaw/poll?cursor={first['cursor']}").json()
        second = client.get(f"/api/openclaw/poll?cursor={first['cursor']}").json()
        assert len(first["events"]) == 1
        assert first["events"][0]["requestId"] == send["requestId"]
        assert len(second["events"]) == 0


@pytest.mark.integration
def test_inactivity_flush_writes_memory_not_per_turn(tmp_path) -> None:
    app = create_app(_config(tmp_path, inactivity_minutes=0))
    with TestClient(app) as client:
        client.post("/api/chat/turn", json={"message": "I need to ship this today"})
        before = client.get("/api/memory").json()
        assert before["items"] == []
        time.sleep(0.05)
        client.post("/api/memory/flush", json={"trigger": "inactivity"})
        after = client.get("/api/memory").json()
        assert len(after["items"]) >= 1


@pytest.mark.integration
def test_toggle_memory_off_flushes_once_and_blocks_new_auto_writes(tmp_path) -> None:
    app = create_app(_config(tmp_path, inactivity_minutes=0))
    with TestClient(app) as client:
        client.post("/api/chat/turn", json={"message": "I prefer concise answers"})
        settings = client.get("/api/settings/companion").json()
        settings["memoryEnabled"] = False
        client.put("/api/settings/companion", json=settings)
        initial_items = client.get("/api/memory").json()["items"]
        client.post("/api/chat/turn", json={"message": "new turn should not auto-flush"})
        time.sleep(0.1)
        final_items = client.get("/api/memory").json()["items"]
        assert len(final_items) == len(initial_items)


@pytest.mark.integration
def test_settings_base_image_path_used_in_next_prompt(tmp_path) -> None:
    app = create_app(_config(tmp_path))
    captured = {"base": None}
    base_image = app.state.config.upload_dir / "seed.png"
    base_image.write_bytes(b"seed")

    async def capture_call(*, base_image_path=None, **kwargs):
        captured["base"] = str(base_image_path) if base_image_path else None
        return ImageGenerationResult(image_bytes=b"img", moderated=False, error_code=None)

    app.state.image_service._xai_client.generate_or_edit = capture_call
    with TestClient(app) as client:
        settings = client.get("/api/settings/companion").json()
        settings["baseImagePath"] = str(base_image)
        client.put("/api/settings/companion", json=settings)
        client.post("/api/chat/turn", json={"message": "hello"})
        time.sleep(0.1)
        assert captured["base"] == str(base_image)
