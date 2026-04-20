"""Shared API and persistence models.

These types define the shape of data crossing boundaries between the frontend,
backend services, and on-disk JSON files so every layer can speak the same
language.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class CompanionState(str, Enum):
    """Visual state shown by the companion panel in the frontend."""

    idle = "idle"
    thinking = "thinking"
    smiling = "smiling"
    frowning = "frowning"
    moderated = "moderated"


class ImageJobStatus(str, Enum):
    """Lifecycle stages for asynchronous image generation jobs."""

    queued = "queued"
    running = "running"
    completed = "completed"
    moderated = "moderated"
    failed = "failed"


class CompanionSettings(BaseModel):
    """User-editable settings that customize behavior and defaults."""

    bio: str = Field(default="Helpful desktop companion.")
    instructions: str = Field(default="Be concise, clear, and useful.")
    baseImagePath: str = ""
    nsfwEnabled: bool = True
    memoryEnabled: bool = True


class ChatTurnRequest(BaseModel):
    """Single user turn submitted from the chat composer."""

    message: str = Field(min_length=1)
    includeOpenClaw: bool = False
    imageWidth: int | None = Field(default=None, ge=64, le=4096)
    imageHeight: int | None = Field(default=None, ge=64, le=4096)


class ChatTurnResponse(BaseModel):
    """Main reply payload returned immediately after a chat turn is accepted."""

    replyText: str
    imageAction: str
    imageJobId: str
    emotion: CompanionState
    openclawRequestId: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ChatImageResponse(BaseModel):
    """Polled status payload for the image job spawned by a chat turn."""

    status: ImageJobStatus
    imageUrl: str | None = None
    moderated: bool = False
    errorCode: str | None = None


class OpenClawSendRequest(BaseModel):
    """Payload used to dispatch a user turn into the OpenClaw sidecar."""

    text: str = Field(min_length=1)


class OpenClawSendResponse(BaseModel):
    """Acknowledgement returned when an OpenClaw request has been queued locally."""

    requestId: str
    sessionKey: str
    accepted: bool


class OpenClawPollResponse(BaseModel):
    """Cursor-based event page for the frontend's OpenClaw timeline."""

    events: list["OpenClawBridgeEvent"]
    cursor: str


class OpenClawBridgeEvent(BaseModel):
    """Normalized event entry shown in the OpenClaw timeline."""

    requestId: str
    sourceSession: str
    role: str
    text: str
    ts: str


class MemoryItem(BaseModel):
    """Condensed long-term memory fact extracted from prior turns."""

    id: str
    text: str
    category: Literal["goal", "decision", "preference", "constraint", "context"]
    storedAt: str


class MemoryQueryResponse(BaseModel):
    """Query wrapper used by the memory search endpoint."""

    items: list[MemoryItem]


class MemoryFlushRequest(BaseModel):
    """Request body for forcing a memory flush with a known trigger label."""

    trigger: Literal["inactivity", "toggle_off", "shutdown"] = "inactivity"


class MemoryFlushResponse(BaseModel):
    """Result of persisting one batch of memory items."""

    writtenCount: int
    summaryId: str


class MemoryDeleteResponse(BaseModel):
    """Simple acknowledgement for memory wipes."""

    ok: bool


class MemoryFlushEvent(BaseModel):
    """Audit record describing why and when a memory flush happened."""

    trigger: Literal["inactivity", "toggle_off", "shutdown"]
    conversationRange: dict[str, str | int]
    summaryText: str
    storedAt: str


class ImageJob(BaseModel):
    """Persisted bookkeeping record for one background image generation task."""

    id: str
    turnId: str
    promptHash: str
    status: ImageJobStatus
    moderated: bool = False
    outputPath: str = ""
    errorCode: str | None = None
    createdAt: str
    completedAt: str | None = None


class TurnRecord(BaseModel):
    """Full transcript record for one user/assistant exchange."""

    id: str
    userText: str
    assistantText: str
    createdAt: str


def utc_now_iso() -> str:
    """Generate a compact UTC timestamp string shared across persisted records."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
