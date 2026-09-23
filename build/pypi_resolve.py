"""Resolve PyPI wheels without pip. Stdlib only."""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from functools import lru_cache
from typing import Any

UA = "PortableAgentInstaller/1.0"
REQ_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


@lru_cache(maxsize=512)
def pypi_project(name: str) -> dict[str, Any]:
    return _get(f"https://pypi.org/pypi/{name}/json")


@lru_cache(maxsize=1024)
def pypi_release(name: str, version: str) -> dict[str, Any]:
    return _get(f"https://pypi.org/pypi/{name}/{version}/json")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text or text.startswith("#"):
        return None
    main, _, marker = text.partition(";")
    main = main.strip()
    extras: list[str] = []
    if "[" in main:
        name_part, rest = main.split("[", 1)
        extra_part, _, ver = rest.partition("]")
        extras = [e.strip().lower() for e in extra_part.split(",") if e.strip()]
        main = name_part.strip() + ver.strip()
    match = REQ_NAME.match(main)
    if not match:
        return None
    name = match.group(1)
    spec = main[len(name) :].strip()
    return {"name": name, "spec": spec, "extras": extras, "marker": marker.strip()}


class _Ver:
    """Numeric PEP 440-ish compare so '3.11' < '3.7' is False."""

    def __init__(self, raw: str) -> None:
        text = str(raw).strip()
        parts: list[int] = []
        for bit in re.split(r"[^0-9]+", text):
            if bit.isdigit():
                parts.append(int(bit))
        self.parts = tuple(parts or (0,))

    def _pair(self, other: object) -> tuple[tuple[int, ...], tuple[int, ...]]:
        right = other.parts if isinstance(other, _Ver) else _Ver(str(other)).parts
        n = max(len(self.parts), len(right))
        return self.parts + (0,) * (n - len(self.parts)), right + (0,) * (n - len(right))

    def __lt__(self, other: object) -> bool:
        a, b = self._pair(other)
        return a < b

    def __le__(self, other: object) -> bool:
        a, b = self._pair(other)
        return a <= b

    def __gt__(self, other: object) -> bool:
        a, b = self._pair(other)
        return a > b

    def __ge__(self, other: object) -> bool:
        a, b = self._pair(other)
        return a >= b

    def __eq__(self, other: object) -> bool:
        a, b = self._pair(other)
        return a == b

    def __ne__(self, other: object) -> bool:
        return not self == other


def python_version_for_tag(python_tag: str) -> str:
    if "cp311" in python_tag:
        return "3.11"
    if "cp314" in python_tag:
        return "3.14"
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def marker_ok(marker: str, python_tag: str, wanted_extras: set[str]) -> bool:
    if not marker:
        return True
    text = marker
    extra_m = re.search(r'extra\s*==\s*["\']([^"\']+)["\']', text)
    if extra_m and extra_m.group(1).lower() not in wanted_extras:
        return False
    collapsed = text.replace(" ", "")
    if "extra==" in collapsed:
        if not extra_m:
            return False
        text = re.sub(r'extra\s*==\s*["\'][^"\']+["\']', "True", text)
    py = python_version_for_tag(python_tag)
    env = {
        "python_version": _Ver(py),
        "python_full_version": _Ver(py + ".0"),
        "sys_platform": "win32",
        "platform_system": "Windows",
        "platform_machine": "AMD64",
        "os_name": "nt",
        "implementation_name": "cpython",
        "extra": next(iter(wanted_extras), ""),
        "True": True,
        "False": False,
    }
    try:
        return bool(eval(text, {"__builtins__": {}}, env))  # noqa: S307 - lockfile resolver, markers only
    except Exception:
        return False


# Backports that are stdlib on 3.11 / 3.14. Must not be installed.
STDLIB_BACKPORTS = {
    "contextvars",
    "dataclasses",
    "enum34",
    "funcsigs",
    "futures",
    "ipaddress",
    "pathlib2",
    "typing",
}


_PRE_TAGS = {
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "c": 2,
    "rc": 2,
    "pre": 2,
    "preview": 2,
}


