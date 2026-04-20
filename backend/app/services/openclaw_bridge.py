"""Asynchronous bridge to a local OpenClaw gateway.

The main chat experience should not block on the OpenClaw sidecar. This service
therefore accepts requests quickly, dispatches them in the background, and
stores timeline events the frontend can poll later.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.config import AppConfig
from app.models import OpenClawBridgeEvent, OpenClawPollResponse, OpenClawSendResponse
from app.storage import read_json, write_json


def _now_iso() -> str:
    """Generate the same compact UTC timestamps used elsewhere in persisted state."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _extract_output_text(payload: dict[str, Any]) -> str:
    """Flatten a Responses-style payload into plain text for the timeline UI."""
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
            if isinstance(text, str):
                chunks.append(text)
    return " ".join(chunks).strip()


class OpenClawBridgeService:
    """Queue, dispatch, and persist OpenClaw bridge activity."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._state_path = config.data_dir / "openclaw_state.json"
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def _headers(self) -> dict[str, str]:
        """Only attach auth headers when token mode is configured locally."""
        token = (self._config.openclaw_auth_token or "").strip()
        if self._config.openclaw_auth_mode != "token" or not token:
            return {}
        return {
            "Authorization": f"Bearer {token}",
            "X-OpenClaw-Token": token,
        }

    async def send(self, text: str) -> OpenClawSendResponse:
        """Track a request locally and start the background dispatch task."""
        request_id = str(uuid4())
        # Prefixing the user text lets downstream consumers correlate responses back to a turn.
        tagged = f"[oc_req:{request_id}] {text}"

        async with self._lock:
            state = self._load_state()
            tracked = set(state.get("trackedRequestIds", []))
            tracked.add(request_id)
            state["trackedRequestIds"] = sorted(tracked)
            self._save_state(state)

        task = asyncio.create_task(self._dispatch_and_capture(request_id=request_id, tagged_text=tagged))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return OpenClawSendResponse(
            requestId=request_id,
            sessionKey=self._config.openclaw_session_key,
            accepted=True,
        )

    async def _dispatch_and_capture(self, *, request_id: str, tagged_text: str) -> None:
        """Send one request to OpenClaw and append the resulting event to the local log."""
        body = {
            "model": self._config.openclaw_model,
            "input": tagged_text,
            "stream": False,
        }
        event_role = "assistant"
        event_text = "OpenClaw response completed."
        try:
            async with httpx.AsyncClient(timeout=self._config.openclaw_timeout_seconds) as client:
                response = await client.post(
                    f"{self._config.openclaw_base_url}/v1/responses",
                    headers=self._headers(),
                    json=body,
                )
                if 200 <= response.status_code < 300:
                    payload = response.json() if response.content else {}
                    output_text = _extract_output_text(payload)
                    if output_text:
                        event_text = output_text
                else:
                    # Surface remote failures as timeline events so the user can see what happened.
                    event_role = "system"
                    event_text = f"OpenClaw request failed with status {response.status_code}."
        except Exception as exc:  # pragma: no cover - network variability
            event_role = "system"
            event_text = f"OpenClaw request error: {type(exc).__name__}"

        event = OpenClawBridgeEvent(
            requestId=request_id,
            sourceSession=self._config.openclaw_session_key,
            role=event_role,
            text=event_text,
            ts=_now_iso(),
        )

        async with self._lock:
            state = self._load_state()
            next_cursor = int(state.get("nextCursor", 0)) + 1
            event_log = list(state.get("eventLog", []))
            event_log.append({"cursor": next_cursor, "event": event.model_dump()})
            # Keep a bounded local log so long-running sessions do not grow without limit.
            state["eventLog"] = event_log[-2000:]
            state["nextCursor"] = next_cursor
            self._save_state(state)

    async def poll(self, cursor: str | None = None) -> OpenClawPollResponse:
        """Return events newer than the caller's cursor and advance the stored cursor."""
        async with self._lock:
            state = self._load_state()
            requested_cursor = cursor or str(state.get("cursor", "0"))
            try:
                cursor_value = max(int(requested_cursor), 0)
            except ValueError:
                cursor_value = 0
            event_log = list(state.get("eventLog", []))
            matched: list[OpenClawBridgeEvent] = []
            max_cursor = cursor_value
            for row in event_log:
                if not isinstance(row, dict):
                    continue
                row_cursor = int(row.get("cursor", 0))
                if row_cursor <= cursor_value:
                    continue
                event_raw = row.get("event")
                if not isinstance(event_raw, dict):
                    continue
                matched.append(OpenClawBridgeEvent.model_validate(event_raw))
                max_cursor = max(max_cursor, row_cursor)
            next_cursor = str(max_cursor)
            state["cursor"] = next_cursor
            self._save_state(state)
            return OpenClawPollResponse(events=matched, cursor=next_cursor)

    def _load_state(self) -> dict[str, Any]:
        """Initialize missing fields so polling logic can assume a stable state shape."""
        state = read_json(self._state_path, {})
        state.setdefault("cursor", "0")
        state.setdefault("trackedRequestIds", [])
        state.setdefault("eventLog", [])
        state.setdefault("nextCursor", 0)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        write_json(self._state_path, state)
