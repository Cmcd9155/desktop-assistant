#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing env file: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    timeout: int = 30,
) -> tuple[int | str, dict | list | str]:
    data = None
    request_headers = headers or {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **request_headers}
    request = urllib.request.Request(url, headers=request_headers, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
    except Exception as exc:  # pragma: no cover - network/runtime variability
        return "exception", str(exc)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / "config" / "secrets" / "backend.env"
    load_env(env_path)

    results: dict[str, object] = {}

    xai_base = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").rstrip("/")
    xai_key = os.environ.get("XAI_API_KEY", "")
    xai_headers = {"Authorization": f"Bearer {xai_key}"}

    status, payload = request_json("GET", f"{xai_base}/models", headers=xai_headers, timeout=20)
    results["xai_models_status"] = status
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        results["xai_models_count"] = len(payload["data"])
    else:
        results["xai_models_payload_type"] = type(payload).__name__

    image_model = os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image")
    status, payload = request_json(
        "POST",
        f"{xai_base}/images/generations",
        headers=xai_headers,
        payload={
            "model": image_model,
            "prompt": "test portrait, simple line art",
            "response_format": "b64_json",
        },
        timeout=45,
    )
    results["xai_image_status"] = status
    if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"]:
        first = payload["data"][0]
        if isinstance(first, dict):
            results["xai_image_has_b64"] = bool(first.get("b64_json"))
            results["xai_image_has_url"] = bool(first.get("url"))
    else:
        results["xai_image_payload_type"] = type(payload).__name__
        if isinstance(payload, dict):
            results["xai_image_error"] = payload.get("error", payload)

    oc_base = os.environ.get("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")
    oc_session = os.environ.get("OPENCLAW_SESSION_KEY", "desktop-assistant-mvp1")
    oc_token = os.environ.get("OPENCLAW_AUTH_TOKEN", "")
    oc_headers: dict[str, str] = {}
    if oc_token:
        oc_headers["Authorization"] = f"Bearer {oc_token}"
        oc_headers["X-OpenClaw-Token"] = oc_token
    query = urllib.parse.urlencode({"session_key": oc_session, "limit": 5})
    status, payload = request_json("GET", f"{oc_base}/v1/responses?{query}", headers=oc_headers, timeout=20)
    results["openclaw_poll_status"] = status
    if isinstance(payload, dict):
        results["openclaw_payload_keys"] = sorted(payload.keys())
    else:
        results["openclaw_payload_type"] = type(payload).__name__
        results["openclaw_payload_preview"] = str(payload)[:200]

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
