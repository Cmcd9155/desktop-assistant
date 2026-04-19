from __future__ import annotations

import base64

import pytest

from app.config import AppConfig
from app.services import xai_image_client as module_under_test
from app.services.xai_image_client import XaiImageClient, _closest_supported_aspect_ratio


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"payload"

    def json(self) -> dict:
        return self._payload


def _cfg(tmp_path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        app_host="127.0.0.1",
        app_port=8787,
        app_origin="http://127.0.0.1:5173",
        data_dir=data_dir,
        image_dir=data_dir / "images",
        upload_dir=data_dir / "uploads",
        xai_api_key="test-key",
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


@pytest.mark.asyncio
async def test_edit_request_uses_image_object_payload(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    base_image = cfg.upload_dir / "base.png"
    base_image.write_bytes(b"png-bytes")
    captured: dict[str, object] = {}
    expected_b64 = base64.b64encode(b"edited-bytes").decode("ascii")

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["base_url"] = kwargs.get("base_url")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, endpoint, headers=None, json=None):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse({"data": [{"b64_json": expected_b64}]})

        async def get(self, url):
            raise AssertionError("Unexpected fallback GET call")

    monkeypatch.setattr(module_under_test.httpx, "AsyncClient", FakeAsyncClient)

    client = XaiImageClient(cfg)
    result = await client.generate_or_edit(
        prompt="keep same character",
        base_image_path=base_image,
        nsfw_enabled=True,
        image_width=1200,
        image_height=900,
    )

    assert result.image_bytes == b"edited-bytes"
    assert captured["endpoint"] == "/images/edits"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "image" in payload
    assert "image_url" not in payload
    assert payload["aspect_ratio"] == "4:3"
    assert payload["image"]["type"] == "image_url"
    assert payload["image"]["url"].startswith("data:image/png;base64,")
    assert "Target render frame: 1200x900 pixels." in payload["prompt"]


@pytest.mark.asyncio
async def test_generation_request_omits_image_payload(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    captured: dict[str, object] = {}
    expected_b64 = base64.b64encode(b"generated-bytes").decode("ascii")

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["base_url"] = kwargs.get("base_url")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, endpoint, headers=None, json=None):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse({"data": [{"b64_json": expected_b64}]})

        async def get(self, url):
            raise AssertionError("Unexpected fallback GET call")

    monkeypatch.setattr(module_under_test.httpx, "AsyncClient", FakeAsyncClient)

    client = XaiImageClient(cfg)
    result = await client.generate_or_edit(
        prompt="draw new pose",
        base_image_path=None,
        nsfw_enabled=True,
    )

    assert result.image_bytes == b"generated-bytes"
    assert captured["endpoint"] == "/images/generations"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "image" not in payload
    assert "image_url" not in payload
    assert "aspect_ratio" not in payload


def test_closest_supported_aspect_ratio_picks_nearest_value() -> None:
    assert _closest_supported_aspect_ratio(1080, 1920) == "9:16"
    assert _closest_supported_aspect_ratio(1100, 500) == "20:9"
