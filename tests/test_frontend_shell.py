from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "app" / "frontend"


class FrontendShellTests(unittest.TestCase):
    def test_hidden_menus_cannot_overlay_the_workspace(self) -> None:
        css = (FRONT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".toolbar-menu[hidden]", css)
        self.assertIn("display: none !important", css)
        self.assertIn("dialog:not([open])", css)
        self.assertIn(".view[hidden]", css)

    def test_agent_shell_has_chat_and_side_status(self) -> None:
        html = (FRONT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="chatLog"', html)
        self.assertIn('id="setupBanner"', html)
        self.assertIn('id="sideGateway"', html)
        self.assertIn('data-action="newProject"', html)
        self.assertIn('id="chatMode"', html)
        self.assertIn('id="dlgSearch"', html)
        self.assertIn('id="dlgAutomation"', html)
        self.assertIn('data-action="openAbout"', html)
        self.assertIn('id="dlgAbout"', html)
        self.assertIn(">0.0.1</div>", html)
        self.assertIn("一次設置 n8n 與 OpenRPA", html)

    def test_chat_has_timeout_and_safe_boot(self) -> None:
        js = (FRONT / "app.js").read_text(encoding="utf-8")
        self.assertIn("CHAT_TIMEOUT_MS", js)
        self.assertIn("withTimeout", js)
        self.assertIn("setBusy(false)", js)
        self.assertIn("DOMContentLoaded", js)
        self.assertIn("closeMenus", js)
