from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class CompanionState(str, Enum):
    idle = "idle"
    thinking = "thinking"
    smiling = "smiling"
    frowning = "frowning"
    moderated = "moderated"


class ImageJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    moderated = "moderated"
    failed = "failed"


class CompanionSettings(BaseModel):
    bio: str = Field(default="Helpful desktop companion.")
    instructions: str = Field(default="Be concise, clear, and useful.")
    baseImagePath: str = ""
    nsfwEnabled: bool = True
    memoryEnabled: bool = True


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    includeOpenClaw: bool = False


class ChatTurnResponse(BaseModel):
    replyText: str
    imageJobId: str
    emotion: CompanionState
    openclawRequestId: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ChatImageResponse(BaseModel):
    status: ImageJobStatus
    imageUrl: str | None = None
    moderated: bool = False
    errorCode: str | None = None


class OpenClawSendRequest(BaseModel):
    text: str = Field(min_length=1)


class OpenClawSendResponse(BaseModel):
    requestId: str
    sessionKey: str
    accepted: bool


class OpenClawPollResponse(BaseModel):
    events: list["OpenClawBridgeEvent"]
    cursor: str


class OpenClawBridgeEvent(BaseModel):
    requestId: str
    sourceSession: str
    role: str
    text: str
    ts: str


class MemoryItem(BaseModel):
    id: str
    text: str
    category: Literal["goal", "decision", "preference", "constraint", "context"]
    storedAt: str


class MemoryQueryResponse(BaseModel):
    items: list[MemoryItem]


class MemoryFlushRequest(BaseModel):
    trigger: Literal["inactivity", "toggle_off", "shutdown"] = "inactivity"


class MemoryFlushResponse(BaseModel):
    writtenCount: int
    summaryId: str


class MemoryDeleteResponse(BaseModel):
    ok: bool


class MemoryFlushEvent(BaseModel):
    trigger: Literal["inactivity", "toggle_off", "shutdown"]
    conversationRange: dict[str, str | int]
    summaryText: str
    storedAt: str


class ImageJob(BaseModel):
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
    id: str
    userText: str
    assistantText: str
    createdAt: str


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
