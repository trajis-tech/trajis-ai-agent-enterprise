from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.jail import FilesystemJail, JailError, JailPolicy


class JailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.fs = self.tmp / "filesystem"
        self.system = self.fs / "system"
        self.projects = self.fs / "projects"
        self.proj = self.projects / "Ab3K9-demo"
        self.other = self.projects / "Zz9Q1-other"
        self.runtime = self.fs / ".runtime"
        for path in (self.system, self.proj, self.other, self.runtime):
            path.mkdir(parents=True)
        (self.proj / "main.py").write_text("print(1)\n", encoding="utf-8")
        (self.system / "lib.py").write_text("x=1\n", encoding="utf-8")
        (self.other / "secret.txt").write_text("nope\n", encoding="utf-8")
        (self.runtime / "state.db").write_text("x", encoding="utf-8")
        self.jail = FilesystemJail(
            self.fs,
            self.system,
            self.proj,
            JailPolicy(write_extensions={".py", ".txt", ".json", ".md"}),
        )

    def test_read_project(self) -> None:
        path = self.jail.resolve("main.py", "read")
        self.assertTrue(path.exists())

    def test_read_system(self) -> None:
        path = self.jail.resolve(str(self.system / "lib.py"), "read")
        self.assertTrue(path.exists())

    def test_write_system_denied(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(str(self.system / "lib.py"), "write")
        self.assertEqual(ctx.exception.code, "SYSTEM_RO")

    def test_abs_c_drive(self) -> None:
        with self.assertRaises(JailError):
            self.jail.resolve(r"C:\Windows\notepad.exe", "read")

    def test_sibling(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(str(self.other / "secret.txt"), "read")
        self.assertEqual(ctx.exception.code, "SIBLING")

    def test_runtime_denied(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(str(self.runtime / "state.db"), "read")
        self.assertEqual(ctx.exception.code, "RUNTIME")

    def test_unc(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(r"\\server\share\file.txt", "read")
        self.assertEqual(ctx.exception.code, "UNC")

    def test_dotdot(self) -> None:
        with self.assertRaises(JailError):
            self.jail.resolve(r"..\Zz9Q1-other\secret.txt", "read")

    def test_env_forbidden(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(".env", "read")
        self.assertEqual(ctx.exception.code, "FORBIDDEN_NAME")

    def test_pem_forbidden(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve("secret.pem", "read")
        self.assertEqual(ctx.exception.code, "FORBIDDEN_EXT")

    def test_custom_api_forbidden(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve("custom_api.json", "read")
        self.assertEqual(ctx.exception.code, "FORBIDDEN_NAME")

    def test_illegal_write_extension(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve("payload.exe", "write")
        self.assertEqual(ctx.exception.code, "EXT")

    def test_symlink_escape(self) -> None:
        link = self.proj / "escape"
        try:
            link.symlink_to(Path(r"C:\Windows"))
        except OSError:
            self.skipTest("symlink creation requires privilege")
        with self.assertRaises(JailError):
            self.jail.resolve("escape", "read")

    def test_projects_root(self) -> None:
        with self.assertRaises(JailError) as ctx:
            self.jail.resolve(str(self.projects), "read")
        self.assertEqual(ctx.exception.code, "PROJECTS_ROOT")


if __name__ == "__main__":
    unittest.main()
