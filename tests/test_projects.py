from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.projects import parse_project_dir, sanitize_title


class ProjectNameTests(unittest.TestCase):
    def test_legal(self) -> None:
        code, title = parse_project_dir("Ab3K9-月報自動化")
        self.assertEqual(code, "Ab3K9")
        self.assertEqual(title, "月報自動化")

    def test_illegal_short_code(self) -> None:
        with self.assertRaises(ValueError):
            parse_project_dir("proj-foo")

    def test_illegal_underscore(self) -> None:
        with self.assertRaises(ValueError):
            parse_project_dir("Ab3K9_標題")

    def test_illegal_dotdot(self) -> None:
        with self.assertRaises(ValueError):
            parse_project_dir("Ab3K9-../system")

    def test_sanitize_strips_bad_chars(self) -> None:
        self.assertEqual(sanitize_title('a/b:*?"<>|c'), "abc")
