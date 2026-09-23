#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record measurements from locked runtimes and product tests. Does not start OpenRPA GUI or n8n."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import winreg
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
PY = REPO / "portable_python" / "python.exe"
OUT = ROOT / "probes" / "runtime_probe.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path, limit: int = 200_000) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def contains_ascii(path: Path, needle: bytes) -> bool:
    data = path.read_bytes()
    return needle in data


def dotnet_release() -> dict:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as key:
            release, _ = winreg.QueryValueEx(key, "Release")
        # Microsoft docs: 394802 = 4.6.2 on Windows 10. We record the DWORD only.
        return {"ok": True, "release": int(release), "meets_394802": int(release) >= 394802}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def n8n_facts() -> dict:
    pkg = REPO / "filesystem" / "system" / "n8n" / "node_modules" / "n8n" / "package.json"
    openapi = REPO / "filesystem" / "system" / "n8n" / "node_modules" / "n8n" / "dist" / "public-api" / "v1" / "openapi.yml"
    loader = REPO / "filesystem" / "system" / "n8n" / "node_modules" / "n8n" / "dist" / "load-nodes-and-credentials.js"
    constants = REPO / "filesystem" / "system" / "n8n" / "node_modules" / "n8n-core" / "dist" / "constants.js"
    handler = REPO / "filesystem" / "system" / "n8n" / "node_modules" / "n8n" / "dist" / "public-api" / "v1" / "handlers" / "workflows" / "workflows.handler.js"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    yml = read_text(openapi, 400_000)
    return {
        "package_version": data.get("version"),
        "engines_node": (data.get("engines") or {}).get("node"),
        "openapi_has_publish": "/workflows/{id}/publish:" in yml,
        "openapi_has_activate": "/workflows/{id}/activate:" in yml,
        "openapi_activate_deprecated": "Deprecated: use POST /workflows/{id}/publish" in yml,
        "openapi_workflowCreate_required": all(item in yml for item in ("workflowCreate:", "- name", "- nodes", "- connections", "- settings")),
        "openapi_create_active_readonly": bool(re.search(r"workflowCreate:[\s\S]{0,800}active:\s+type: boolean\s+readOnly: true", yml)),
        "openapi_publish_409": "/workflows/{id}/publish:" in yml and "workflowPublishBlockedError" in yml,
        "CUSTOM_EXTENSION_ENV": "N8N_CUSTOM_EXTENSIONS" in constants.read_text(encoding="utf-8"),
        "loader_splits_semicolon": "CUSTOM_EXTENSION_ENV].split(';')" in loader.read_text(encoding="utf-8")
        or "CUSTOM_EXTENSION_ENV]).split(';')" in loader.read_text(encoding="utf-8"),
        "activate_handler_deprecated_since": "2026-07-23" in handler.read_text(encoding="utf-8"),
        "paths": {
            "package.json": str(pkg.relative_to(REPO)),
            "openapi.yml": str(openapi.relative_to(REPO)),
            "load-nodes-and-credentials.js": str(loader.relative_to(REPO)),
        },
    }


