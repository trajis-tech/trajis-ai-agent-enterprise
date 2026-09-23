from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.agent_app import dispatch_tool
from backend.audit import AuditLog
from backend.deps import AppDeps
from backend.jail import FilesystemJail, JailError, JailPolicy
from backend.n8n_client import N8nClient
from backend.policy import load_policy
from backend.snapshot import SnapshotStore
from backend.state import StateDB


def _deps() -> AppDeps:
    tmp = Path(tempfile.mkdtemp())
    fs = tmp / "filesystem"
    proj = fs / "projects" / "Ab3K9-demo"
    proj.mkdir(parents=True)
    (fs / "system").mkdir()
    (proj / "main.py").write_text("print(1)\n", encoding="utf-8")
    policy = load_policy(ROOT / "app" / "config" / "policy.yaml")
    return AppDeps(
        fs_root=fs,
        system_root=fs / "system",
        project_root=proj,
        jail=FilesystemJail(fs, fs / "system", proj, JailPolicy(write_extensions=policy.write_extensions)),
        policy=policy,
        audit=AuditLog(tmp / "audit.jsonl"),
        snapshots=SnapshotStore(tmp / "snaps"),
        db=StateDB(tmp / "state.db"),
        project_id="Ab3K9",
        session_id="s1",
        turn_id="t1",
        n8n=N8nClient("http://127.0.0.1:9", None),
        interpreter=Path(sys.executable),
        pythonhome=Path(sys.executable).parent,
        staging_root=tmp / "staging",
    )


class FunctionModelStyleTests(unittest.TestCase):
    """Stand-in for pydantic-ai FunctionModel: adversarial tool sequences without a live LLM."""

    def test_hallucinated_tool_name(self) -> None:
        with self.assertRaises(KeyError):
            dispatch_tool(_deps(), "execute", {"cmd": "whoami"})

    def test_illegal_absolute_path(self) -> None:
        with self.assertRaises(JailError):
            dispatch_tool(_deps(), "write_file", {"path": r"C:\Temp\x.py", "content": "x"})

    def test_schema_missing_path(self) -> None:
        with self.assertRaises(KeyError):
            dispatch_tool(_deps(), "read_file", {})

    def test_same_file_edits_second_conflicts(self) -> None:
        deps = _deps()
        first = json.loads(dispatch_tool(deps, "read_file", {"path": "main.py"}))
        dispatch_tool(
            deps,
            "edit_file",
            {
                "path": "main.py",
                "old_text": "print(1)",
                "new_text": "print(2)",
                "expected_sha256": first["sha256"],
            },
        )
        from backend.tools_file import ToolConflict

        with self.assertRaises(ToolConflict):
            dispatch_tool(
                deps,
                "edit_file",
                {
                    "path": "main.py",
                    "old_text": "print(1)",
                    "new_text": "print(3)",
                    "expected_sha256": first["sha256"],
                },
            )


@unittest.skipUnless(importlib.util.find_spec("pydantic_ai") is not None, "pydantic-ai not installed")
class TestModelSmoke(unittest.TestCase):
    def test_build_agent(self) -> None:
        from backend.agent_app import build_pydantic_agent, tool_specs

        agent = build_pydantic_agent(None)
        self.assertIsNotNone(agent)
        names = {item["name"] for item in tool_specs()}
        self.assertIn("publish_workflow", names)
        self.assertIn("run_python", names)
        registered = set(agent._function_toolset.tools)
        self.assertIn("ls", registered)
        self.assertIn("read_file", registered)
        self.assertIn("run_python", registered)
        self.assertIn("publish_workflow", registered)
        self.assertNotIn("tool_ls", registered)
        self.assertNotIn("tool_pub", registered)
