# 工具完善與驗證紀錄

更新日期：2026-09-09。保留可攜雙 Python、Pydantic AI、專案隔離與 n8n 人工批准架構。

## 已實作

- [x] 回合復原先驗證全部目標與備份，拒絕覆蓋後續修改，禁止重複復原；與 Agent 共用專案鎖。
- [x] 原子寫入使用唯一暫存檔，不覆蓋使用者同名 .tmp；快照路徑正規化，拒絕穿越與 ADS。
- [x] 各分頁由 session header 綁定專案；重開與重新整理恢復歷史、待批准項目及可復原回合；升級前對話也傳入模型上下文。
- [x] SQLite 共用連線加鎖；取消與工具結束後才釋放專案鎖。
- [x] 真實工具進度、SSE keepalive、取消與錯誤紀錄；無金鑰時不假装 AI 已完成工作。
- [x] 儲存 Pydantic AI 工具歷史與伺服器批准結果；批准後續跑不重複發佈。
- [x] 批准綁定 session 與流程內容雜湊，其他 session 或已修改流程不能沿用批准。
- [x] Python 取消、非零退出與逾時不提交 staging；修正 Windows Job Object 控制代碼型別與 CPU 時間欄位。
- [x] 閘道可設定名稱、URL、模型、金鑰；提供 n8n API Key 設定。
- [x] 匯入、檔案搜尋、文字／二進位辨識、下載與含實際檔案的 ZIP 匯出，所有入口使用 Jail。
- [x] 桌面與手機介面、空白狀態、忙碌狀態、中文輸入法、鍵盤焦點與持續錯誤回饋。
- [x] n8n 子路徑資產、登入 cookies、WebSocket 來源及關閉流程；非阻塞啟動控制、readiness 與啟動日誌。
- [x] n8n 發佈 API 移除唯讀 active 與空值欄位；保留 CREATE／UPDATE／去重／遠端衝突保護。
- [x] 發行打包排除使用者專案、runtime、測試資料與閘道金鑰；更新使用說明。
- [x] 一般／計畫／唯讀模式由後端強制；切換會使待批准失效，不刪除對話歷史。
- [x] 本機 SearXNG MCP；AI 不可指定任意上游。
- [x] OpenRPA 離線解壓 runtime、本機 Broker :8771、預載 n8n Local OpenRPA 節點；一次寫入整合部署包，批准後才開放執行且不自動啟用。
- [x] 依賴知識庫唯讀 reader 與 inspect_automation_environment；空庫據實降級，不編造內容。

## 驗證證據

- `portable_python/python.exe -m unittest discover -s tests`：128 項，127 通過，1 項 symlink 權限跳過。
- `build/smoke_test.py`：SMOKE OK。
- Node `--check app/frontend/app.js`：通過。
- `tests/ui_smoke.cjs`：實際 Edge 無頭瀏覽器通過新增、匯入、預覽、搜尋、歷史恢复、復原、設定與 390px 寬度排版。
- `tests/n8n_ui_smoke.cjs`：真實 n8n 2.34.6 首次帳號初始化、重新登入、編輯器、深層連結重新整理與 WebSocket；無非預期載入錯誤。
- `tests/n8n_publish_smoke.py`：真實 n8n CREATE、UPDATE 同一 ID、未啟用狀態、重複去重與遠端衝突保護。
- `tests/test_model_runtime.py`：真正的 Pydantic AI FunctionModel 驗證 canonical history 與延期工具結果，禁止實際模型連網。
- `tests/test_pack_product.py`：發行資產不包含測試秘密、專案或 runtime。

## 驗證邊界

- 真實 n8n 測試使用 tests/ui-test-* 隔離資料，不使用企業專案或正式憑證。
- 未對公司真實模型閘道發送請求；實際模型名稱、網址、金鑰及公司網路政策需在部署環境設定。
- Job Object 與 staging 不等於 OS 檔案沙箱。若要求惡意 Python 也無法存取宿主檔案，仍需 AppContainer／其他 OS 隔離。
- 自動審查曾拒絕遞迴刪除修正；已採較安全方案，delete_file 僅接受逐檔刪除，不增加整個資料夾刪除能力。
- 知識庫內容不在本產品建置範圍；未匯入 `dependencies.sqlite` 時檢索工具回報不可用。
- OpenRPA 桌面執行需獨立 Windows 環境驗證；若已有使用者 OpenRPA profile，產品會拒絕啟動以免覆寫。

最新整合、取消限制、可攜封裝與介面驗證見 [2026-09-09 驗證紀錄](docs/VERIFICATION_2026-09-09.md)。
