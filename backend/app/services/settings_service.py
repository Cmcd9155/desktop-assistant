from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import AppConfig
from app.models import CompanionSettings
from app.storage import read_json, write_json


class SettingsService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._path = config.data_dir / "settings.json"
        self._lock = asyncio.Lock()
        self._ensure_default()

    async def get(self) -> CompanionSettings:
        async with self._lock:
            payload = read_json(self._path, {})
            return CompanionSettings.model_validate(payload)

    async def update(self, new_settings: CompanionSettings) -> CompanionSettings:
        async with self._lock:
            write_json(self._path, new_settings.model_dump())
            return new_settings

    async def save_base_image(self, filename: str, data: bytes) -> CompanionSettings:
        safe_name = Path(filename or "base-image.png").name
        suffix = Path(safe_name).suffix or ".png"
        target = self._config.upload_dir / f"base-image{suffix}"
        target.write_bytes(data)
        current = await self.get()
        current.baseImagePath = str(target)
        return await self.update(current)

    def _ensure_default(self) -> None:
        if self._path.exists():
            return
        defaults = CompanionSettings(
            nsfwEnabled=self._config.nsfw_default_enabled,
            memoryEnabled=self._config.memory_default_enabled,
        )
        write_json(self._path, defaults.model_dump())

