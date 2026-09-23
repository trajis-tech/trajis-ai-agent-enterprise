from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class Policy:
    raw: dict[str, Any]
    write_extensions: set[str] = field(default_factory=set)
    forbidden_names: set[str] = field(default_factory=set)
    forbidden_suffixes: set[str] = field(default_factory=set)
    request_limit: int = 20
    tool_calls_limit: int = 50
    total_tokens_limit: int = 200000
    per_request_input_tokens_limit: int = 100000
    run_timeout: int = 60
    run_memory: int = 1024 * 1024 * 1024
    run_cpu_seconds: int = 30
    run_process_limit: int = 8
    stdout_limit: int = 65536
    n8n_host: str = "127.0.0.1"
    n8n_port: int = 5678
    n8n_code_enabled: bool = False
    allowed_node_types: list[str] = field(default_factory=list)
    keep_recent_turns: int = 12
    max_tool_output_chars: int = 4000


def load_policy(path: Path) -> Policy:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text) or {}
    else:
        raw = _minimal_yaml(text)
    limits = raw.get("agent_limits") or {}
    run = raw.get("run_python") or {}
    n8n = raw.get("n8n") or {}
    hist = raw.get("history") or {}
    return Policy(
        raw=raw,
        write_extensions=set(raw.get("write_extensions") or []),
        forbidden_names=set(raw.get("forbidden_names") or [".env", "custom_api.json"]),
        forbidden_suffixes=set(raw.get("forbidden_suffixes") or [".pem", ".key"]),
        request_limit=int(limits.get("request_limit") or 20),
        tool_calls_limit=int(limits.get("tool_calls_limit") or 50),
        total_tokens_limit=int(limits.get("total_tokens_limit") or 200000),
        per_request_input_tokens_limit=int(limits.get("per_request_input_tokens_limit") or 100000),
        run_timeout=int(run.get("timeout_seconds") or 60),
        run_memory=int(run.get("memory_bytes") or 1024 * 1024 * 1024),
        run_cpu_seconds=int(run.get("cpu_seconds") or 30),
        run_process_limit=int(run.get("active_process_limit") or 8),
        stdout_limit=int(run.get("stdout_limit_bytes") or 65536),
        n8n_host=str(n8n.get("host") or "127.0.0.1"),
        n8n_port=int(n8n.get("port") or 5678),
        n8n_code_enabled=bool(n8n.get("code_node_enabled") or False),
        allowed_node_types=list(n8n.get("allowed_node_types") or []),
        keep_recent_turns=int(hist.get("keep_recent_turns") or 12),
        max_tool_output_chars=int(hist.get("max_tool_output_chars") or 4000),
    )


def _minimal_yaml(text: str) -> dict[str, Any]:
    """Tiny subset parser so tests can run without PyYAML."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(0, root)]
    pending_key: str | None = None
    pending_indent = 0
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = _scalar(line[2:].strip())
            indent_s, parent = stack[-1]
            if isinstance(parent, list):
                parent.append(item)
                continue
            if isinstance(parent, dict) and not parent and len(stack) >= 2:
                prev = stack[-2][1]
                if isinstance(prev, dict) and pending_key in prev and prev[pending_key] is parent:
                    lst: list[Any] = [item]
                    prev[pending_key] = lst
                    stack[-1] = (indent_s, lst)
                    continue
            continue
        if ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if not isinstance(parent, dict):
                while stack and not isinstance(stack[-1][1], dict):
                    stack.pop()
                parent = stack[-1][1]
            pending_key = key
            pending_indent = indent
            if rest == "":
                parent[key] = {}
                stack.append((indent + 2, parent[key]))
            else:
                parent[key] = _scalar(rest)
    return root


def _scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    return value.strip("'\"")
