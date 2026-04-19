from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config import AppConfig
from app.models import MemoryFlushEvent, MemoryFlushResponse, MemoryItem, TurnRecord, utc_now_iso
from app.storage import read_json, write_json


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


class MemoryService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._transcript_path = config.data_dir / "transcript.json"
        self._memory_path = config.data_dir / "memory_items.json"
        self._events_path = config.data_dir / "memory_flush_events.json"
        self._runtime_path = config.data_dir / "runtime_state.json"
        self._lock = asyncio.Lock()

    async def record_turn(self, *, turn_id: str, user_text: str, assistant_text: str) -> None:
        async with self._lock:
            turns = self._load_transcript()
            turns.append(
                TurnRecord(
                    id=turn_id,
                    userText=user_text,
                    assistantText=assistant_text,
                    createdAt=utc_now_iso(),
                ).model_dump()
            )
            write_json(self._transcript_path, turns)
            runtime = self._load_runtime()
            runtime["lastActivityAt"] = utc_now_iso()
            write_json(self._runtime_path, runtime)

    async def maybe_flush_for_inactivity(self, *, memory_enabled: bool) -> MemoryFlushResponse | None:
        if not memory_enabled:
            return None
        async with self._lock:
            runtime = self._load_runtime()
            last_activity = runtime.get("lastActivityAt")
            if not last_activity:
                return None
            age = datetime.now(tz=timezone.utc) - _parse_iso(last_activity)
            if age < timedelta(minutes=self._config.memory_inactivity_minutes):
                return None
            return await self._flush_locked(trigger="inactivity", force=False)

    async def flush(self, *, trigger: str, force: bool = False) -> MemoryFlushResponse:
        async with self._lock:
            return await self._flush_locked(trigger=trigger, force=force)

    async def query(self, query: str) -> list[MemoryItem]:
        async with self._lock:
            items = [MemoryItem.model_validate(x) for x in read_json(self._memory_path, [])]
            if not query:
                return items
            needle = query.lower()
            return [item for item in items if needle in item.text.lower()]

    async def wipe(self) -> None:
        async with self._lock:
            write_json(self._memory_path, [])
            write_json(self._events_path, [])
            runtime = self._load_runtime()
            runtime["lastFlushedTurnIndex"] = 0
            runtime["lastMemoryFlushAt"] = ""
            write_json(self._runtime_path, runtime)

    async def _flush_locked(self, *, trigger: str, force: bool) -> MemoryFlushResponse:
        turns = [TurnRecord.model_validate(x) for x in self._load_transcript()]
        runtime = self._load_runtime()
        start_idx = int(runtime.get("lastFlushedTurnIndex", 0))

        if start_idx >= len(turns):
            return MemoryFlushResponse(writtenCount=0, summaryId=str(uuid4()))

        pending = turns[start_idx:]
        memory_items, summary_text = self._summarize(pending)
        summary_id = str(uuid4())

        if not memory_items and not force:
            return MemoryFlushResponse(writtenCount=0, summaryId=summary_id)

        existing = read_json(self._memory_path, [])
        existing.extend([item.model_dump() for item in memory_items])
        write_json(self._memory_path, existing)

        event = MemoryFlushEvent(
            trigger=trigger,  # type: ignore[arg-type]
            conversationRange={
                "fromTurnId": pending[0].id,
                "toTurnId": pending[-1].id,
                "count": len(pending),
            },
            summaryText=summary_text,
            storedAt=utc_now_iso(),
        )
        events = read_json(self._events_path, [])
        events.append(event.model_dump())
        write_json(self._events_path, events)

        runtime["lastFlushedTurnIndex"] = len(turns)
        runtime["lastMemoryFlushAt"] = utc_now_iso()
        write_json(self._runtime_path, runtime)

        return MemoryFlushResponse(writtenCount=len(memory_items), summaryId=summary_id)

    def _summarize(self, turns: list[TurnRecord]) -> tuple[list[MemoryItem], str]:
        lines: list[tuple[str, str]] = []
        for turn in turns:
            candidate = turn.userText.strip()
            lowered = candidate.lower()
            if any(token in lowered for token in ("goal", "want", "need to", "plan to")):
                lines.append(("goal", candidate))
            elif any(token in lowered for token in ("decide", "decision", "we should", "let's")):
                lines.append(("decision", candidate))
            elif any(token in lowered for token in ("prefer", "like", "usually", "always")):
                lines.append(("preference", candidate))
            elif any(token in lowered for token in ("must", "cannot", "can't", "constraint", "deadline")):
                lines.append(("constraint", candidate))

        if not lines:
            fallback = turns[-1].userText.strip()
            lines.append(("context", fallback))

        terse = lines[:6]
        items: list[MemoryItem] = []
        summary_parts: list[str] = []
        for category, text in terse:
            compact = " ".join(text.split())[:220]
            items.append(
                MemoryItem(
                    id=str(uuid4()),
                    category=category,  # type: ignore[arg-type]
                    text=compact,
                    storedAt=utc_now_iso(),
                )
            )
            summary_parts.append(f"[{category}] {compact}")
        return items, " | ".join(summary_parts)

    def _load_transcript(self) -> list[dict]:
        return read_json(self._transcript_path, [])

    def _load_runtime(self) -> dict:
        runtime = read_json(self._runtime_path, {})
        runtime.setdefault("lastActivityAt", "")
        runtime.setdefault("lastFlushedTurnIndex", 0)
        runtime.setdefault("lastMemoryFlushAt", "")
        runtime.setdefault("lastValidImagePath", "")
        return runtime

