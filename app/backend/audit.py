from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .atomic import atomic_write_text


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> str:
        event_id = str(event.get("event_id") or uuid4())
        payload = {
            "event_id": event_id,
            "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            **event,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return event_id


def ensure_newline_file(path: Path) -> None:
    if not path.exists():
        atomic_write_text(path, "")
