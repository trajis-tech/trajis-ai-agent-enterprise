from __future__ import annotations

import json
from typing import Any

try:
    from pydantic import BaseModel, Field

    class WorkflowSettings(BaseModel):
        executionOrder: str = "v1"

    class WorkflowNode(BaseModel):
        id: str
        name: str
        type: str
        typeVersion: float | int = 1
        position: list[float] = Field(default_factory=lambda: [0, 0])
        parameters: dict[str, Any] = Field(default_factory=dict)
        credentials: dict[str, Any] | None = None

    class WorkflowDocument(BaseModel):
        name: str
        nodes: list[WorkflowNode]
        connections: dict[str, Any] = Field(default_factory=dict)
        settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
        active: bool = False

except ImportError:  # pragma: no cover - tests without product wheels
    from dataclasses import asdict, dataclass, field

    @dataclass
    class WorkflowSettings:
        executionOrder: str = "v1"

        @classmethod
        def model_validate(cls, data: Any) -> "WorkflowSettings":
            if isinstance(data, cls):
                return data
            data = data or {}
            return cls(executionOrder=str(data.get("executionOrder") or "v1"))

        @classmethod
        def model_validate_json(cls, text: str) -> "WorkflowSettings":
            return cls.model_validate(json.loads(text))

        def model_dump(self) -> dict[str, Any]:
            return asdict(self)

    @dataclass
    class WorkflowNode:
        id: str
        name: str
        type: str
        typeVersion: float | int = 1
        position: list = field(default_factory=lambda: [0.0, 0.0])
        parameters: dict = field(default_factory=dict)
        credentials: dict | None = None

        @classmethod
        def model_validate(cls, data: Any) -> "WorkflowNode":
            if isinstance(data, cls):
                return data
            return cls(
                id=str(data["id"]),
                name=str(data["name"]),
                type=str(data["type"]),
                typeVersion=data.get("typeVersion", 1),
                position=list(data.get("position") or [0.0, 0.0]),
                parameters=dict(data.get("parameters") or {}),
                credentials=data.get("credentials"),
            )

        def model_dump(self) -> dict[str, Any]:
            return asdict(self)

    @dataclass
    class WorkflowDocument:
        name: str
        nodes: list
        connections: dict = field(default_factory=dict)
        settings: WorkflowSettings = field(default_factory=WorkflowSettings)
        active: bool = False

        @classmethod
        def model_validate(cls, data: Any) -> "WorkflowDocument":
            if isinstance(data, cls):
                return data
            nodes = [WorkflowNode.model_validate(item) for item in (data.get("nodes") or [])]
            return cls(
                name=str(data["name"]),
                nodes=nodes,
                connections=dict(data.get("connections") or {}),
                settings=WorkflowSettings.model_validate(data.get("settings") or {}),
                active=bool(data.get("active") or False),
            )

        @classmethod
        def model_validate_json(cls, text: str) -> "WorkflowDocument":
            return cls.model_validate(json.loads(text))

        def model_dump(self) -> dict[str, Any]:
            return asdict(self)


CODE_NODE_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
}


def validate_workflow(doc: WorkflowDocument, allowed_types: list[str], code_enabled: bool) -> list[str]:
    errors: list[str] = []
    if doc.active:
        errors.append("active must be false; do not auto-activate")
    for node in doc.nodes:
        if node.type in CODE_NODE_TYPES and not code_enabled:
            errors.append(f"code node disabled: {node.name}")
        if allowed_types and node.type not in allowed_types and node.type not in CODE_NODE_TYPES:
            errors.append(f"node type not allowed: {node.type}")
        if node.credentials:
            errors.append(f"credentials are not allowed in agent JSON: {node.name}")
    return errors