def node_facts() -> dict:
    license_path = REPO / "filesystem" / "system" / "node" / "LICENSE"
    version_path = REPO / "filesystem" / "system" / "node" / "node.exe"
    proc = subprocess.run(
        [str(version_path), "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(REPO),
    )
    text = license_path.read_text(encoding="utf-8", errors="replace")[:4000]
    mit = "Permission is hereby granted, free of charge" in text and "AS IS" in text
    return {
        "node_version_stdout": (proc.stdout or "").strip(),
        "node_version_exit": proc.returncode,
        "license_has_mit_permission_grant": mit,
        "license_path": str(license_path.relative_to(REPO)),
    }


def openrpa_facts() -> dict:
    cfg = REPO / "filesystem" / "system" / "openrpa" / "OpenRPA.exe.config"
    exe = REPO / "filesystem" / "system" / "openrpa" / "OpenRPA.exe"
    text = cfg.read_text(encoding="utf-8", errors="replace")
    sku = re.search(r'sku="([^"]+)"', text)
    return {
        "exe_exists": exe.is_file(),
        "supportedRuntime_sku": sku.group(1) if sku else None,
        "exe_contains_WorkingDir_ascii": contains_ascii(exe, b"WorkingDir") if exe.is_file() else False,
        "exe_contains_workingdir_ascii_lowercase": contains_ascii(exe, b"workingdir") if exe.is_file() else False,
        "config_path": str(cfg.relative_to(REPO)),
        "dotnet_ndp_v4_full": dotnet_release(),
    }


def python_package_facts() -> dict:
    code = r"""
import json, inspect
import starlette, uvicorn, httpx
from httpx._config import DEFAULT_TIMEOUT_CONFIG
from uvicorn.main import run
from starlette.applications import Starlette
sig = str(inspect.signature(run))
defaults = {k: repr(v.default) for k, v in inspect.signature(run).parameters.items() if k in ('host','port') }
print(json.dumps({
  'starlette': starlette.__version__,
  'uvicorn': uvicorn.__version__,
  'httpx': httpx.__version__,
  'httpx_default_timeout': getattr(DEFAULT_TIMEOUT_CONFIG, 'timeout', None) or getattr(DEFAULT_TIMEOUT_CONFIG, 'connect', None),
  'httpx_timeout_repr': repr(DEFAULT_TIMEOUT_CONFIG),
  'uvicorn_run_host_port_defaults': defaults,
  'starlette_init_params': list(inspect.signature(Starlette.__init__).parameters),
}, ensure_ascii=False))
"""
    proc = subprocess.run([str(PY), "-c", code], capture_output=True, text=True, timeout=20, cwd=str(REPO))
    if proc.returncode != 0:
        return {"ok": False, "stderr": proc.stderr[-2000:]}
    return {"ok": True, **json.loads(proc.stdout)}


def sqlite_facts() -> dict:
    proc = subprocess.run([str(PY), str(ROOT / "_sqlite_probe.py")], capture_output=True, text=True, timeout=20, cwd=str(REPO))
    return {"exit": proc.returncode, "stdout": proc.stdout.strip()}


def node_satisfies_engines(node_ver: str, engines: str) -> dict:
    m = re.match(r"v?(\d+)\.(\d+)", node_ver or "")
    e = re.match(r">=(\d+)\.(\d+)", engines or "")
    if not m or not e:
        return {"ok": False, "reason": "parse"}
    got = (int(m.group(1)), int(m.group(2)))
    need = (int(e.group(1)), int(e.group(2)))
    return {"ok": got >= need, "got": got, "need": need}


def run_unittests() -> dict:
    tests = [
        "tests/test_automation.py",
        "tests/test_search_mcp.py",
        "tests/test_chat_modes.py",
        "tests/test_knowledge.py",
        "tests/test_agent_tools.py",
    ]
    started = time.perf_counter()
    results = {}
    for path in tests:
        name = Path(path).stem
        code = (
            "import sys, unittest\n"
            f"sys.path.insert(0, r'{REPO / 'app'}')\n"
            f"sys.path.insert(0, r'{REPO / 'tests'}')\n"
            f"suite = unittest.defaultTestLoader.loadTestsFromName({name!r})\n"
            "r = unittest.TextTestRunner(verbosity=2).run(suite)\n"
            "sys.exit(0 if r.wasSuccessful() else 1)\n"
        )
        p = subprocess.run(
            [str(PY), "-c", code],
            capture_output=True,
            timeout=120,
            cwd=str(REPO),
        )
        text = ((p.stderr or b"") + (p.stdout or b"")).decode("utf-8", errors="replace")
        results[path] = {
            "exit": p.returncode,
            "ok": p.returncode == 0,
            "tail": text[-2000:],
        }
    return {
        "mode": "per_file",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "all_ok": all(item["ok"] for item in results.values()),
        "results": results,
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n8n = n8n_facts()
    node = node_facts()
    payload = {
        "probed_at": utc_now(),
        "method": "inspect locked files + import pinned packages + run selected unit tests; did not start OpenRPA GUI or n8n process",
        "n8n": n8n,
        "node": node,
        "node_vs_n8n_engines": node_satisfies_engines(node.get("node_version_stdout") or "", n8n.get("engines_node") or ""),
        "openrpa": openrpa_facts(),
        "python_packages": python_package_facts(),
        "sqlite": sqlite_facts(),
        "unittests": run_unittests(),
        "product_code": {
            "openrpa_launch_argv": ["OpenRPA.exe", "/workingdir", "<profile>"],
            "search_mcp_httpx_timeout": 15,
            "search_mcp_maps_403_429": True,
            "broker_test_origin_403": "tests/test_automation.py::test_broker_requires_auth_and_rejects_browser_origin",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "node": node.get("node_version_stdout"), "n8n": n8n.get("package_version"), "engines_ok": payload["node_vs_n8n_engines"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
