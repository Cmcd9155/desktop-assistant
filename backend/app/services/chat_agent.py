"""Text reply generation for the assistant persona.

This service tries the configured xAI text model first and falls back to a
local echo-style response so the UI keeps working even when credentials or
network access are unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import AppConfig
from app.models import CompanionSettings


@dataclass(slots=True)
class ChatReply:
    """Normalized reply object consumed by the main request handler."""

    reply_text: str
    image_action: str


def _extract_output_text(payload: dict[str, Any]) -> str:
    """Pull plain text out of the Responses-style payload shape returned by xAI/OpenAI APIs."""
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


def _strip_code_fence(text: str) -> str:
    """Undo a common model failure mode where JSON is wrapped in markdown fences."""
    stripped = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _normalize_field(payload: dict[str, Any], *keys: str) -> str:
    """Accept a few key variants so minor schema drift does not break parsing."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_structured_reply(raw_text: str) -> ChatReply | None:
    """Best-effort parse of the strict JSON contract we ask the model to return."""
    text = _strip_code_fence(raw_text)
    if not text:
        return None

    candidates: list[dict[str, Any]] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    if not candidates and "{" in text:
        start = text.find("{")
        decoder = json.JSONDecoder()
        try:
            parsed, _ = decoder.raw_decode(text[start:])
            if isinstance(parsed, dict):
                candidates.append(parsed)
        except json.JSONDecodeError:
            pass

    for candidate in candidates:
        reply_text = _normalize_field(candidate, "replyText", "reply_text")
        image_action = _normalize_field(candidate, "imageAction", "image_action")
        if reply_text:
            return ChatReply(reply_text=reply_text, image_action=image_action)
    return None


class PrimaryChatAgent:
    """Primary text reply agent with xAI online path + local fallback."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def reply(self, user_message: str, settings: CompanionSettings) -> ChatReply:
        """Generate the assistant's visible reply and a paired image action hint."""
        trimmed = user_message.strip()
        if not trimmed:
            return ChatReply(reply_text="I did not get a message to respond to.", image_action="")

        if not self._config.xai_api_key:
            # Missing credentials should degrade to a predictable local response, not an exception.
            return self._fallback_reply(trimmed)

        # The model is asked for strict JSON so the backend can split text reply from image direction.
        system_prompt = (
            "You are a desktop companion in a back-and-forth chat.\n"
            f"Bio: {settings.bio.strip() or 'Helpful desktop companion.'}\n"
            f"Instructions: {settings.instructions.strip() or 'Be concise, clear, and useful.'}\n"
            "Write a direct assistant reply to the user.\n"
            "Return strict JSON only with exactly two string fields:\n"
            '{"replyText":"...","imageAction":"..."}\n'
            "imageAction must be a short third-person visual directive for what the companion is doing now.\n"
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
            # Network issues should look like a softer product fallback, not a hard API failure.
            return self._fallback_reply(trimmed)

        if response.status_code >= 400:
            return self._fallback_reply(trimmed)

        payload = response.json() if response.content else {}
        generated = _extract_output_text(payload)
        if generated:
            parsed = _parse_structured_reply(generated)
            if parsed:
                return parsed
            # If the model ignored the JSON contract, still salvage the user-visible reply text.
            return ChatReply(reply_text=generated, image_action="")
        return self._fallback_reply(trimmed)

    def _fallback_reply(self, user_message: str) -> ChatReply:
        """Keep local development usable even without the remote text model."""
        return ChatReply(
            reply_text=(
                f"I heard you: {user_message}\n"
                "Tell me what you want next, and I will help."
            ),
            image_action="",
        )
