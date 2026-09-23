from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from wheel_installer import install_wheel


class WheelInstallerTests(unittest.TestCase):
    def test_purelib_and_dist_info(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        wheel = tmp / "demo-1.0-py3-none-any.whl"
        dest = tmp / "site-packages"
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("demo/__init__.py", "VALUE=1\n")
            zf.writestr("demo-1.0.dist-info/METADATA", "Name: demo\n")
            zf.writestr("demo-1.0.data/purelib/extra.py", "X=2\n")
        install_wheel(wheel, dest)
        self.assertTrue((dest / "demo" / "__init__.py").exists())
        self.assertTrue((dest / "extra.py").exists())
        self.assertTrue((dest / "demo-1.0.dist-info" / "METADATA").exists())


if __name__ == "__main__":
    unittest.main()
