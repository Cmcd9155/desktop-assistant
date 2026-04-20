from __future__ import annotations

import asyncio
import base64
import json

import pytest

from app.config import AppConfig
from app.models import ImageJobStatus
from app.services.image_jobs import ImageJobService
from app.services.xai_image_client import ImageGenerationResult, PNG_1X1_BASE64


class FakeXaiClient:
    def __init__(self, result: ImageGenerationResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def generate_or_edit(self, **kwargs: object) -> ImageGenerationResult:
        self.calls.append(kwargs)
        return self.result


def _cfg(tmp_path) -> AppConfig:
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


@pytest.mark.asyncio
async def test_image_job_completed_state(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    service = ImageJobService(
        cfg,
        FakeXaiClient(ImageGenerationResult(image_bytes=b"pngbytes", moderated=False, error_code=None)),
    )
    job_id = await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=None, nsfw_enabled=True)
    await asyncio.sleep(0.05)
    response = await service.get(job_id)
    assert response.status == ImageJobStatus.completed
    assert response.imageUrl


@pytest.mark.asyncio
async def test_image_job_moderation_falls_back(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    service = ImageJobService(
        cfg,
        FakeXaiClient(ImageGenerationResult(image_bytes=None, moderated=True, error_code="moderated")),
    )
    job_id = await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=None, nsfw_enabled=True)
    await asyncio.sleep(0.05)
    response = await service.get(job_id)
    assert response.status == ImageJobStatus.moderated
    assert response.moderated is True


@pytest.mark.asyncio
async def test_image_job_failure_falls_back_without_crash(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    service = ImageJobService(
        cfg,
        FakeXaiClient(ImageGenerationResult(image_bytes=None, moderated=False, error_code="http_500")),
    )
    job_id = await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=None, nsfw_enabled=True)
    await asyncio.sleep(0.05)
    response = await service.get(job_id)
    assert response.status == ImageJobStatus.failed
    assert response.errorCode == "http_500"


@pytest.mark.asyncio
async def test_image_job_reference_chain_orders_previous_then_base(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    previous = cfg.image_dir / "previous.png"
    previous.write_bytes(b"old")
    base = cfg.upload_dir / "base.png"
    base.write_bytes(b"base")
    runtime_path = cfg.data_dir / "runtime_state.json"
    runtime_path.write_text(json.dumps({"lastValidImagePath": str(previous)}), encoding="utf-8")

    fake = FakeXaiClient(ImageGenerationResult(image_bytes=b"pngbytes", moderated=False, error_code=None))
    service = ImageJobService(cfg, fake)
    await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=base, nsfw_enabled=True)
    await asyncio.sleep(0.05)

    assert len(fake.calls) == 1
    refs = fake.calls[0]["reference_image_paths"]
    assert isinstance(refs, list)
    assert refs == [previous, base]


@pytest.mark.asyncio
async def test_image_job_reference_chain_dedupes_identical_paths(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    same = cfg.upload_dir / "base.png"
    same.write_bytes(b"same")
    runtime_path = cfg.data_dir / "runtime_state.json"
    runtime_path.write_text(json.dumps({"lastValidImagePath": str(same)}), encoding="utf-8")

    fake = FakeXaiClient(ImageGenerationResult(image_bytes=b"pngbytes", moderated=False, error_code=None))
    service = ImageJobService(cfg, fake)
    await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=same, nsfw_enabled=True)
    await asyncio.sleep(0.05)

    refs = fake.calls[0]["reference_image_paths"]
    assert isinstance(refs, list)
    assert refs == [same]


@pytest.mark.asyncio
async def test_image_job_skips_placeholder_previous_reference(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    previous = cfg.image_dir / "previous.png"
    previous.write_bytes(base64.b64decode(PNG_1X1_BASE64))
    base = cfg.upload_dir / "base.png"
    base.write_bytes(b"base")
    runtime_path = cfg.data_dir / "runtime_state.json"
    runtime_path.write_text(json.dumps({"lastValidImagePath": str(previous)}), encoding="utf-8")

    fake = FakeXaiClient(ImageGenerationResult(image_bytes=b"pngbytes", moderated=False, error_code=None))
    service = ImageJobService(cfg, fake)
    await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=base, nsfw_enabled=True)
    await asyncio.sleep(0.05)

    refs = fake.calls[0]["reference_image_paths"]
    assert isinstance(refs, list)
    assert refs == [base]


@pytest.mark.asyncio
async def test_image_job_does_not_promote_placeholder_output_to_runtime(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.ensure_directories()
    service = ImageJobService(
        cfg,
        FakeXaiClient(
            ImageGenerationResult(
                image_bytes=base64.b64decode(PNG_1X1_BASE64),
                moderated=False,
                error_code="xai_api_key_missing",
            )
        ),
    )

    await service.enqueue(turn_id="turn-1", prompt="hello", base_image_path=None, nsfw_enabled=True)
    await asyncio.sleep(0.05)

    runtime_path = cfg.data_dir / "runtime_state.json"
    assert not runtime_path.exists()
