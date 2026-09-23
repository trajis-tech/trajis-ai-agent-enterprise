from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_runtime_bat_has_no_powershell_pip_npm(self) -> None:
        text = (ROOT / "build" / "install_runtime.bat").read_text(encoding="utf-8").lower()
        for banned in ("powershell", "pwsh", "invoke-webrequest", "npm", "npx", "get-pip", "pip "):
            self.assertNotIn(banned, text)

    def test_start_bat_does_not_download(self) -> None:
        text = (ROOT / "點此開始.bat").read_text(encoding="utf-8").lower()
        self.assertIn("install_runtime.bat", text)
        self.assertNotIn("curl", text)
        self.assertNotIn("powershell.exe", text)
        self.assertNotIn("pwsh", text)
        self.assertNotIn("invoke-webrequest", text)

    def test_wheel_installer_is_stdlib_only(self) -> None:
        text = (ROOT / "build" / "wheel_installer.py").read_text(encoding="utf-8")
        self.assertNotIn("import pip", text)
        self.assertIn("zipfile", text)
        self.assertIn("purelib", text)
        self.assertIn("platlib", text)
        self.assertIn("RECORD", text)
        self.assertIn("dist-info", text)

    def test_installer_does_not_mask_failures_as_ok(self) -> None:
        text = (ROOT / "build" / "install_from_lock.py").read_text(encoding="utf-8")
        self.assertNotIn("Product UI can still start", text)
        self.assertIn("wheels[] empty", text)
        self.assertIn("from smoke_test import main as smoke", text)
        self.assertIn("REPLACE_WITH_BUNDLE_SHA256", text)
        self.assertIn("lstrip(\"#\")", text)
        self.assertIn("_under_wheel_cache", text)

    def test_enable_pth_uncomments_import_site(self) -> None:
        import sys
        import tempfile

        sys.path.insert(0, str(ROOT / "build"))
        from install_from_lock import enable_pth

        tmp = Path(tempfile.mkdtemp())
        (tmp / "python311._pth").write_text("python311.zip\n.\n#import site\n", encoding="utf-8")
        enable_pth(tmp)
        lines = [line.strip() for line in (tmp / "python311._pth").read_text(encoding="utf-8").splitlines()]
        self.assertIn("import site", lines)
        self.assertNotIn("#import site", lines)
        self.assertEqual(lines.count("import site"), 1)
        self.assertIn("Lib\\site-packages", lines)
        self.assertTrue((tmp / "Lib" / "site-packages").is_dir())
