# 2026-09-09 整合完善與驗證

本次延續其他 Agent 的成果，保留其知識庫內容；修正執行邊界、回復流程、檢索與介面。

## 已完成

- 一般／計畫／唯讀模式由伺服器檢查；切換模式撤銷待批准，保留原始對話及工具歷史。唯讀與計畫模式的匯入、復原按鈕同步停用。
- 窄螢幕仍能開啟搜尋設定與自動化執行記錄，避免重要入口跟著側欄消失。
- n8n 啟動逾時後若服務稍後就緒，介面會恢復；停用 MCP registry 與社群套件背景模組。OpenRPA 離線設定停用分析回報與更新檢查。
- n8n 的 Local OpenRPA 節點以 execution/node/runIndex/item 識別操作：同一輪重試去重，不同迴圈可再次執行。
- OpenRPA IPC 使用 UTF-8；狀態不明時持久保存暫停標記，後續排隊工作不得繼續執行。服務重啟不重播桌面操作。
- 「停止執行器並解除暫停」只停止本工具擁有的 OpenRPA；外部執行器仍存在時拒絕解除。解除後不重跑歷史工作。
- 知識库精確版本比對依來源文件的 doc_version，並在候選截斷前篩選；已安裝版本不能冒充文件驗證版本。詳細文件可讀取本文，文件與配方回應限制 20,000 字元。
- OpenRPA 1.4.57.13、UTF-8 IPC helper 與設定進入獨立可攜 ZIP，SHA-256 寫入 build.lock.json；安裝器直接驗證及解壓，不執行 MSI。原始 C# 納入產品原始碼封裝。

## 驗證證據

- Python unittest：128 項，127 通過、1 項因 Windows symlink 權限跳過。
- build/smoke_test.py：SMOKE OK，檢查雙 Python、Node、n8n、OpenRPA 與 Agent 建構。
- tests/openrpa_node_smoke.cjs：本機 HTTP 認證、同輪重試去重、不同迴圈執行通過。
- tests/ui_smoke.cjs：新增專案、匯入、預覽、搜尋、重開歷史、復原、設定、390px 畫面、模式切換與保存、搜尋設定入口通過。
- tests/n8n_ui_smoke.cjs：真實 n8n 初始設定、登入、編輯器、深層連結及 WebSocket 通過。
- tests/automation_live_smoke.py：真實 n8n 預載 CUSTOM.localOpenRpa → 127.0.0.1 Broker → 離線 OpenRPA XAML → 中文結果回傳通過；流程部署後維持 inactive，測試另行手動觸發。
- 真實取消等待流程：觀察到上游未回傳取消完成確認。系統正確標示 unknown 並暫停；明確復原後本工具的執行器已停止，且不重跑。

所有實際整合測試使用 tests/ui-test-*、8766／5688／8871，未使用正式專案或公司 AI 接口。

## 使用與封裝

本機平常由「點此開始.bat」啟動。設定公司 AI 接口及 SearXNG 上游後，AI 可使用本機工具。SearXNG 必須開放 JSON 搜尋格式；本次測試使用本機模擬上游與真實 stdio MCP，尚未驗證使用者的實際搜尋服務。

OpenRPA 的桌面操作以登入中的 Windows 使用者權限執行，並非作業系統沙箱。取消要求不代表已回滾桌面副作用；狀態不明時應先查看桌面，再使用解除暫停按鈕。

建置機先以 build/extract_openrpa.py 解出鎖定 MSI，使用 .NET Framework C# compiler 編譯 build/OpenRpaIpcBridge.cs，引用 OpenRPA.Interfaces.dll 與 Newtonsoft.Json.dll，輸出 filesystem/system/openrpa/LocalOpenRpaBridge.exe，並複製 OpenRPA.exe.config 為 LocalOpenRpaBridge.exe.config。再執行：

```
portable_python\python.exe build\pack_openrpa_runtime.py
portable_python\python.exe build\pack_product.py
```

交付時需要產品 body ZIP、build.lock.json 所列各 runtime ZIP、wheel 快取與啟動器，不能只複製 body ZIP。OpenRPA ZIP 位於 vendor/openrpa-runtime-1.4.57.13-win-x64.zip；目標 Windows 需有 .NET Framework 4.6.2 或更新版本。目標電腦不需 pip/npm、C# 編譯或 MSI 安裝。

知識庫內容由另一 Agent 建立，本次未重建其資料。既有 dependencies.sqlite 可沿用；產品 body ZIP 排除資料庫內容，額外部署至 filesystem/system/knowledge/dependencies.sqlite。建立或更新資料內容的 Prompt 仍見 DEPENDENCY_KNOWLEDGE_DB_PROMPT.md。LOCAL_AUTOMATION_ARCHITECTURE.md 包含後續設計，不能視為每項均已實作。

## 手動下載與純 CMD 部署補完

- build/install_runtime.bat 提供離線、線上與手動下載頁選單；可直接傳 --offline 或 --online。無 PowerShell、系統 Python、pip/npm 依賴。
- docs/MANUAL_DOWNLOADS.html 由版本鎖定產生 94 個必要檔案的下載網址、路徑與 SHA-256；離線模式預先核對完整清單，缺少或損壞時不進行 runtime 安裝，也不退回線上下載。初始可攜 Python 的解壓屬於啟動此檢查的必要步驟。
- n8n/OpenRPA 的封裝 ZIP 隨發行版提供；手動頁不編造公開下載網址。
- build/deployment_assets.py 不帶參數可離線核對全部資產；--download 可在有網路且已有可攜 Python 的建置機準備官方下載資產，不會安裝或啟動服務；--write-guide 重新產生清單。
- tests/test_deployment.py 驗證完整清單、無網路缺檔報告、離線下載禁止、真實 CMD 缺檔與錯誤 SHA（含空白和驚嘆號路徑）。
