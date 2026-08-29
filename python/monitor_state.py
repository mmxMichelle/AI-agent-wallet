"""Tiny offset checkpoint helper for the live monitor."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def load_last_offset(path: str | Path) -> Optional[str]:
    """Return the last saved offset string, or None if no state exists."""
    state_path = Path(path)
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    offset = data.get("last_offset")
    if offset is None:
        return None
    return str(offset)


def save_last_offset(path: str | Path, offset: int | str) -> None:
    """Atomically persist the latest processed offset."""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f".{state_path.name}.tmp")
    payload = {"last_offset": str(offset)}
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    os.replace(tmp_path, state_path)
