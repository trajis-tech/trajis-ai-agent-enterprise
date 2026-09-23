from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .hashutil import sha256_text
from .models_n8n import WorkflowDocument, validate_workflow
from .n8n_client import N8nClient
from .policy import Policy
from .state import StateDB
from .tools_file import FileContext, write_file


class PublishConflict(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "CONFLICT"


def write_workflow_json(ctx: FileContext, path: str, workflow: dict[str, Any], policy: Policy) -> str:
    doc = WorkflowDocument.model_validate(workflow)
    errors = validate_workflow(doc, policy.allowed_node_types, policy.n8n_code_enabled)
    if errors:
        raise ValueError("; ".join(errors))
    payload = json.dumps(doc.model_dump(), ensure_ascii=False, indent=2)
    return write_file(ctx, path, payload)


def validate_workflow_file(ctx: FileContext, path: str, policy: Policy) -> str:
    target = ctx.jail.resolve(path, "read")
    doc = WorkflowDocument.model_validate_json(target.read_text(encoding="utf-8"))
    errors = validate_workflow(doc, policy.allowed_node_types, policy.n8n_code_enabled)
    return json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False)


def load_deployment(project_root: Path) -> dict[str, Any]:
    path = project_root / "n8n" / "deployment.json"
    if not path.exists():
        return {"workflows": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_deployment(ctx: FileContext, data: dict[str, Any]) -> None:
    write_file(ctx, "n8n/deployment.json", json.dumps(data, ensure_ascii=False, indent=2))


def publish_workflow(
    ctx: FileContext,
    path: str,
    policy: Policy,
    client: N8nClient | None,
    db: StateDB,
    approved: bool,
) -> str:
    if not approved:
        raise PermissionError("publish requires human approval")
    if client is None:
        raise RuntimeError("n8n is not ready")
    target = ctx.jail.resolve(path, "read")
    raw = target.read_text(encoding="utf-8")
    digest = sha256_text(raw)
    doc = WorkflowDocument.model_validate_json(raw)
    errors = validate_workflow(doc, policy.allowed_node_types, policy.n8n_code_enabled)
    if errors:
        raise ValueError("; ".join(errors))
    payload = doc.model_dump()
    payload["active"] = False
    deployment = load_deployment(ctx.project_root)
    records = deployment.setdefault("workflows", [])
    rec = next((item for item in records if item.get("workflow_file") == path), None)
    last = db.last_publish(ctx.project_id, path)
    if last and last.get("workflow_hash") == digest and last.get("n8n_workflow_id"):
        return json.dumps(
            {
                "action": "idempotent",
                "n8n_workflow_id": last["n8n_workflow_id"],
                "hash": digest,
            }
        )
    if rec and rec.get("n8n_workflow_id"):
        remote = client.get_workflow(str(rec["n8n_workflow_id"]))
        remote_updated = str(remote.get("updatedAt") or remote.get("versionId") or "")
        if rec.get("remote_revision") and remote_updated and remote_updated != rec.get("remote_revision"):
            raise PublishConflict("remote workflow changed in n8n UI")
        result = client.update_workflow(str(rec["n8n_workflow_id"]), payload)
        action = "UPDATE"
    else:
        result = client.create_workflow(payload)
        action = "CREATE"
    workflow_id = str(result.get("id") or (rec or {}).get("n8n_workflow_id") or "")
    revision = str(result.get("updatedAt") or result.get("versionId") or "")
    if rec is None:
        rec = {"workflow_file": path}
        records.append(rec)
    rec.update(
        {
            "n8n_workflow_id": workflow_id,
            "last_published_hash": digest,
            "remote_revision": revision,
        }
    )
    save_deployment(ctx, deployment)
    db.add_publish(ctx.project_id, path, digest, action, n8n_workflow_id=workflow_id, publish_call_id=str(uuid4()))
    ctx.audit.write(
        {
            "tool": "publish_workflow",
            "project_id": ctx.project_id,
            "turn_id": ctx.turn_id,
            "target": path,
            "result": action,
            "approved": True,
        }
    )
    return json.dumps({"action": action, "n8n_workflow_id": workflow_id, "hash": digest})
