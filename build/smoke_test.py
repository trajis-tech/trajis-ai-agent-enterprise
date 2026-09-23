"""Post-install smoke checks. Stdlib only plus installed product/agent packages."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fail(message: str) -> None:
    raise SystemExit(f"SMOKE FAIL: {message}")


def _run(exe: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    if not exe.exists():
        _fail(f"missing executable {exe}")
    return subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
    )


def check_lockfile(lock: dict) -> None:
    for key in ("product_python", "agent_python", "node", "n8n_runtime", "openrpa_runtime"):
        item = lock[key]
        sha = str(item.get("sha256") or "")
        url = str(item.get("url") or "")
        if sha.startswith("REPLACE") or "REPLACE_" in url:
            _fail(f"{key} still has REPLACE placeholder in build.lock.json")
        if len(sha) != 64:
            _fail(f"{key} sha256 must be 64 hex chars")
    wheels = lock.get("wheels") or []
    if not wheels:
        _fail("wheels[] is empty; run build/pin_wheels.py before install")
    if not any(w.get("role") == "product" for w in wheels):
        _fail("wheels[] has no product entries")
    if not any(w.get("role") == "agent" for w in wheels):
        _fail("wheels[] has no agent entries")


def check_product_python() -> None:
    py = ROOT / "portable_python" / "python.exe"
    proc = _run(
        py,
        [
            "-c",
            "import pydantic_ai, starlette, uvicorn, opentelemetry.util; "
            "from pydantic_ai import Agent; "
            "print('product-ok', pydantic_ai.__version__)",
        ],
    )
    if proc.returncode != 0:
        _fail("product Python cannot import pydantic_ai/starlette:\n" + (proc.stderr or proc.stdout))
    if "pkg_resources" in (proc.stderr or ""):
        _fail("product import still depends on pkg_resources")


def check_agent_python() -> None:
    py = ROOT / "filesystem" / "system" / "python" / "python.exe"
    proc = _run(py, ["-c", "import numpy, pandas; print('agent-ok', numpy.__version__)"])
    if proc.returncode != 0:
        _fail("agent Python 3.14 cannot import numpy/pandas:\n" + (proc.stderr or proc.stdout))


def check_node() -> None:
    exe = ROOT / "filesystem" / "system" / "node" / "node.exe"
    proc = _run(exe, ["-v"])
    if proc.returncode != 0:
        _fail("node.exe -v failed:\n" + (proc.stderr or proc.stdout))


def check_pth(py_dir: Path) -> None:
    pths = list(py_dir.glob("python*._pth"))
    if not pths:
        _fail(f"missing python*._pth in {py_dir}")
    text = pths[0].read_text(encoding="utf-8")
    if not any(line.strip() == "import site" for line in text.splitlines()):
        _fail(f"{pths[0].name} does not enable site (need uncommented 'import site')")
    if "Lib\\site-packages" not in text and "Lib/site-packages" not in text:
        _fail(f"{pths[0].name} is missing Lib\\site-packages")


def check_n8n() -> None:
    marker = ROOT / "filesystem" / "system" / "n8n" / "node_modules" / "n8n"
    entry = marker / "bin" / "n8n"
    pkg = marker / "package.json"
    if not marker.exists() or not entry.exists() or not pkg.exists():
        _fail("n8n runtime missing; pack with build\\pack_n8n_runtime.bat and put zip+sha256 in lockfile")


def check_build_agent() -> None:
    py = ROOT / "portable_python" / "python.exe"
    proc = _run(
        py,
        [
            "-c",
            "import sys; sys.path.insert(0, r'%s'); "
            "from backend.agent_app import build_pydantic_agent, tool_specs; "
            "agent = build_pydantic_agent(None); "
            "names = {i['name'] for i in tool_specs()}; "
            "assert 'publish_workflow' in names and 'run_python' in names; "
            "registered = set(agent._function_toolset.tools); "
            "assert 'ls' in registered and 'publish_workflow' in registered; "
            "assert 'tool_ls' not in registered; "
            "print('agent-factory-ok')"
            % str(ROOT / "app").replace("\\", "\\\\"),
        ],
    )
    if proc.returncode != 0:
        _fail("build_pydantic_agent failed:\n" + (proc.stderr or proc.stdout))


def main() -> int:
    lock = json.loads((ROOT / "build.lock.json").read_text(encoding="utf-8"))
    check_lockfile(lock)
    check_pth(ROOT / "portable_python")
    check_pth(ROOT / "filesystem" / "system" / "python")
    check_product_python()
    check_agent_python()
    check_node()
    check_n8n()
    for name in ("OpenRPA.exe", "OpenRPA.Interfaces.dll", "LocalOpenRpaBridge.exe", "LocalOpenRpaBridge.exe.config"):
        if not (ROOT / "filesystem/system/openrpa" / name).is_file():
            _fail("OpenRPA runtime missing: " + name)
    check_build_agent()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
