from __future__ import annotations

from dataclasses import dataclass, field
import threading
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .jail import FilesystemJail
from .n8n_client import N8nClient
from .policy import Policy
from .snapshot import SnapshotStore
from .state import StateDB


@dataclass
class AppDeps:
    fs_root: Path
    system_root: Path
    project_root: Path
    jail: FilesystemJail
    policy: Policy
    audit: AuditLog
    snapshots: SnapshotStore
    db: StateDB
    project_id: str
    session_id: str
    turn_id: str
    n8n: N8nClient | None
    interpreter: Path
    pythonhome: Path
    staging_root: Path
    skip: dict[str, Any] | None = None
    chat_mode: str = "general"
    mode_epoch: int = 0
    search_config: Path | None = None
    automation: Any = None

    cancel_event: threading.Event = field(default_factory=threading.Event)
    tool_condition: threading.Condition = field(default_factory=threading.Condition)
    active_tools: int = 0
    progress: Any = None

    def wait_for_tools(self) -> None:
        with self.tool_condition:
            self.tool_condition.wait_for(lambda: self.active_tools == 0)
