"""Lock-derived download inventory, offline validation and manual download page."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import os
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def inventory(lock):
    rows = []
    for key in ('product_python', 'agent_python', 'node', 'n8n_runtime', 'openrpa_runtime'):
        item = lock[key]
        folder = 'vendor' if key.endswith('_runtime') else 'vendor/wheels'
        rows.append(dict(item, path=folder + '/' + item['filename'], component=key))
    for item in lock['wheels']:
        rows.append(dict(item, path='vendor/wheels/' + item['role'] + '/' + item['filename'], component=item['name']))
    return rows


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def problems(root, rows):
    result = []
    for item in rows:
        path = root / item['path']
        if not path.is_file():
            result.append('MISSING: ' + item['path'])
        elif digest(path).lower() != item['sha256'].lower():
            result.append('HASH MISMATCH: ' + item['path'])
    return result


def require_offline_assets(root, lock):
    errors = problems(root, inventory(lock))
    if errors:
        raise SystemExit('Offline installation stopped before modifying runtimes.\n' + '\n'.join(errors)
                         + '\nSee docs/MANUAL_DOWNLOADS.html; no network was used.')


def manual_page(root, rows):
    e = html.escape
    body = []
    for item in rows:
        url = item['url']
        source = ('<a href="' + e(url, quote=True) + '">官方下載</a>') if url.startswith('https://') else '請由產品發行者提供此預先封裝 ZIP（不可用原始 MSI／npm 套件替代）'
        body.append('<tr><td>' + e(item['component']) + '</td><td><code>' + e(item['path'])
                    + '</code></td><td>' + source + '</td><td><code>' + e(item['sha256']) + '</code></td></tr>')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>手動下載與離線安裝</title><style>body{font:16px system-ui;margin:32px;line-height:1.6;color:#243047}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd4df;padding:10px;text-align:left;vertical-align:top}code{overflow-wrap:anywhere}a{color:#2059a6}h1{font-size:26px}.table{overflow:auto}</style>
<h1>手動下載與離線安裝</h1><p>這份清單由 build.lock.json 產生；不會自動連線或執行下載。可在另一台能上網的電腦下載，再依下列相對路徑放入產品資料夾。</p>
<ol><li>先解壓產品 portable-agent-body.zip。</li><li>下載全部列出的檔案；n8n 與 OpenRPA 是產品發行者提供的預先封裝 ZIP，並無公開下載網址，請使用隨產品提供的 vendor 檔案。</li><li>在 CMD 執行 <code>build\\install_runtime.bat --offline</code>。安裝會先核對完整清單的 SHA-256；缺檔或不符時停止，不會退回線上下載。</li><li>安裝完成後執行「點此開始.bat」。公司 AI 接口及 SearXNG 網址在介面另行設定。</li></ol>
<p>線上 CMD 模式：<code>build\\install_runtime.bat --online</code>。無 PowerShell、pip、npm 或 MSI 安裝；CMD 以 Windows curl／certutil／tar 啟動可攜 Python，再由產品內的標準函式庫安裝依賴。Windows 需具備 .NET Framework 4.6.2 或更新版本；桌面自動化需要互動式 Windows 工作階段。</p>
<p>手動核對範例：<code>certutil -hashfile "vendor\\openrpa-runtime-1.4.57.13-win-x64.zip" SHA256</code>。另外提供的知識庫可放在 <code>filesystem\\system\\knowledge\\dependencies.sqlite</code>；它不屬於必要 runtime 清單。</p>
<div class="table"><table><thead><tr><th>元件</th><th>放置路徑</th><th>來源</th><th>SHA-256</th></tr></thead><tbody>'''
    page += '\n'.join(body) + '</tbody></table></div></html>'
    target = root / 'docs/MANUAL_DOWNLOADS.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding='utf-8')


def download_assets(root, rows):
    errors = []
    for item in rows:
        path = root / item['path']
        if path.is_file() and digest(path).lower() == item['sha256'].lower():
            continue
        if not item['url'].startswith('https://'):
            errors.append('Provide release bundle manually: ' + item['path'])
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.download')
        try:
            print('Downloading ' + item['filename'], flush=True)
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'PortableAgentInstaller/1.0'})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if digest(temporary).lower() != item['sha256'].lower():
                raise ValueError('SHA-256 mismatch')
            os.replace(temporary, path)
        except Exception as exc:
            errors.append(item['path'] + ': ' + str(exc))
        finally:
            temporary.unlink(missing_ok=True)
    if errors:
        raise SystemExit('\n'.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Download missing official assets; no installation')
    parser.add_argument('--write-guide', action='store_true', help='Generate manual HTML without network')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'build.lock.json').read_text(encoding='utf-8'))
    rows = inventory(lock)
    if args.write_guide:
        manual_page(ROOT, rows)
        print('Manual download guide written:', len(rows), 'assets')
        return
    if args.download:
        download_assets(ROOT, rows)
    require_offline_assets(ROOT, lock)
    print('OFFLINE ASSETS OK:', len(rows), 'verified files')


if __name__ == '__main__':
    main()
