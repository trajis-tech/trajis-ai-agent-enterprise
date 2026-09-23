"""Download remaining runtimes and wheels using only stdlib. No pip, no npm."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

OFFLINE = False
ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from pypi_resolve import normalize
from wheel_installer import install_wheel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    if OFFLINE:
        raise SystemExit("Offline mode forbids downloading: " + dest.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PortableAgentInstaller/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def is_placeholder(value: str | None) -> bool:
    text = str(value or "")
    return text.startswith("REPLACE") or "REPLACE_" in text or not text


def resolve_asset_path(url: str, filename: str) -> Path | None:
    if url.startswith("http://") or url.startswith("https://"):
        return None
    candidate = Path(url)
    if not candidate.is_absolute():
        candidate = ROOT / url
    if candidate.exists():
        return candidate
    local = ROOT / "vendor" / filename
    return local if local.exists() else None


def _under_wheel_cache(path: Path) -> bool:
    try:
        path.resolve().relative_to((ROOT / "vendor" / "wheels").resolve())
        return True
    except ValueError:
        return False


def verify(path: Path, expected: str | None) -> None:
    got = sha256_file(path)
    if is_placeholder(expected):
        raise SystemExit(
            f"lockfile sha256 for {path.name} is a placeholder\ncomputed {got}\n"
            "Fill build.lock.json before this install can succeed."
        )
    if got.lower() != str(expected).lower():
        if _under_wheel_cache(path):
            path.unlink(missing_ok=True)
        raise SystemExit(f"hash mismatch for {path.name}\nexpected {expected}\ngot {got}")


def enable_pth(py_dir: Path) -> None:
    """Enable site-packages on embeddable CPython.

    python*._pth ships with a commented ``#import site``. A substring check for
    ``import site`` would treat that comment as already enabled and skip the fix.
    """
    for pth in py_dir.glob("python*._pth"):
        lines = pth.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        has_site_packages = False
        has_import_site = False
        for line in lines:
            stripped = line.strip()
            if stripped.lstrip("#").strip() == "import site":
                if not has_import_site:
                    out.append("import site")
                    has_import_site = True
                continue
            normalized = stripped.replace("/", "\\")
            if normalized == "Lib\\site-packages" or normalized.endswith("\\Lib\\site-packages"):
                has_site_packages = True
            out.append(line)
        if not has_site_packages:
            out.append("Lib\\site-packages")
        if not has_import_site:
            out.append("import site")
        pth.write_text("\n".join(out) + "\n", encoding="utf-8")
    (py_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def extract_zip(archive: Path, dest: Path, strip_prefix: str | None = None) -> None:
    import zipfile

    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        if not strip_prefix:
            zf.extractall(dest)
            return
        for info in zf.infolist():
            name = info.filename
            prefix = strip_prefix.replace("\\", "/").rstrip("/") + "/"
            if name.replace("\\", "/").startswith(prefix):
                rel = name.replace("\\", "/")[len(prefix) :]
            elif name.replace("\\", "/").rstrip("/") == strip_prefix.replace("\\", "/"):
                continue
            else:
                rel = name
            if not rel:
                continue
            target = dest / rel
            if info.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)


def remove_installed_dist(site: Path, dist_name: str) -> None:
    needle = normalize(dist_name).replace("-", "_")
    for info in list(site.glob("*.dist-info")):
        base = info.name[: -len(".dist-info")]
        pkg = base.split("-", 1)[0].replace("-", "_").lower()
        if pkg != needle:
            continue
        record = info / "RECORD"
        if record.exists():
            for line in record.read_text(encoding="utf-8").splitlines():
                rel = line.split(",", 1)[0].replace("\\", "/").lstrip("/")
                if not rel or rel.startswith(".."):
                    continue
                target = (site / rel).resolve()
                try:
                    target.relative_to(site.resolve())
                except ValueError:
                    continue
                if target.is_file():
                    target.unlink(missing_ok=True)
        shutil.rmtree(info, ignore_errors=True)


def install_wheel_list(items: list[dict], dest: Path, cache: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    for item in items:
        wheel = cache / item["filename"]
        if not wheel.exists() or sha256_file(wheel).lower() != item["sha256"].lower():
            download(item["url"], wheel)
        verify(wheel, item["sha256"])
        print(f"Installing {item['filename']}")
        remove_installed_dist(dest, item["name"])
        install_wheel(wheel, dest)


def ensure_zip_runtime(item: dict, dest: Path, cache: Path, *, strip_prefix: str | None, marker: Path) -> None:
    if marker.exists():
        return
    filename = item["filename"]
    archive = cache / filename
    local = resolve_asset_path(item.get("url") or "", filename)
    if local is not None:
        print(f"Using local {local}")
        archive = local
    else:
        if is_placeholder(item.get("url")) or is_placeholder(item.get("sha256")):
            raise SystemExit(
                f"{filename} is not packed. Run build\\pack_n8n_runtime.bat, "
                "put the zip under vendor\\, and fill url+sha256 in build.lock.json"
            )
        if not archive.exists() or sha256_file(archive).lower() != str(item["sha256"]).lower():
            download(item["url"], archive)
    verify(archive, item.get("sha256"))
    extract_zip(archive, dest, strip_prefix=strip_prefix)


def main() -> int:
    global OFFLINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    OFFLINE = args.offline
    lock = json.loads((ROOT / "build.lock.json").read_text(encoding="utf-8"))
    if OFFLINE:
        from deployment_assets import require_offline_assets
        require_offline_assets(ROOT, lock)
    cache = ROOT / "vendor" / "wheels"
    cache.mkdir(parents=True, exist_ok=True)

    agent_py = ROOT / "filesystem" / "system" / "python"
    agent_zip = cache / lock["agent_python"]["filename"]
    if not (agent_py / "python.exe").exists():
        if not agent_zip.exists() or sha256_file(agent_zip).lower() != lock["agent_python"]["sha256"].lower():
            download(lock["agent_python"]["url"], agent_zip)
        verify(agent_zip, lock["agent_python"]["sha256"])
        extract_zip(agent_zip, agent_py)
    enable_pth(ROOT / "portable_python")
    enable_pth(agent_py)

    node_dir = ROOT / "filesystem" / "system" / "node"
    node_zip = cache / lock["node"]["filename"]
    if not (node_dir / "node.exe").exists():
        if not node_zip.exists() or sha256_file(node_zip).lower() != lock["node"]["sha256"].lower():
            download(lock["node"]["url"], node_zip)
        verify(node_zip, lock["node"]["sha256"])
        extract_zip(node_zip, node_dir, strip_prefix=lock["node"].get("strip_prefix"))

    product_site = ROOT / "portable_python" / "Lib" / "site-packages"
    agent_site = agent_py / "Lib" / "site-packages"
    pinned = [w for w in (lock.get("wheels") or []) if w.get("url") and w.get("sha256")]
    if not pinned:
        raise SystemExit("wheels[] empty; run build/pin_wheels.py and commit build.lock.json, then re-run install")
    product_wheels = [w for w in pinned if w.get("role") == "product"]
    agent_wheels = [w for w in pinned if w.get("role") != "product"]
    if not product_wheels or not agent_wheels:
        raise SystemExit("wheels[] must contain both product and agent roles")
    install_wheel_list(product_wheels, product_site, cache / "product")
    install_wheel_list(agent_wheels, agent_site, cache / "agent")

    n8n_dir = ROOT / "filesystem" / "system" / "n8n"
    n8n = lock["n8n_runtime"]
    n8n_zip = cache / n8n["filename"]
    marker = n8n_dir / "node_modules" / "n8n"
    local_n8n = resolve_asset_path(n8n.get("url") or "", n8n["filename"]) or (ROOT / "vendor" / n8n["filename"])
    if local_n8n.exists():
        n8n_zip = local_n8n
    if not marker.exists():
        if is_placeholder(n8n.get("sha256")):
            raise SystemExit(
                "n8n_runtime sha256 is still REPLACE_WITH_BUNDLE_SHA256\n"
                "Pack the bundle with build\\pack_n8n_runtime.bat and put URL/sha256 in build.lock.json"
            )
        if not n8n_zip.exists() or sha256_file(n8n_zip).lower() != str(n8n["sha256"]).lower():
            url = str(n8n.get("url") or "")
            if is_placeholder(url) or not url.startswith(("http://", "https://")):
                raise SystemExit(
                    "n8n_runtime url is a placeholder and vendor zip is missing"
                    if is_placeholder(url)
                    else (
                        f"n8n bundle missing at {ROOT / 'vendor' / n8n['filename']}\n"
                        "Pack with build\\pack_n8n_runtime.bat (do not npm on locked-down PCs)"
                    )
                )
            download(url, n8n_zip)
        verify(n8n_zip, n8n.get("sha256"))
        extract_zip(n8n_zip, n8n_dir)

    openrpa_dir = ROOT / "filesystem" / "system" / "openrpa"
    ensure_zip_runtime(lock["openrpa_runtime"], openrpa_dir, cache,
                       strip_prefix=None, marker=openrpa_dir / "LocalOpenRpaBridge.exe")

    from smoke_test import main as smoke

    smoke()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
