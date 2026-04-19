#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAgMBgNmPR9kAAAAASUVORK5CYII="
)


def load_env(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key] = value
    return loaded


def wait_for_health(base_url: str, timeout_s: int = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError("Backend health check did not become ready in time.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live API checks for all backend endpoints.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Absolute path to repository root.",
    )
    parser.add_argument(
        "--env-file",
        default="config/secrets/backend.env",
        help="Env file relative to repo root.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    env_file = (repo_root / args.env_file).resolve()
    backend_dir = repo_root / "backend"
    backend_python = backend_dir / ".venv" / "bin" / "python"
    if not backend_python.exists():
        print("ERROR: backend/.venv/bin/python not found; create backend venv first.")
        return 2
    if not env_file.exists():
        print(f"ERROR: env file not found: {env_file}")
        return 2

    env = os.environ.copy()
    env.update(load_env(env_file))
    env.setdefault("APP_ORIGIN", "http://127.0.0.1:5173")
    env.setdefault("APP_HOST", "127.0.0.1")
    env.setdefault("APP_PORT", "8787")

    process = subprocess.Popen(
        [
            str(backend_python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8787",
            "--app-dir",
            str(backend_dir),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    results: dict[str, Any] = {}
    failures: list[str] = []
    warnings: list[str] = []

    try:
        wait_for_health(args.base_url, timeout_s=30)
        results["health"] = "ok"

        with httpx.Client(base_url=args.base_url, timeout=45.0) as client:
            # Settings GET/PUT
            settings_get = client.get("/api/settings/companion")
            results["settings_get_status"] = settings_get.status_code
            if settings_get.status_code != 200:
                failures.append("GET /api/settings/companion")
                current_settings = {}
            else:
                current_settings = settings_get.json()
                updated_settings = dict(current_settings)
                updated_settings["bio"] = "Endpoint test bio"
                settings_put = client.put("/api/settings/companion", json=updated_settings)
                results["settings_put_status"] = settings_put.status_code
                if settings_put.status_code != 200:
                    failures.append("PUT /api/settings/companion")
                restore = client.put("/api/settings/companion", json=current_settings)
                results["settings_restore_status"] = restore.status_code

            # Base image upload
            upload = client.post(
                "/api/settings/companion/base-image",
                files={"file": ("base.png", PNG_1X1, "image/png")},
            )
            results["base_image_upload_status"] = upload.status_code
            if upload.status_code != 200:
                failures.append("POST /api/settings/companion/base-image")

            # Chat turn + image polling
            chat = client.post("/api/chat/turn", json={"message": "Endpoint validation turn", "includeOpenClaw": True})
            results["chat_turn_status"] = chat.status_code
            if chat.status_code != 200:
                failures.append("POST /api/chat/turn")
            else:
                chat_json = chat.json()
                job_id = chat_json.get("imageJobId")
                oc_req = chat_json.get("openclawRequestId")
                results["chat_openclaw_request_id"] = bool(oc_req)
                image_status = None
                deadline = time.time() + 45
                while time.time() < deadline and image_status not in {"completed", "moderated", "failed"}:
                    image_resp = client.get(f"/api/chat/image/{job_id}")
                    results["chat_image_status_code"] = image_resp.status_code
                    if image_resp.status_code != 200:
                        failures.append("GET /api/chat/image/:jobId")
                        break
                    image_json = image_resp.json()
                    image_status = image_json.get("status")
                    results["chat_image_error_code"] = image_json.get("errorCode")
                    results["chat_image_moderated"] = image_json.get("moderated")
                    time.sleep(0.75)
                results["chat_image_terminal_status"] = image_status
                if image_status not in {"completed", "moderated", "failed"}:
                    failures.append("GET /api/chat/image/:jobId terminal timeout")

            # Memory endpoints
            memory_get = client.get("/api/memory")
            results["memory_get_status"] = memory_get.status_code
            if memory_get.status_code != 200:
                failures.append("GET /api/memory")

            memory_flush = client.post("/api/memory/flush", json={"trigger": "inactivity"})
            results["memory_flush_status"] = memory_flush.status_code
            if memory_flush.status_code != 200:
                failures.append("POST /api/memory/flush")

            memory_delete = client.delete("/api/memory")
            results["memory_delete_status"] = memory_delete.status_code
            if memory_delete.status_code != 200:
                failures.append("DELETE /api/memory")

            # OpenClaw endpoints
            oc_send = client.post("/api/openclaw/send", json={"text": "Endpoint direct bridge test"})
            results["openclaw_send_status"] = oc_send.status_code
            if oc_send.status_code != 200:
                failures.append("POST /api/openclaw/send")
            else:
                accepted = bool(oc_send.json().get("accepted"))
                results["openclaw_send_accepted"] = accepted
                if not accepted:
                    warnings.append("OpenClaw send returned accepted=false (gateway unreachable or rejected).")

            oc_poll = client.get("/api/openclaw/poll")
            results["openclaw_poll_status"] = oc_poll.status_code
            if oc_poll.status_code != 200:
                failures.append("GET /api/openclaw/poll")

    finally:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass

    print(json.dumps({"results": results, "failures": failures, "warnings": warnings}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
