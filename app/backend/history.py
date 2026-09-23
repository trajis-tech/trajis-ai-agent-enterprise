from __future__ import annotations

from typing import Any

from .policy import Policy


def model_view(messages: list[dict[str, Any]], policy: Policy, pending_active: bool) -> list[dict[str, Any]]:
    """Build a compacted history for the model. Canonical messages stay in SQLite."""
    if pending_active:
        return list(messages)
    keep = max(policy.keep_recent_turns, 4)
    if len(messages) <= keep * 2:
        return [_trim_payload(item, policy) for item in messages]
    head = messages[:2]
    tail = messages[-(keep * 2) :]
    summary = {
        "role": "system",
        "payload": {
            "kind": "summary",
            "text": f"Earlier conversation truncated ({len(messages) - len(head) - len(tail)} messages omitted).",
        },
    }
    return [_trim_payload(item, policy) for item in [*head, summary, *tail]]


def _trim_payload(item: dict[str, Any], policy: Policy) -> dict[str, Any]:
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return item
    text = payload.get("content") or payload.get("text")
    if isinstance(text, str) and len(text) > policy.max_tool_output_chars:
        cloned = dict(item)
        cloned_payload = dict(payload)
        cloned_payload["content"] = text[: policy.max_tool_output_chars] + "\n[truncated tool output]"
        cloned["payload"] = cloned_payload
        return cloned
    return item


def to_agent_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten DB messages when the SDK history API is unavailable."""
    parts = []
    for item in messages:
        role = item.get("role") or "user"
        payload = item.get("payload") or {}
        text = payload.get("content") or payload.get("text") or ""
        if text:
            parts.append(f"{role}: {text}")
    return "\n".join(parts[-20:])
