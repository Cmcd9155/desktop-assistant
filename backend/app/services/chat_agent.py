from __future__ import annotations

from typing import Any

import httpx

from app.config import AppConfig
from app.models import CompanionSettings


def _extract_output_text(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


class PrimaryChatAgent:
    """Primary text reply agent with xAI online path + local fallback."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def reply(self, user_message: str, settings: CompanionSettings) -> str:
        trimmed = user_message.strip()
        if not trimmed:
            return "I did not get a message to respond to."

        if not self._config.xai_api_key:
            return self._fallback_reply(trimmed)

        system_prompt = (
            "You are a desktop companion in a back-and-forth chat.\n"
            f"Bio: {settings.bio.strip() or 'Helpful desktop companion.'}\n"
            f"Instructions: {settings.instructions.strip() or 'Be concise, clear, and useful.'}\n"
            "Write a direct assistant reply to the user.\n"
            "Do not repeat the bio/instructions verbatim.\n"
            "Do not prepend labels like 'Answer:'."
        )
        body = {
            "model": self._config.xai_text_model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": trimmed}],
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._config.xai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._config.xai_api_base,
                timeout=self._config.xai_timeout_seconds,
            ) as client:
                response = await client.post("/responses", headers=headers, json=body)
        except Exception:
            return self._fallback_reply(trimmed)

        if response.status_code >= 400:
            return self._fallback_reply(trimmed)

        payload = response.json() if response.content else {}
        generated = _extract_output_text(payload)
        if generated:
            return generated
        return self._fallback_reply(trimmed)

    def _fallback_reply(self, user_message: str) -> str:
        return (
            f"I heard you: {user_message}\n"
            "Tell me what you want next, and I will help."
        )
