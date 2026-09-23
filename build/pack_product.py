"""Package source and installation metadata without user projects or secrets."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def pack(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for directory in ('app', 'build', 'tests', 'docs'):
            if not (root / directory).is_dir():
                continue
            for file in sorted((root / directory).rglob('*')):
                if not file.is_file() or file.is_symlink():
                    continue
                rel = file.relative_to(root)
                if any(part == '__pycache__' or part.startswith('ui-test-') for part in rel.parts):
                    continue
                if file.suffix not in {'.cs', '.py', '.js', '.cjs', '.css', '.html', '.bat', '.json', '.yaml', '.yml', '.sql', '.md', '.txt'}:
                    continue
                if file.name.endswith('.local.json') or file.name.startswith('ui-n8n-state'):
                    continue
                if rel.as_posix() == 'app/config/custom_api.json':
                    # The release must never contain local gateway keys or custom auth headers.
                    template = {'enabled': False, 'displayName': '公司閘道', 'requestUrl': '',
                                'apiKeyEncrypted': '', 'headers': {}, 'defaults': {'model': ''},
                                'timeoutSeconds': 240, 'tls': {'verify': True}}
                    archive.writestr(rel.as_posix(), json.dumps(template, ensure_ascii=False, indent=2))
                else:
                    archive.write(file, rel.as_posix())
        knowledge = root / 'filesystem/system/knowledge'
        if knowledge.is_dir():
            for file in sorted(knowledge.rglob('*')):
                if file.is_file() and file.suffix in {'.sql', '.md'} and file.name != 'dependencies.sqlite':
                    archive.write(file, file.relative_to(root).as_posix())
        for name in ('一鍵安裝.bat', '點此開始.bat', 'build.lock.json', 'RELEASE_GATE.md', '使用說明.txt', 'IMPROVEMENT_PLAN.md', 'README.md', 'VERSION'):
            if (root / name).is_file():
                archive.write(root / name, name)
        manifest = root / 'filesystem/system/manifests.json'
        if manifest.is_file():
            archive.write(manifest, 'filesystem/system/manifests.json')
        archive.writestr('filesystem/projects/.gitkeep', '')


if __name__ == '__main__':
    output = ROOT / 'vendor/portable-agent-body.zip'
    pack(ROOT, output)
    print(f'Packed {output} ({output.stat().st_size} bytes)')
