# 企業本機 AI Agent — 發行閘門

每個發行版必須通過本清單。CI 設 `ALLOW_MODEL_REQUESTS=False`，不得打公司閘道。

## Security

- [ ] FilesystemJail 拒絕：`C:\` 絕對路徑、UNC、`\\?\`、`..`、兄弟專案、`projects/` 根目錄、`.runtime/`、`system/` 寫入、`.env` / `*.pem` / `custom_api.json`
- [ ] `run_python` 不以真實專案為 cwd。腳本若直接改真實專案 tree hash → `VIOLATION`、不 commit（見 `tests/test_staging_violation.py`）
- [ ] 寫回真實專案一律 snapshot → atomic replace → jail → audit
- [ ] HITL 只接受 `{approval_id, approve|deny}`。拒絕 client `message_history` / `args` / `deferred_tool_results`
- [ ] Agent 沒有通用 shell、沒有 `create_project`、沒有 pip/npm
- [ ] 閘道範本**不可**把 `"tools": []` 寫死（見 `app/config/custom_api.json`）

## Execution

- [ ] 產品 Python **3.11.9**（`portable_python\`）只跑 Uvicorn + Pydantic AI
- [ ] Agent Python **3.14.7**（`filesystem/system/python\`）只給 `run_python`
- [ ] Job Object：kill-on-close、記憶體／CPU／行程數；timeout 殺樹
- [ ] UsageLimits：request 20 / tool 50 / tokens 200000
- [ ] 讀類工具可平行；write / edit / delete / run_python / write_workflow_json / publish sequential
- [ ] `run_python` 與 `publish_workflow` `max_retries=0`
- [ ] TestModel + FunctionModel（或同等 `dispatch_tool` 對抗測試）通過

## Recovery

- [ ] 檔案工具與 staging commit 共用回合 snapshot
- [ ] UI「復原本回合變更」可還原 `run_python` 產生的 Excel／PNG／CSV／程式碼
- [ ] 中止不自動 rollback
- [ ] 狀態在 `.runtime/state.db`；`audit.jsonl` 只追加

## n8n

- [ ] `/n8n/` reverse proxy 支援 HTTP + WebSocket + SSE（`tests/integration/test_n8n_proxy.py`）
- [ ] iframe 同源；n8n 只綁 127.0.0.1；`frame-ancestors` 僅本機 origin
- [ ] 首次生命週期：encryption key → health → owner → API key。失敗 degraded，Agent 其餘功能仍可用
- [ ] `publish_workflow`：尚無 id → CREATE；遠端未改 → UPDATE；遠端手改 → CONFLICT 不覆蓋
- [ ] 不自動 Activate；Agent 不准建 credential
- [ ] 公司電腦**不** `npm install` / `npx`

## Corporate PC

- [ ] `build\install_runtime.bat` 為純 cmd：`curl` + `certutil` + `tar`；**無** PowerShell / pwsh / pip / npm / get-pip
- [ ] 在目標電腦各跑一次：`portable_python\python.exe`、`filesystem\system\python\python.exe`、`filesystem\system\node\node.exe`
- [ ] 工作區放使用者可寫位置（不要 Program Files）
- [ ] 安裝腳本需能連 python.org、pypi、nodejs.org、GitHub Release（本體 + n8n 第二資產）

## Packaging

- [ ] GitHub Release **本體 zip** 不含 `portable_python/`、`vendor/`、`system/python|node|n8n`、`.runtime`
- [ ] 同一 Release **第二資產** `n8n-runtime-<ver>-win-x64.zip` 有整包 sha256，且 < 2 GiB
- [ ] 公開 Release 不得附上仍含 n8n `.ee.` 檔的 runtime zip。Sustainable Use License 不涵蓋這些 Enterprise 檔；內部安裝仍用建置機 `vendor/` 的鎖定 ZIP
- [ ] `build.lock.json` 每筆 runtime 有 version + url + sha256；`wheels[]` 以 `build\pin_wheels.py` 凍結後再發行
- [ ] wheel 走 `wheel_installer.py`（dist-info / `.data` / RECORD），不是只 `zipfile -e`

## Agent tests

```bat
set ALLOW_MODEL_REQUESTS=False
portable_python\python.exe -m unittest discover -s tests -v
```

## 最近一次本機驗證

2026-09-09 的實測範圍與未驗證項目見 [整合驗證紀錄](docs/VERIFICATION_2026-09-09.md)。上方清單保留為每次發行的檢查模板，不代表公司接口及部署環境已驗證。
