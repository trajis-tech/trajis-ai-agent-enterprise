"""Build-machine only: package extracted official runtime + compiled local bridge.

Run extract_openrpa.py first; this never executes an MSI or modifies profiles.
The target computer only verifies and extracts this archive.
"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'vendor/openrpa-extracted'
    bridge = ROOT / 'filesystem/system/openrpa'
    output = ROOT / 'vendor/openrpa-runtime-1.4.57.13-win-x64.zip'
    required = ['OpenRPA.exe', 'OpenRPA.Interfaces.dll']
    for name in required:
        if not (source / name).is_file():
            raise SystemExit('Extract the pinned official MSI first: ' + name)
    helpers = ['LocalOpenRpaBridge.exe', 'LocalOpenRpaBridge.exe.config']
    for name in helpers:
        if not (bridge / name).is_file():
            raise SystemExit('Compile build/OpenRpaIpcBridge.cs first: ' + name)
    files = {p.relative_to(source).as_posix(): p for p in source.rglob('*')
             if p.is_file() and not p.is_symlink()
             and '_cabinet' not in p.relative_to(source).parts
             and p.name not in helpers
             and p.name.lower() not in {'settings.json', 'openrpa.log'}
             and p.suffix.lower() not in {'.log', '.pdb'}}
    files.update({name: bridge / name for name in helpers})
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    lock_path = ROOT / 'build.lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    lock['openrpa_runtime'] = {
        'version': '1.4.57.13', 'bridge_version': '1.0.1',
        'url': 'vendor/' + output.name, 'filename': output.name, 'sha256': digest,
        'source_url': 'https://github.com/open-rpa/openrpa/releases/download/1.4.57.13/OpenRPA.msi',
        'source_sha256': '96ddcc22bfaca8fe3c080eba0e914c961e0921c5c3cfe48ef3d736092b208bec',
        'note': 'Build machine extracts MSI and compiles C# bridge. Target extracts verified ZIP; requires Windows .NET Framework 4.6.2 or later.'}
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Packed', len(files), 'files;', output.stat().st_size, 'bytes;', digest)


if __name__ == '__main__':
    main()
