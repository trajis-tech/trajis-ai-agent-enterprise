from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.agent_app import dispatch_tool, file_ctx
from backend.audit import AuditLog
from backend.deps import AppDeps
from backend.hashutil import sha256_file
from backend.jail import FilesystemJail, JailError, JailPolicy
from backend.n8n_client import N8nClient
from backend.policy import load_policy
from backend.snapshot import SnapshotStore
from backend.state import StateDB
from backend.tools_file import ToolConflict, edit_file
from backend.tools_n8n import PublishConflict, publish_workflow


class FakeN8n(N8nClient):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:9", None)
        self.store: dict = {}
        self.updated_at = "r1"

    def create_workflow(self, payload):
        self.store["1"] = dict(payload)
        return {"id": "1", "updatedAt": self.updated_at}

    def update_workflow(self, workflow_id, payload):
        self.store[workflow_id] = dict(payload)
        return {"id": workflow_id, "updatedAt": self.updated_at}

    def get_workflow(self, workflow_id):
        return {"id": workflow_id, "updatedAt": self.updated_at, **self.store.get(workflow_id, {})}


class AdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        fs = self.tmp / "filesystem"
        proj = fs / "projects" / "Ab3K9-demo"
        proj.mkdir(parents=True)
        (proj / "n8n" / "workflows").mkdir(parents=True)
        (fs / "system").mkdir()
        (proj / "a.py").write_text("x=1\n", encoding="utf-8")
        policy = load_policy(ROOT / "app" / "config" / "policy.yaml")
        jail = FilesystemJail(fs, fs / "system", proj, JailPolicy(write_extensions=policy.write_extensions))
        self.ctx_deps = AppDeps(
            fs_root=fs,
            system_root=fs / "system",
            project_root=proj,
            jail=jail,
            policy=policy,
            audit=AuditLog(self.tmp / "audit.jsonl"),
            snapshots=SnapshotStore(self.tmp / "snaps"),
            db=StateDB(self.tmp / "state.db"),
            project_id="Ab3K9",
            session_id="s1",
            turn_id="t1",
            n8n=FakeN8n(),
            interpreter=Path(sys.executable),
            pythonhome=Path(sys.executable).parent,
            staging_root=self.tmp / "staging",
        )

    def test_illegal_path(self) -> None:
        with self.assertRaises(JailError):
            dispatch_tool(self.ctx_deps, "read_file", {"path": r"C:\Windows\win.ini"})

    def test_unknown_tool(self) -> None:
        with self.assertRaises(KeyError):
            dispatch_tool(self.ctx_deps, "rm_rf", {"path": "."})

    def test_edit_conflict(self) -> None:
        ctx = file_ctx(self.ctx_deps)
        with self.assertRaises(ToolConflict):
            edit_file(ctx, "a.py", "x=1", "x=2", expected_sha256="deadbeef")

    def test_five_tools_sequential_writes(self) -> None:
        for i in range(5):
            dispatch_tool(self.ctx_deps, "write_file", {"path": f"n{i}.txt", "content": str(i)})
        listing = json.loads(dispatch_tool(self.ctx_deps, "ls", {"path": "."}))
        names = {item["name"] for item in listing}
        self.assertTrue({"n0.txt", "n4.txt"} <= names)

    def test_publish_create_then_conflict(self) -> None:
        wf = {
            "name": "demo",
            "nodes": [
                {
                    "id": "1",
                    "name": "Start",
                    "type": "n8n-nodes-base.manualTrigger",
                    "position": [0, 0],
                    "parameters": {},
                }
            ],
            "connections": {},
            "active": False,
        }
        dispatch_tool(self.ctx_deps, "write_workflow_json", {"path": "n8n/workflows/demo.json", "workflow": wf})
        out = json.loads(
            dispatch_tool(self.ctx_deps, "publish_workflow", {"path": "n8n/workflows/demo.json"}, approved=True)
        )
        self.assertEqual(out["action"], "CREATE")
        again = json.loads(
            dispatch_tool(self.ctx_deps, "publish_workflow", {"path": "n8n/workflows/demo.json"}, approved=True)
        )
        self.assertEqual(again["action"], "idempotent")
        self.ctx_deps.n8n.updated_at = "r2"
        (self.ctx_deps.project_root / "n8n" / "workflows" / "demo.json").write_text(
            (self.ctx_deps.project_root / "n8n" / "workflows" / "demo.json").read_text(encoding="utf-8").replace(
                '"demo"', '"demo2"'
            ),
            encoding="utf-8",
        )
        with self.assertRaises(PublishConflict):
            publish_workflow(
                file_ctx(self.ctx_deps),
                "n8n/workflows/demo.json",
                self.ctx_deps.policy,
                self.ctx_deps.n8n,
                self.ctx_deps.db,
                approved=True,
            )

    def test_publish_without_approval(self) -> None:
        with self.assertRaises(PermissionError):
            dispatch_tool(self.ctx_deps, "publish_workflow", {"path": "n8n/workflows/demo.json"}, approved=False)

    def test_expected_sha256_roundtrip(self) -> None:
        digest = sha256_file(self.ctx_deps.project_root / "a.py")
        out = json.loads(
            dispatch_tool(
                self.ctx_deps,
                "edit_file",
                {"path": "a.py", "old_text": "x=1", "new_text": "x=2", "expected_sha256": digest},
            )
        )
        self.assertIn("sha256", out)


if __name__ == "__main__":
    unittest.main()
