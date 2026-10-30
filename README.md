# trajis-ai-agent-enterprise

[繁體中文說明](README.zh-TW.md)

Enterprise local AI Agent **0.0.1**. It runs on Windows with a portable Python, keeps project files on the local machine, and requires human approval before publishing n8n and OpenRPA integration packages.

## What is in this release

- Three conversation modes, enforced by the server: normal, plan and read-only.
- Project files, per-turn rollback, Python staging and a Windows Job Object. The Job Object is not an operating-system file sandbox.
- A local n8n, a custom OpenRPA Broker (`127.0.0.1:8771`; this is not the official OpenRPA REST API) and a SearXNG MCP.
- Read-only retrieval from a dependency knowledge base. The database is at `filesystem/system/knowledge/dependencies.sqlite`.

The company model gateway, real desktop workflows and the user's SearXNG service must be configured separately in the deployment environment. This repository contains no API keys.

## Download and install

Download only `trajis-ai-agent-enterprise-0.0.1.zip` from the [0.0.1 release](https://github.com/trajis-tech/trajis-ai-agent-enterprise/releases/tag/v0.0.1). Extract it to a folder the user can write to, then double-click `一鍵安裝.bat` (the file name means "One-Click Install").

That archive already contains the product code and the pinned OpenRPA and n8n archives. The script fetches Python, Node and wheels with Windows `curl`, verifies their SHA-256 hashes, installs them, and then opens `http://127.0.0.1:8765`. You do not need to download any other release asset, and you should not run PowerShell, pip or npm yourself. The target machine needs .NET Framework 4.6.2 or later. The n8n archive contains upstream `.ee.` files, and their license restricts public redistribution.

For operating details, see `使用說明.txt` (the file name means "User Guide"; its contents are in Traditional Chinese).

## Development and testing

The Git tree does not contain `portable_python/`, `vendor/`, `filesystem/system/python|node|n8n|openrpa/` or `filesystem/.runtime/`.

```bat
set ALLOW_MODEL_REQUESTS=False
portable_python\python.exe -m unittest discover -s tests -v
```

GitHub Actions uses Python 3.11 and installs only the pinned packages that the tests import (`build/ci_install_test_deps.py`). Company machines still go through `build\install_runtime.bat`; pip and npm are not run on site.

To build the package:

```bat
build\pack_product.bat
```

## License

The product code in this repository is provided as-is and does not come with a separate product license. Third-party runtimes keep their own licenses: n8n is under the Sustainable Use License (excluding the `.ee.` Enterprise files), OpenRPA tag 1.4.57.13 is under MPL-2.0, and CPython is under PSF-2.0.