def pep440_key(ver: str) -> tuple:
    """PEP 440 sort key. 1.10a0 < 1.10 < 1.28.0; finals sort after their prereleases."""
    raw = str(ver).strip()
    epoch = 0
    local = ""
    if "!" in raw:
        left, raw = raw.split("!", 1)
        epoch = int(left) if left.isdigit() else 0
    if "+" in raw:
        raw, local = raw.split("+", 1)
    raw = raw.lower()
    match = re.match(r"^(\d+(?:\.\d+)*)(.*)$", raw)
    if not match:
        return (epoch, (0,), (99, 0), -1, (1, 0), local)
    release = tuple(int(part) for part in match.group(1).split("."))
    rest = match.group(2) or ""
    pre = (99, 0)
    post = -1
    dev: tuple[int, int] = (1, 0)
    dev_m = re.search(r"[._-]?(?:dev)(\d*)$", rest)
    if dev_m:
        rest = rest[: dev_m.start()]
        dev = (0, int(dev_m.group(1) or 0))
    post_m = re.search(r"[._-]?(?:post|rev|r)(\d*)$", rest)
    if post_m:
        rest = rest[: post_m.start()]
        post = int(post_m.group(1) or 0)
    rest = rest.lstrip("._-")
    if rest:
        pre_m = re.match(r"(alpha|beta|preview|a|b|rc|c|pre)(\d*)", rest)
        if pre_m:
            pre = (_PRE_TAGS[pre_m.group(1)], int(pre_m.group(2) or 0))
    return (epoch, release, pre, post, dev, local)


def is_prerelease(ver: str) -> bool:
    key = pep440_key(ver)
    return key[2][0] != 99 or key[4][0] == 0


def spec_wants_prerelease(spec: str) -> bool:
    return bool(re.search(r"(?:a|b|rc|c|dev)\d", spec.lower()))


def pick_version(name: str, spec: str) -> str:
    data = pypi_project(name)
    versions = list((data.get("releases") or {}).keys())
    versions.sort(key=pep440_key, reverse=True)
    allow_pre = spec_wants_prerelease(spec)
    for ver in versions:
        if not allow_pre and is_prerelease(ver):
            continue
        if not (data["releases"].get(ver)):
            continue
        if _match_spec(ver, spec):
            return ver
    latest = str(data["info"]["version"])
    if _match_spec(latest, spec) and (allow_pre or not is_prerelease(latest)):
        return latest
    raise SystemExit(f"no version of {name} matches {spec or 'any'}")


def _match_spec(version: str, spec: str) -> bool:
    spec = spec.replace("(", "").replace(")", "").strip()
    if not spec:
        return True
    clauses = [c.strip() for c in spec.split(",") if c.strip()]
    for clause in clauses:
        m = re.match(r"^(==|!=|>=|<=|>|<|~=)\s*([0-9A-Za-z._+*!-]+)", clause)
        if not m:
            continue
        op, target = m.group(1), m.group(2)
        if op == "==":
            if target.endswith(".*"):
                prefix = target[:-2]
                v_rel = pep440_key(version)[1]
                p_rel = pep440_key(prefix)[1]
                if v_rel[: len(p_rel)] != p_rel:
                    return False
            elif version != target:
                return False
        elif op == "!=":
            if version == target:
                return False
        elif op in {">=", "<=", ">", "<"}:
            cmp = _cmp_ver(version, target)
            if op == ">=" and cmp < 0:
                return False
            if op == "<=" and cmp > 0:
                return False
            if op == ">" and cmp <= 0:
                return False
            if op == "<" and cmp >= 0:
                return False
        elif op == "~=":
            if _cmp_ver(version, target) < 0:
                return False
            left = pep440_key(version)[1]
            right = pep440_key(target)[1]
            if len(right) < 2:
                if left[:1] != right[:1]:
                    return False
            elif left[: len(right) - 1] != right[: len(right) - 1]:
                return False
    return True


def _cmp_ver(a: str, b: str) -> int:
    ka, kb = pep440_key(a), pep440_key(b)
    return (ka > kb) - (ka < kb)


def parse_wheel_tags(filename: str) -> tuple[str, str, str] | None:
    """Return (python, abi, platform) from a PEP 427 wheel filename."""
    if not filename.endswith(".whl"):
        return None
    parts = filename[:-4].split("-")
    if len(parts) < 3:
        return None
    return parts[-3], parts[-2], parts[-1]


