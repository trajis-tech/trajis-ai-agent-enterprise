# 知識庫缺口（禁止把下列項目當成已證實）

## 官方頁 404 或抓取失敗（仍有效）
- 舊路徑 `https://docs.n8n.io/integrations/creating-nodes/...`、`/api/api-reference` 回 404。
- `https://www.python.org/license/` 404。
- `https://www.uvicorn.org/` HTTP 500、Starlette 官網逾時；**改以鎖定 wheel 原始碼/METADATA 為準**，不以網站記憶補 API。
- SearXNG GitHub LICENSE 仍未取到；SearXNG SPDX 維持 unknown。
- Node GitHub LICENSE URL 曾逾時；**已改讀官方 dist zip 內 `filesystem/system/node/LICENSE`**。

## 2026-09-08 實測已補（見 probes/runtime_probe.json）
- n8n 2.34.6 內建 openapi.yml **含** POST `/workflows/{id}/publish`；activate 為 deprecated。
- n8n 2.34.6 `engines.node` 為 `>=22.22`；鎖定 `node.exe --version` = v22.23.2。
- n8n 2.34.6 `N8N_CUSTOM_EXTENSIONS` 在 n8n-core + loader 中存在。
- OpenRPA.exe.config sku=.NET 4.6.2；本機 NDP Release=533509。**未啟動 OpenRPA GUI**。
- OpenRPA.exe 含 ASCII `WorkingDir`；官方 CLI 頁仍未記載 `/workingdir`。**未實跑隔離 profile**。
- uvicorn 0.35.0 / starlette 0.47.2 / httpx 0.28.1 從安裝套件讀取。
- 單元測試 test_automation、test_search_mcp、test_chat_modes、test_knowledge、test_agent_tools 於 embeddable Python 下通過（28 項）。

## 仍未證明
- 未啟動 n8n 行程，因此沒有對 live POST /api/v1/workflows 的 HTTP 狀態碼實測（僅 OpenAPI + 產品單元測試假 client）。
- 未啟動 OpenRPA 桌面：`/workingdir` 是否真的改 profile、CLI 退出是否等於完成、取消是否完整，仍不足。
- 解壓 MSI ≠ 官方安裝器保證的完整功能。
- unicode61 **不做** 中文斷詞。
- Python staging / Job Object / localhost **不是** OS 沙箱。
- `:8772` HTTP MCP 仍為 project_proposed。
- n8n 雲端「免費試用無 Public API」敘述未核對本機 2.34.6。
- credentials 完整 schema 未整份擷取。OpenAPI 對 publish 的 409 已在 2.34.6 yml 見到；產品衝突偵測仍用 updatedAt/versionId。
- SearXNG 官方 Search API 頁未定義 429；產品 adapter 對 429 的處理是專案實作。單元測試 stub 回 200，**未打到 403/429 分支**。
- 本機 .NET Release 不能推廣到未檢查的公司電腦。
- Node LICENSE 檔內其他捆绑元件各自授權，不全部是 MIT。
- Pydantic AI 網站可能新於 2.31.0；仍以安裝套件為準。
- build.lock.json 其餘套件多數仍只有 inventory、沒有 API 摘要。
