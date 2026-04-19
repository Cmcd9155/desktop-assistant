from __future__ import annotations

import pytest

from app.config import AppConfig
from app.models import CompanionSettings
from app.services import chat_agent as module_under_test
from app.services.chat_agent import PrimaryChatAgent


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"payload"

    def json(self) -> dict:
        return self._payload


def _cfg(tmp_path, api_key: str | None) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        app_host="127.0.0.1",
        app_port=8787,
        app_origin="http://127.0.0.1:5173",
        data_dir=data_dir,
        image_dir=data_dir / "images",
        upload_dir=data_dir / "uploads",
        xai_api_key=api_key,
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
        xai_text_model="grok-4",
    )


@pytest.mark.asyncio
async def test_reply_uses_remote_text_when_xai_available(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path, api_key="test-key")
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["base_url"] = kwargs.get("base_url")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, endpoint, headers=None, json=None):
            captured["endpoint"] = endpoint
            captured["json"] = json
            return _FakeResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Real companion response"}],
                        }
                    ]
                }
            )

    monkeypatch.setattr(module_under_test.httpx, "AsyncClient", FakeAsyncClient)
    agent = PrimaryChatAgent(cfg)
    settings = CompanionSettings()

    reply = await agent.reply("hey", settings)

    assert reply == "Real companion response"
    assert captured["endpoint"] == "/responses"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "grok-4"


@pytest.mark.asyncio
async def test_reply_fallback_does_not_dump_settings(tmp_path) -> None:
    cfg = _cfg(tmp_path, api_key=None)
    agent = PrimaryChatAgent(cfg)
    settings = CompanionSettings(
        bio="Helpful desktop companion.",
        instructions="Be concise, clear, and useful.",
    )

    reply = await agent.reply("hey", settings)

    assert "Answer:" not in reply
    assert "Bio:" not in reply
    assert "Instructions:" not in reply
    assert "helpful desktop companion" not in reply.lower()
    assert "i heard you: hey" in reply.lower()

