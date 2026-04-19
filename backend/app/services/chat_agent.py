from __future__ import annotations

from app.models import CompanionSettings


class PrimaryChatAgent:
    """Single-agent chat path for MVP1."""

    async def reply(self, user_message: str, settings: CompanionSettings) -> str:
        # MVP1 keeps text generation deterministic and local-first for reliability.
        trimmed = user_message.strip()
        if not trimmed:
            return "I did not get a message to respond to."

        bio_hint = settings.bio.strip()
        style_hint = settings.instructions.strip()
        return (
            f"{bio_hint}\n\n"
            f"{style_hint}\n\n"
            f"Answer: {trimmed}"
        )