def wheel_ok(filename: str, python_tag: str) -> bool:
    """True if this wheel can load on Windows amd64 + the requested CPython ABI.

    Embeddable CPython uses e.g. cp314, not the free-threaded cp314t ABI.
    """
    tags = parse_wheel_tags(filename)
    if not tags:
        return False
    py_tag, abi, plat = tags
    plat_bits = set(plat.split("."))
    if "manylinux" in plat or "macosx" in plat or "linux" in plat:
        return False
    if plat != "any" and "win_amd64" not in plat_bits:
        return False
    if abi.endswith("t") and abi != "none":
        return False
    py_bits = set(py_tag.split("."))
    if abi == "none" and plat == "any":
        return True
    if abi == "abi3" and "win_amd64" in plat_bits:
        return True
    if python_tag in py_bits and abi in {python_tag, "none"}:
        return True
    return False


def _wheel_score(filename: str, python_tag: str) -> int:
    tags = parse_wheel_tags(filename)
    if not tags or not wheel_ok(filename, python_tag):
        return -100
    py_tag, abi, plat = tags
    n = 1
    if python_tag in py_tag.split(".") and abi == python_tag and "win_amd64" in plat:
        n += 50
    elif abi == "abi3":
        n += 20
    elif plat == "any":
        n += 10
    if "win_amd64" in plat:
        n += 5
    return n


def find_compatible_release(name: str, python_tag: str, min_version: str = "") -> str | None:
    data = pypi_project(name)
    versions = list((data.get("releases") or {}).keys())
    versions.sort(key=pep440_key, reverse=True)
    min_key = pep440_key(min_version) if min_version else None
    for ver in versions:
        if is_prerelease(ver):
            continue
        if min_key is not None and pep440_key(ver) < min_key:
            continue
        files = data["releases"].get(ver) or []
        if any(
            f.get("packagetype") == "bdist_wheel" and wheel_ok(f.get("filename") or "", python_tag)
            for f in files
        ):
            return ver
    return None


def _pick_from_release(name: str, version: str, python_tag: str) -> dict[str, str] | None:
    try:
        data = pypi_release(name, version)
    except Exception:
        return None
    files = [
        f
        for f in (data.get("urls") or [])
        if f.get("packagetype") == "bdist_wheel" and wheel_ok(f.get("filename") or "", python_tag)
    ]
    if not files:
        return None
    files.sort(key=lambda item: _wheel_score(item.get("filename") or "", python_tag), reverse=True)
    chosen = files[0]
    return {
        "name": name,
        "version": version,
        "url": chosen["url"],
        "sha256": chosen["digests"]["sha256"],
        "filename": chosen["filename"],
    }


def choose_wheel(name: str, version: str, python_tag: str) -> dict[str, str]:
    chosen = _pick_from_release(name, version, python_tag)
    if chosen:
        return chosen
    alt = find_compatible_release(name, python_tag, min_version=version)
    if alt and alt != version:
        print(f"WARNING: {name}=={version} has no {python_tag} wheel; using {alt}")
        chosen = _pick_from_release(name, alt, python_tag)
        if chosen:
            return chosen
    raise SystemExit(f"no compatible wheel for {name}=={version} ({python_tag})")


def resolve_packages(packages: list[dict[str, Any]], python_tag: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    queue: list[tuple[str, str, set[str]]] = []
    for pkg in packages:
        extras = {e.lower() for e in (pkg.get("extras") or [])}
        queue.append((pkg["name"], pkg.get("version") or "", extras))
    while queue:
        name, version, extras = queue.pop(0)
        key = normalize(name)
        if key in seen:
            continue
        if key in STDLIB_BACKPORTS:
            seen.add(key)
            continue
        seen.add(key)
        if not version:
            version = pick_version(name, "")
        wheel = choose_wheel(name, version, python_tag)
        out.append(wheel)
        rel = pypi_release(name, wheel["version"])
        for raw in rel.get("info", {}).get("requires_dist") or []:
            parsed = parse_requirement(raw)
            if not parsed:
                continue
            if not marker_ok(parsed["marker"], python_tag, extras):
                continue
            child_ver = ""
            if parsed["spec"].startswith("=="):
                target = parsed["spec"][2:].strip()
                if "*" in target:
                    child_ver = pick_version(parsed["name"], parsed["spec"])
                else:
                    child_ver = target
            elif parsed["spec"]:
                child_ver = pick_version(parsed["name"], parsed["spec"])
            queue.append((parsed["name"], child_ver, set(parsed["extras"])))
    return out
