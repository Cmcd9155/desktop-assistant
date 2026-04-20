"""Persistence for user-editable companion settings."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import AppConfig
from app.models import CompanionSettings
from app.storage import read_json, write_json


class SettingsService:
    """Read, write, and initialize companion settings plus the base image anchor."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._path = config.data_dir / "settings.json"
        self._lock = asyncio.Lock()
        self._ensure_default()

    async def get(self) -> CompanionSettings:
        """Return the latest persisted settings."""
        async with self._lock:
            return self._read_unlocked()

    async def update(self, new_settings: CompanionSettings) -> CompanionSettings:
        """Persist the full settings payload supplied by the frontend."""
        async with self._lock:
            return self._write_unlocked(new_settings)

    async def save_base_image(self, filename: str, data: bytes) -> CompanionSettings:
        """Store an uploaded base image and point settings at the sanitized local path."""
        safe_name = Path(filename or "base-image.png").name
        suffix = Path(safe_name).suffix or ".png"
        # Reusing a stable filename keeps the frontend preview URL predictable across uploads.
        target = self._config.upload_dir / f"base-image{suffix}"
        async with self._lock:
            target.write_bytes(data)
            current = self._read_unlocked()
            current.baseImagePath = str(target)
            return self._write_unlocked(current)

    def _ensure_default(self) -> None:
        """Create a settings file on first run so the rest of the app can assume it exists."""
        if self._path.exists():
            return
        defaults = CompanionSettings(
            nsfwEnabled=self._config.nsfw_default_enabled,
            memoryEnabled=self._config.memory_default_enabled,
        )
        write_json(self._path, defaults.model_dump())

    def _read_unlocked(self) -> CompanionSettings:
        """Internal unlocked read for callers that already hold the service lock."""
        payload = read_json(self._path, {})
        settings = CompanionSettings.model_validate(payload)
        # NSFW mode is product-default and no longer user-configurable in UI.
        settings.nsfwEnabled = True
        return settings

    def _write_unlocked(self, settings: CompanionSettings) -> CompanionSettings:
        """Internal unlocked write that keeps read/update/save paths consistent."""
        settings.nsfwEnabled = True
        write_json(self._path, settings.model_dump())
        return settings
