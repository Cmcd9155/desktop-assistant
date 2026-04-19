#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    config_path = Path("/home/cmcd9/.openclaw/openclaw.json")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    gateway = cfg.setdefault("gateway", {})
    http_cfg = gateway.setdefault("http", {})
    endpoints = http_cfg.setdefault("endpoints", {})
    responses = endpoints.setdefault("responses", {})
    responses["enabled"] = True
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("gateway.http.endpoints.responses.enabled=true")


if __name__ == "__main__":
    main()

