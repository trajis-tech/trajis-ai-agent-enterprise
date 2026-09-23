# trajis-ai-agent-enterprise

企業本機 AI Agent **0.0.1**。在 Windows 上以可攜 Python 執行，專案檔留在本機；發佈 n8n 與 OpenRPA 整合包需要人工批准。

## 這個版本包含什麼

- 一般、計畫、唯讀三種對話模式，由伺服器強制。
- 專案檔案、回合復原、Python staging 與 Windows Job Object。Job Object 不是作業系統檔案沙箱。
- 本機 n8n、自製 OpenRPA Broker（`127.0.0.1:8771`，不是 OpenRPA 官方 REST）與 SearXNG MCP。
- 依賴知識庫唯讀檢索。資料庫在 `filesystem/system/knowledge/dependencies.sqlite`。

公司模型閘道、真實桌面流程與使用者的 SearXNG 服務需要在部署環境另行設定。本儲存庫不包含 API 金鑰。

## 取得與安裝

只下載 [0.0.1 Release](https://github.com/trajis-tech/trajis-ai-agent-enterprise/releases/tag/v0.0.1) 的 `trajis-ai-agent-enterprise-0.0.1.zip`。解壓到使用者可寫資料夾，雙擊 `一鍵安裝.bat`。

這個檔已包含產品程式、OpenRPA 與 n8n 的鎖定壓縮檔。腳本會用 Windows `curl` 取得 Python、Node 與 wheel，核對 SHA-256 後安裝，接著開啟 `http://127.0.0.1:8765`。不需要另下載其他 Release 附件，也不要執行 PowerShell、pip 或 npm。目標電腦需有 .NET Framework 4.6.2 或更新版本。n8n 壓縮檔含上游 `.ee.` 檔，公開再散布受其授權限制。

操作細節見 `使用說明.txt`。

## 開發與測試

Git 樹不含 `portable_python/`、`vendor/`、`filesystem/system/python|node|n8n|openrpa/` 與 `filesystem/.runtime/`。

```bat
set ALLOW_MODEL_REQUESTS=False
portable_python\python.exe -m unittest discover -s tests -v
```

GitHub Actions 使用 Python 3.11，並只安裝測試會匯入的鎖定套件（`build/ci_install_test_deps.py`）。公司電腦仍走 `build\install_runtime.bat`，不在現場執行 pip 或 npm。

打包本體：

```bat
build\pack_product.bat
```

## 授權

本儲存庫的產品程式依儲存庫現況提供，未另附獨立產品授權條款。第三方 runtime 維持各自授權：n8n 為 Sustainable Use License（不含 `.ee.` Enterprise 檔）、OpenRPA tag 1.4.57.13 為 MPL-2.0、CPython 為 PSF-2.0。
