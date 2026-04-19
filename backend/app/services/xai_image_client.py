from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import AppConfig


PNG_1X1_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAgMBgNmPR9kAAAAASUVORK5CYII="
)


@dataclass(slots=True)
class ImageGenerationResult:
    image_bytes: bytes | None
    moderated: bool
    error_code: str | None
    raw: dict[str, Any] | None = None


def _extract_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("type") or "").strip()
        return message
    return str(payload.get("message") or "").strip()


def _is_moderation_error(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("moderation", "policy", "unsafe", "safety"))


def _image_data_url(path: Path) -> str:
    mime = "image/png"
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class XaiImageClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def generate_or_edit(
        self,
        *,
        prompt: str,
        base_image_path: Path | None,
        nsfw_enabled: bool,
    ) -> ImageGenerationResult:
        if not self._config.xai_api_key:
            return ImageGenerationResult(
                image_bytes=base64.b64decode(PNG_1X1_BASE64),
                moderated=False,
                error_code="xai_api_key_missing",
                raw={"warning": "XAI_API_KEY not set; using local placeholder image."},
            )

        prompt_prefix = (
            "Character template: anime desk companion, stable identity, consistent face, "
            "consistent clothing silhouette, high quality, soft lighting.\n"
            "Style: clean line art + painterly shading, single subject, desktop framing.\n"
            f"Policy intent: NSFW product mode is {'enabled' if nsfw_enabled else 'disabled'}.\n"
            "Follow platform safety policy while maximizing prompt fidelity.\n"
        )
        composed_prompt = f"{prompt_prefix}\nUser turn instruction:\n{prompt}"

        endpoint = "/images/edits" if base_image_path and base_image_path.exists() else "/images/generations"
        body: dict[str, Any] = {
            "model": self._config.xai_image_model,
            "prompt": composed_prompt,
            "response_format": "b64_json",
        }
        if endpoint == "/images/edits" and base_image_path:
            body["image_url"] = _image_data_url(base_image_path)

        headers = {
            "Authorization": f"Bearer {self._config.xai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(
            base_url=self._config.xai_api_base,
            timeout=self._config.xai_timeout_seconds,
        ) as client:
            response = await client.post(endpoint, headers=headers, json=body)
            payload = response.json() if response.content else {}

            if response.status_code >= 400:
                message = _extract_error(payload)
                if _is_moderation_error(message):
                    return ImageGenerationResult(
                        image_bytes=None,
                        moderated=True,
                        error_code="moderated",
                        raw=payload,
                    )
                return ImageGenerationResult(
                    image_bytes=None,
                    moderated=False,
                    error_code=f"http_{response.status_code}",
                    raw=payload,
                )

            data = payload.get("data") or []
            first = data[0] if data else {}
            moderation_value = payload.get("respect_moderation", first.get("respect_moderation", True))
            moderated = bool(moderation_value is False)

            if moderated:
                return ImageGenerationResult(
                    image_bytes=None,
                    moderated=True,
                    error_code="moderated",
                    raw=payload,
                )

            b64_json = first.get("b64_json")
            if isinstance(b64_json, str) and b64_json:
                return ImageGenerationResult(
                    image_bytes=base64.b64decode(b64_json),
                    moderated=False,
                    error_code=None,
                    raw=payload,
                )

            url = first.get("url")
            if isinstance(url, str) and url:
                image_resp = await client.get(url)
                if image_resp.status_code == 200 and image_resp.content:
                    return ImageGenerationResult(
                        image_bytes=image_resp.content,
                        moderated=False,
                        error_code=None,
                        raw=payload,
                    )

            return ImageGenerationResult(
                image_bytes=None,
                moderated=False,
                error_code="missing_image_data",
                raw=payload,
            )
