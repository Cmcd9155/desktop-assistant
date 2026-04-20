"""Tiny JSON persistence helpers.

The app persists state in local JSON files instead of a database, so these
helpers make reads forgiving and writes atomic enough for a single-user desktop
workflow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _atomic_write(path: Path, payload: Any) -> None:
    """Write via a temp file so partial crashes do not corrupt the target JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path, default: Any) -> Any:
    """Return parsed JSON when possible, otherwise fall back to a caller-provided default."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    """Keep a small public API so call sites do not care about temp-file details."""
    _atomic_write(path, payload)
