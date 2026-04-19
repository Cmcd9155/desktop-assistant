from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from app.config import AppConfig
from app.models import ChatImageResponse, ImageJob, ImageJobStatus, utc_now_iso
from app.storage import read_json, write_json

from .xai_image_client import XaiImageClient


class ImageJobService:
    def __init__(self, config: AppConfig, xai_client: XaiImageClient) -> None:
        self._config = config
        self._xai_client = xai_client
        self._jobs_path = config.data_dir / "image_jobs.json"
        self._runtime_path = config.data_dir / "runtime_state.json"
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(
        self,
        *,
        turn_id: str,
        prompt: str,
        base_image_path: Path | None,
        nsfw_enabled: bool,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> str:
        job_id = str(uuid4())
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        async with self._lock:
            jobs = self._load_jobs()
            jobs[job_id] = ImageJob(
                id=job_id,
                turnId=turn_id,
                promptHash=prompt_hash,
                status=ImageJobStatus.queued,
                createdAt=utc_now_iso(),
            ).model_dump()
            self._save_jobs(jobs)
            task = asyncio.create_task(
                self._process_job(
                    job_id=job_id,
                    prompt=prompt,
                    base_image_path=base_image_path,
                    nsfw_enabled=nsfw_enabled,
                    image_width=image_width,
                    image_height=image_height,
                )
            )
            self._tasks[job_id] = task

        return job_id

    async def get(self, job_id: str) -> ChatImageResponse:
        async with self._lock:
            jobs = self._load_jobs()
            raw = jobs.get(job_id)
            if not raw:
                return ChatImageResponse(
                    status=ImageJobStatus.failed,
                    errorCode="job_not_found",
                    moderated=False,
                )
            job = ImageJob.model_validate(raw)
            image_url = None
            if job.outputPath:
                path = Path(job.outputPath)
                if path.exists():
                    image_url = f"/static/images/{path.name}"
            return ChatImageResponse(
                status=job.status,
                imageUrl=image_url,
                moderated=job.moderated,
                errorCode=job.errorCode,
            )

    async def _process_job(
        self,
        *,
        job_id: str,
        prompt: str,
        base_image_path: Path | None,
        nsfw_enabled: bool,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> None:
        previous_valid = self._load_runtime().get("lastValidImagePath", "")
        reference_image_paths: list[Path] = []
        if previous_valid:
            previous_path = Path(previous_valid)
            if previous_path.exists():
                reference_image_paths.append(previous_path)
        if base_image_path and base_image_path.exists():
            if not any(existing.resolve() == base_image_path.resolve() for existing in reference_image_paths):
                reference_image_paths.append(base_image_path)
        reference_image_paths = reference_image_paths[:5]

        await self._update_job(job_id, status=ImageJobStatus.running, completedAt=None)

        result = await self._xai_client.generate_or_edit(
            prompt=prompt,
            reference_image_paths=reference_image_paths,
            nsfw_enabled=nsfw_enabled,
            image_width=image_width,
            image_height=image_height,
        )

        if result.image_bytes:
            filename = f"{job_id}.png"
            output_path = self._config.image_dir / filename
            output_path.write_bytes(result.image_bytes)
            runtime = self._load_runtime()
            runtime["lastValidImagePath"] = str(output_path)
            write_json(self._runtime_path, runtime)
            await self._update_job(
                job_id,
                status=ImageJobStatus.completed,
                outputPath=str(output_path),
                moderated=False,
                errorCode=None,
                completedAt=utc_now_iso(),
            )
            return

        if result.moderated:
            await self._update_job(
                job_id,
                status=ImageJobStatus.moderated,
                outputPath=previous_valid,
                moderated=True,
                errorCode=result.error_code or "moderated",
                completedAt=utc_now_iso(),
            )
            return

        await self._update_job(
            job_id,
            status=ImageJobStatus.failed,
            outputPath=previous_valid,
            moderated=False,
            errorCode=result.error_code or "image_generation_failed",
            completedAt=utc_now_iso(),
        )

    async def _update_job(self, job_id: str, **updates: object) -> None:
        async with self._lock:
            jobs = self._load_jobs()
            raw = jobs.get(job_id)
            if not raw:
                return
            raw.update(updates)
            jobs[job_id] = raw
            self._save_jobs(jobs)

    def _load_jobs(self) -> dict[str, dict]:
        return read_json(self._jobs_path, {})

    def _save_jobs(self, jobs: dict[str, dict]) -> None:
        write_json(self._jobs_path, jobs)

    def _load_runtime(self) -> dict:
        runtime = read_json(self._runtime_path, {})
        runtime.setdefault("lastValidImagePath", "")
        return runtime
