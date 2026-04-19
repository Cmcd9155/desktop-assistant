#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAgMBgNmPR9kAAAAASUVORK5CYII="
)


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_env(root / "config" / "secrets" / "backend.env")

    image_data = base64.b64encode(PNG_1X1).decode("ascii")
    image_data_uri = f"data:image/png;base64,{image_data}"
    payloads = {
        "shape_a_image_object": {
            "model": os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image"),
            "prompt": "edit test",
            "response_format": "b64_json",
            "image": {"type": "image_url", "url": image_data_uri},
        },
        "shape_b_image_string": {
            "model": os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image"),
            "prompt": "edit test",
            "response_format": "b64_json",
            "image": image_data_uri,
        },
        "shape_c_image_url_field": {
            "model": os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image"),
            "prompt": "edit test",
            "response_format": "b64_json",
            "image_url": image_data_uri,
        },
        "shape_d_images_array": {
            "model": os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image"),
            "prompt": "edit test",
            "response_format": "b64_json",
            "images": [{"type": "image_url", "url": image_data_uri}],
        },
    }

    for name, payload in payloads.items():
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").rstrip("/") + "/images/edits",
            headers={
                "Authorization": f"Bearer {os.environ.get('XAI_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            data=data,
            method="POST",
        )
        print(f"=== {name} ===")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                print(resp.status)
                print(raw[:500])
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            print(exc.code)
            print(raw[:500])
        except Exception as exc:
            print(f"exception: {exc}")


if __name__ == "__main__":
    main()

