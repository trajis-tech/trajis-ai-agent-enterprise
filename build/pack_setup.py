"""Build the single release archive. The user downloads this one file."""
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_product import pack

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ZIPS = (
    "vendor/openrpa-runtime-1.4.57.13-win-x64.zip",
    "vendor/n8n-runtime-2.34.6-win-x64.zip",
)


def pack_setup(root: Path, output: Path) -> None:
    pack(root, output)
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_STORED) as archive:
        sqlite = root / "filesystem/system/knowledge/dependencies.sqlite"
        if sqlite.is_file():
            archive.write(sqlite, "filesystem/system/knowledge/dependencies.sqlite")
        missing = [rel for rel in RUNTIME_ZIPS if not (root / rel).is_file()]
        if missing:
            raise SystemExit("setup archive is missing:\n" + "\n".join(missing))
        for rel in RUNTIME_ZIPS:
            archive.write(root / rel, rel)


if __name__ == "__main__":
    output = ROOT / "vendor" / "trajis-ai-agent-enterprise-0.0.1.zip"
    pack_setup(ROOT, output)
    print(f"Packed {output} ({output.stat().st_size} bytes)")
