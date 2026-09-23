from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from pypi_resolve import STDLIB_BACKPORTS, _cmp_ver, _match_spec, _wheel_score, is_prerelease, marker_ok, pep440_key, wheel_ok


class MarkerTests(unittest.TestCase):
    def test_old_python_backport_skipped_on_311(self) -> None:
        self.assertFalse(marker_ok('python_version < "3.7"', "cp311", set()))
        self.assertFalse(marker_ok('python_version < "3.11"', "cp311", set()))
        self.assertTrue(marker_ok('python_version >= "3.10"', "cp311", set()))

    def test_string_compare_trap(self) -> None:
        # Lexicographic "3.11" < "3.7" is True; version compare must be False.
        self.assertFalse(marker_ok('python_version < "3.7"', "cp311", set()))
        self.assertTrue(marker_ok('python_version >= "3.7"', "cp311", set()))

    def test_extra_not_requested(self) -> None:
        self.assertFalse(marker_ok('extra == "cli"', "cp311", {"openai"}))
        self.assertTrue(marker_ok('extra == "openai"', "cp311", {"openai"}))

    def test_stdlib_backports_listed(self) -> None:
        self.assertIn("contextvars", STDLIB_BACKPORTS)


class WheelTagTests(unittest.TestCase):
    def test_gil_cp314_win_accepted(self) -> None:
        self.assertTrue(wheel_ok("numpy-2.5.2-cp314-cp314-win_amd64.whl", "cp314"))

    def test_free_threaded_cp314t_rejected(self) -> None:
        self.assertFalse(wheel_ok("numpy-2.5.2-cp314-cp314t-win_amd64.whl", "cp314"))
        self.assertGreater(
            _wheel_score("numpy-2.5.2-cp314-cp314-win_amd64.whl", "cp314"),
            _wheel_score("numpy-2.5.2-cp314-cp314t-win_amd64.whl", "cp314"),
        )

    def test_any_and_abi3_accepted(self) -> None:
        self.assertTrue(wheel_ok("sympy-1.14.0-py3-none-any.whl", "cp314"))
        self.assertTrue(wheel_ok("charset_normalizer-3.5.1-cp37-abi3-win_amd64.whl", "cp314"))

    def test_other_python_and_unix_rejected(self) -> None:
        self.assertFalse(wheel_ok("numpy-2.2.6-cp311-cp311-win_amd64.whl", "cp314"))
        self.assertFalse(wheel_ok("numpy-2.5.2-cp314-cp314-manylinux2014_x86_64.whl", "cp314"))
        self.assertFalse(wheel_ok("numpy-2.5.2-cp314-cp314-macosx_11_0_arm64.whl", "cp314"))


class Pep440Tests(unittest.TestCase):
    def test_prerelease_sorts_before_final_and_newer_minors(self) -> None:
        self.assertLess(pep440_key("1.10a0"), pep440_key("1.28.0"))
        self.assertLess(pep440_key("1.28.0a1"), pep440_key("1.28.0"))
        self.assertGreater(pep440_key("1.28.0"), pep440_key("1.10a0"))
        self.assertGreater(_cmp_ver("2.9.0.post0", "2.9.0"), 0)

    def test_gte_does_not_accept_old_prerelease(self) -> None:
        self.assertTrue(is_prerelease("1.10a0"))
        self.assertFalse(is_prerelease("1.28.0"))
        self.assertFalse(_match_spec("1.10a0", ">=1.28.0"))
        self.assertTrue(_match_spec("1.39.0", ">=1.28.0"))
        self.assertTrue(_match_spec("1.28.0", ">=1.28.0"))

    def test_star_equals_matches_compatible_series(self) -> None:
        self.assertTrue(_match_spec("1.0.9", "==1.*"))
        self.assertTrue(_match_spec("1.16.0", "==1.*"))
        self.assertFalse(_match_spec("2.0.0", "==1.*"))
        self.assertFalse(_match_spec("10.0.0", "==1.*"))
        self.assertTrue(_match_spec("1.0.9", "==1.0.*"))
        self.assertFalse(_match_spec("1.1.0", "==1.0.*"))
