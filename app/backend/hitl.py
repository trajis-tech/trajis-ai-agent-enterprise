from __future__ import annotations

from typing import Any


FORBIDDEN_CLIENT_KEYS = (
    "message_history",
    "args",
    "deferred_tool_results",
    "tool_args",
    "output",
)


def reject_client_overrides(body: dict[str, Any] | None) -> str | None:
    """HITL is server-owned. Browser may send only approval_id + decision."""
    if not body:
        return None
    for key in FORBIDDEN_CLIENT_KEYS:
        if key in body:
            return "client history/args are not accepted"
    return None
