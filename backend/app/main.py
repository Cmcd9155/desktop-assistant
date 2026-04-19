from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import AppConfig
from app.models import (
    ChatImageResponse,
    ChatTurnRequest,
    ChatTurnResponse,
    CompanionSettings,
    CompanionState,
    MemoryDeleteResponse,
    MemoryFlushRequest,
    MemoryFlushResponse,
    MemoryQueryResponse,
    OpenClawPollResponse,
    OpenClawSendRequest,
    OpenClawSendResponse,
)
from app.services.chat_agent import PrimaryChatAgent
from app.services.emotion import map_emotion
from app.services.image_jobs import ImageJobService
from app.services.memory_service import MemoryService
from app.services.openclaw_bridge import OpenClawBridgeService
from app.services.settings_service import SettingsService
from app.services.xai_image_client import XaiImageClient


def _build_image_prompt(
    *,
    user_text: str,
    assistant_text: str,
    emotion: CompanionState,
    base_image_path: str,
) -> str:
    return (
        "Keep the same character identity from the base anchor image.\n"
        f"Base image anchor path: {base_image_path or 'missing'}\n"
        f"Companion expression target: {emotion.value}\n"
        "Render only one character and preserve face consistency.\n"
        f"User said: {user_text}\n"
        f"Assistant replied: {assistant_text}\n"
    )


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig.from_env()
    cfg.ensure_directories()

    settings_service = SettingsService(cfg)
    memory_service = MemoryService(cfg)
    chat_agent = PrimaryChatAgent(cfg)
    xai_client = XaiImageClient(cfg)
    image_service = ImageJobService(cfg, xai_client)
    openclaw_service = OpenClawBridgeService(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def inactivity_loop() -> None:
            while not app.state.shutting_down:
                settings = await settings_service.get()
                await memory_service.maybe_flush_for_inactivity(memory_enabled=settings.memoryEnabled)
                await asyncio.sleep(cfg.openclaw_poll_interval_seconds)

        app.state.inactivity_task = asyncio.create_task(inactivity_loop())
        try:
            yield
        finally:
            app.state.shutting_down = True
            task = app.state.inactivity_task
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            settings = await settings_service.get()
            if settings.memoryEnabled:
                await memory_service.flush(trigger="shutdown", force=True)

    app = FastAPI(title="Desktop Assistant MVP1", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.app_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static/images", StaticFiles(directory=str(cfg.image_dir)), name="images")
    app.mount("/static/uploads", StaticFiles(directory=str(cfg.upload_dir)), name="uploads")

    app.state.config = cfg
    app.state.settings_service = settings_service
    app.state.memory_service = memory_service
    app.state.chat_agent = chat_agent
    app.state.image_service = image_service
    app.state.openclaw_service = openclaw_service
    app.state.inactivity_task = None
    app.state.shutting_down = False

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"ok": "true"}

    @app.post("/api/chat/turn", response_model=ChatTurnResponse)
    async def chat_turn(payload: ChatTurnRequest) -> ChatTurnResponse:
        settings = await settings_service.get()
        await memory_service.maybe_flush_for_inactivity(memory_enabled=settings.memoryEnabled)

        reply = await chat_agent.reply(payload.message, settings)
        emotion = map_emotion(reply)
        warnings: list[str] = []

        base_image_path = Path(settings.baseImagePath) if settings.baseImagePath else None
        if not (base_image_path and base_image_path.exists()):
            warnings.append("Base image is missing; generating without anchor.")
            base_image_path = None

        prompt = _build_image_prompt(
            user_text=payload.message,
            assistant_text=reply,
            emotion=emotion,
            base_image_path=settings.baseImagePath,
        )

        turn_id = str(uuid4())
        image_job_id = await image_service.enqueue(
            turn_id=turn_id,
            prompt=prompt,
            base_image_path=base_image_path,
            nsfw_enabled=settings.nsfwEnabled,
            image_width=payload.imageWidth,
            image_height=payload.imageHeight,
        )

        openclaw_request_id = None
        if payload.includeOpenClaw:
            oc = await openclaw_service.send(payload.message)
            openclaw_request_id = oc.requestId
            if not oc.accepted:
                warnings.append("OpenClaw send was not accepted.")

        await memory_service.record_turn(
            turn_id=turn_id,
            user_text=payload.message,
            assistant_text=reply,
        )

        return ChatTurnResponse(
            replyText=reply,
            imageJobId=image_job_id,
            emotion=emotion,
            openclawRequestId=openclaw_request_id,
            warnings=warnings,
        )

    @app.get("/api/chat/image/{job_id}", response_model=ChatImageResponse)
    async def get_chat_image(job_id: str) -> ChatImageResponse:
        return await image_service.get(job_id)

    @app.get("/api/settings/companion", response_model=CompanionSettings)
    async def get_companion_settings() -> CompanionSettings:
        return await settings_service.get()

    @app.put("/api/settings/companion", response_model=CompanionSettings)
    async def update_companion_settings(settings: CompanionSettings) -> CompanionSettings:
        existing = await settings_service.get()
        toggling_off = existing.memoryEnabled and not settings.memoryEnabled
        if toggling_off:
            await memory_service.flush(trigger="toggle_off", force=True)
        return await settings_service.update(settings)

    @app.post("/api/settings/companion/base-image", response_model=CompanionSettings)
    async def upload_base_image(file: UploadFile = File(...)) -> CompanionSettings:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        return await settings_service.save_base_image(file.filename or "base-image.png", data)

    @app.get("/api/memory", response_model=MemoryQueryResponse)
    async def query_memory(query: str = "") -> MemoryQueryResponse:
        items = await memory_service.query(query=query)
        return MemoryQueryResponse(items=items)

    @app.delete("/api/memory", response_model=MemoryDeleteResponse)
    async def wipe_memory() -> MemoryDeleteResponse:
        await memory_service.wipe()
        return MemoryDeleteResponse(ok=True)

    @app.post("/api/memory/flush", response_model=MemoryFlushResponse)
    async def flush_memory(payload: MemoryFlushRequest) -> MemoryFlushResponse:
        return await memory_service.flush(trigger=payload.trigger, force=True)

    @app.post("/api/openclaw/send", response_model=OpenClawSendResponse)
    async def openclaw_send(payload: OpenClawSendRequest) -> OpenClawSendResponse:
        return await openclaw_service.send(payload.text)

    @app.get("/api/openclaw/poll", response_model=OpenClawPollResponse)
    async def openclaw_poll(cursor: str = "") -> OpenClawPollResponse:
        return await openclaw_service.poll(cursor=cursor or None)

    return app

app = create_app()
