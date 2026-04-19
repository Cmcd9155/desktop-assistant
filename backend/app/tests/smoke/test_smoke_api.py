from __future__ import annotations

import time


def test_health_endpoint(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("ok") == "true"


def test_chat_turn_text_first_and_image_job_terminal(client) -> None:
    response = client.post("/api/chat/turn", json={"message": "hello"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["replyText"]
    assert payload["imageJobId"]

    deadline = time.time() + 3
    terminal = {"completed", "moderated", "failed"}
    while time.time() < deadline:
        image_response = client.get(f"/api/chat/image/{payload['imageJobId']}")
        assert image_response.status_code == 200
        status = image_response.json()["status"]
        if status in terminal:
            break
        time.sleep(0.05)
    assert status in terminal


def test_settings_roundtrip(client) -> None:
    current = client.get("/api/settings/companion")
    assert current.status_code == 200
    body = current.json()
    body["bio"] = "Updated bio"
    updated = client.put("/api/settings/companion", json=body)
    assert updated.status_code == 200
    assert updated.json()["bio"] == "Updated bio"


def test_openclaw_endpoints_reachable(client, monkeypatch) -> None:
    async def fake_send(text: str):
        from app.models import OpenClawSendResponse

        return OpenClawSendResponse(requestId="req-1", sessionKey="test-session", accepted=True)

    async def fake_poll(cursor: str | None = None):
        from app.models import OpenClawBridgeEvent, OpenClawPollResponse

        return OpenClawPollResponse(
            events=[
                OpenClawBridgeEvent(
                    requestId="req-1",
                    sourceSession="test-session",
                    role="assistant",
                    text="[oc_req:req-1] hello",
                    ts="2026-04-19T00:00:00Z",
                )
            ],
            cursor="cursor-1",
        )

    monkeypatch.setattr(client.app.state.openclaw_service, "send", fake_send)
    monkeypatch.setattr(client.app.state.openclaw_service, "poll", fake_poll)

    send_response = client.post("/api/openclaw/send", json={"text": "ping"})
    assert send_response.status_code == 200
    assert send_response.json()["accepted"] is True

    poll_response = client.get("/api/openclaw/poll")
    assert poll_response.status_code == 200
    payload = poll_response.json()
    assert payload["cursor"] == "cursor-1"
    assert len(payload["events"]) == 1


def test_memory_endpoints_reachable(client) -> None:
    query = client.get("/api/memory")
    assert query.status_code == 200
    flush = client.post("/api/memory/flush", json={"trigger": "inactivity"})
    assert flush.status_code == 200
    wipe = client.delete("/api/memory")
    assert wipe.status_code == 200
    assert wipe.json()["ok"] is True

