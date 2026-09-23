"""Install a wheel into a destination without pip.

Handles PEP 427 layout: root files, *.dist-info (including RECORD),
and .data/{purelib,platlib,scripts,data}.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


class WheelInstallError(RuntimeError):
    pass


def install_wheel(wheel_path: Path, dest: Path, scripts_dir: Path | None = None) -> None:
    wheel_path = wheel_path.resolve()
    dest = dest.resolve()
    if not wheel_path.is_file() or wheel_path.suffix.lower() != ".whl":
        raise WheelInstallError(f"not a wheel: {wheel_path}")
    dest.mkdir(parents=True, exist_ok=True)
    if scripts_dir is None:
        scripts_dir = dest.parent.parent / "Scripts"
        if dest.name == "site-packages" and dest.parent.name == "Lib":
            scripts_dir = dest.parent.parent / "Scripts"

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
        data_prefixes = sorted(
            {n.split(".data/")[0] + ".data/" for n in names if ".data/" in n}
        )

        with tempfile.TemporaryDirectory(prefix="whlinst_") as tmp:
            tmp_path = Path(tmp)
            zf.extractall(tmp_path)

            for prefix in data_prefixes:
                data_root = tmp_path.joinpath(*prefix.rstrip("/").split("/"))
                for kind in ("purelib", "platlib"):
                    src = data_root / kind
                    if src.is_dir():
                        _copy_tree(src, dest)
                src_scripts = data_root / "scripts"
                if src_scripts.is_dir():
                    scripts_dir.mkdir(parents=True, exist_ok=True)
                    _copy_tree(src_scripts, scripts_dir)
                src_data = data_root / "data"
                if src_data.is_dir():
                    _copy_tree(src_data, dest.parent.parent)
                shutil.rmtree(data_root, ignore_errors=True)

            for item in tmp_path.iterdir():
                target = dest / item.name
                if item.is_dir():
                    _copy_tree(item, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.rglob("*"):
        rel = child.relative_to(src)
        out = dest / rel
        if child.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install wheels without pip")
    parser.add_argument("--dest", required=True, help="site-packages directory")
    parser.add_argument("--scripts", default="", help="optional Scripts directory")
    parser.add_argument("wheels", nargs="+", help="wheel files")
    args = parser.parse_args(argv)
    dest = Path(args.dest)
    scripts = Path(args.scripts) if args.scripts else None
    for raw in args.wheels:
        wheel = Path(raw)
        print(f"Installing {wheel.name} -> {dest}")
        install_wheel(wheel, dest, scripts)
    print(json.dumps({"installed": [Path(w).name for w in args.wheels], "dest": str(dest)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WheelInstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
