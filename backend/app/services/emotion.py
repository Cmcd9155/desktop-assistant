"""Heuristic mapping from assistant reply text to a lightweight UI emotion state."""

from __future__ import annotations

from app.models import CompanionState


POSITIVE_MARKERS = {
    "great",
    "good",
    "awesome",
    "glad",
    "love",
    "nice",
    "yes",
    "perfect",
}

NEGATIVE_MARKERS = {
    "sorry",
    "cannot",
    "can't",
    "unable",
    "failed",
    "error",
    "no",
    "bad",
}


def map_emotion(reply_text: str) -> CompanionState:
    """Use simple keyword cues so the portrait can react without another model call."""
    text = reply_text.lower()
    if any(token in text for token in NEGATIVE_MARKERS):
        return CompanionState.frowning
    if any(token in text for token in POSITIVE_MARKERS):
        return CompanionState.smiling
    return CompanionState.idle
