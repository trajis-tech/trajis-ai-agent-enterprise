from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.n8n_rewrite import rewrite_location


class RewriteTests(unittest.TestCase):
    def test_absolute_upstream(self) -> None:
        self.assertEqual(
            rewrite_location("http://127.0.0.1:5678/workflow/1", "http://127.0.0.1:5678"),
            "/n8n/workflow/1",
        )

    def test_relative(self) -> None:
        self.assertEqual(rewrite_location("/signin", "http://127.0.0.1:5678"), "/n8n/signin")

    def test_already_prefixed(self) -> None:
        self.assertEqual(rewrite_location("/n8n/ok", "http://127.0.0.1:5678"), "/n8n/ok")
