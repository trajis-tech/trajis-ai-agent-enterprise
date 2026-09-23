# 交給建庫 AI 的完整 Prompt

請將下方「Prompt 開始」至「Prompt 結束」交給另一個 AI，並提供專案的 `build.lock.json`、`filesystem/system/manifests.json`（若存在）及 `docs/LOCAL_AUTOMATION_ARCHITECTURE.md`。不需要提供 `.runtime`、API key、私人工作流程或公司資料。

---

## Prompt 開始

你是 Windows 本機 AI 自動化工具的依賴知識庫建置工程師。請建立真正可交付、可唯讀檢索的 SQLite 依賴文件知識庫，不是只有設計或幾筆示例。使用繁體中文解釋，保留原始 API、參數、錯誤與程式碼識別字。

### 任務邊界

只建立依賴文件知識庫、建置/驗證程式、來源 manifest 及報告。不修改產品程式、不替使用者設定 API、不部署 n8n/OpenRPA、不執行文件中的 shell 命令或自動化、不讀取 `.runtime` 或秘密檔、不收集私人專案內容。

在獨立輸出目錄交付；由產品匯入流程放入 `filesystem/system/knowledge/dependencies.sqlite`。禁止直接覆寫產品正在使用的 DB。建置階段可查詢官方網路來源，成品查詢必須離線運作，不依賴網路、embedding API、外部向量 DB 或下載模型。

### 先讀輸入、鎖定版本

讀取提供的 `build.lock.json` 與 installed manifests，以實際檔案為準，不自行升版。整理 component inventory，包括但不限於：產品 Python、Agent Python、Node.js、n8n、Pydantic AI / Pydantic、Starlette / Uvicorn / httpx、SQLite / FTS5、OpenRPA、OpenRPA adapter、私有 n8n node、MCP SDK、SearXNG Search API。展開實际列出的 Python 套件，不只寫上面名稱。

未提供或尚未鎖定的版本設為 unknown；新增 OpenRPA / adapter / MCP SDK 若尚未實作，不假造版本、API 或相容性。區分 `official_implemented`、`project_implemented`、`project_proposed`、`unverified`。設計規格只屬 project_proposed，不能改寫成官方能力。

特別注意：OpenRPA 離線模式 / CLI 啟動有官方說明，但本產品設計的 `127.0.0.1:8771/v1` 是自製 Broker，不是 OpenRPA 官方 REST API。CLI 程序退出不一定代表 workflow 完成。n8n 的預載 Local OpenRPA 是本產品私有節點設計，不可標成已證實的官方節點。

### 資料來源與內容

優先順序：指定版本的官方 tag/source、官方版本文件、官方當前文件、專案提供的已驗證程式/契約。官方論壇只作維護者解釋的補充，注明身份、時間與驗證狀態。搜尋結果摘要、第三方教學與其他 AI 的回答不得作唯一證據。

起始來源如下；先確認仍可存取，再依真實版本擴展，不假造 URL：

- https://docs.openiap.io/docs/openrpa/Offline.html
- https://docs.openiap.io/docs/openrpa/CommandLine.html
- https://docs.openiap.io/docs/openrpa/OpenRPA-Installer.html
- https://docs.openiap.io/docs/openrpa/Plugin-Model.html
- https://github.com/open-rpa/openrpa
- https://github.com/n8n-io/n8n
- https://docs.n8n.io/
- https://docs.searxng.org/dev/search_api.html
- https://modelcontextprotocol.io/specification/
- https://ai.pydantic.dev/
- https://docs.python.org/
- https://www.sqlite.org/fts5.html

每個核心元件至少涵蓋用途/限制、版本前提、Windows 執行需求、安裝打包、設定、核心 API、常見任務、輸入輸出、錯誤診斷、秘密/網路/副作用、離線能力及相容性。對未能證實的資訊明確寫 gaps，不能為了填滿內容而推測。

為這些問題提供可追溯 recipe：

1. 如何在不連 OpenIAP 雲端下啟動 OpenRPA？設定變更何時生效？
2. 如何以 CLI 啟動既有 OpenRPA workflow？哪些輸出/取消能力尚待 adapter 驗證？
3. n8n 私有節點如何以鎖定版本離線預包、載入與驗證？
4. n8n workflow create/update 的 writable fields、credentials reference、inactive 部署與版本衝突處理。
5. SearXNG `/search` JSON API、403/429/timeout、language/time_range、結果格式。
6. MCP stdio 初始化、tools/list、tools/call、stderr、取消及生命週期；HTTP 選配的 Origin/認證要求。
7. Pydantic AI tool filtering、DeferredToolRequests / DeferredToolResults 與中斷恢復的版本證據。
8. SQLite 唯讀開啟、FTS5、中文搜尋、版本过滤及不執行檢索內容的措施。
9. 一般/計畫/唯讀的產品契約；只能引用提供的架構文件，標記 proposed 或 implemented。
10. 離線打包、路徑隔離與 Windows 桌面權限的限制，不把 Python staging 或 loopback 當 OS sandbox。

原始文件若不允許整篇再散布，保存原創摘要、必要的短引文、來源 URL 與授權註記；不得為方便把有版權的完整網站鏡像塞入可分發 DB。程式片段保留適用授權。每個 source 有 redistribution decision；缺少授權證據標記 unknown 並限制保存內容。

### Schema v1 契約

產出 schema.sql，使用 SQLite foreign keys 和合理 UNIQUE/CHECK 約束。ID 使用穩定字串（FTS 對應 chunks.id 為 INTEGER PRIMARY KEY）。UTC timestamp 一律 ISO-8601。JSON 欄位存合法 JSON 字串。最低欄位如下，可增欄但不可悄悄改語意：

```text
kb_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
  必含 schema_version=1、corpus_version、built_at、builder_version、
  input_lock_sha256、sqlite_version、inventory_sha256、tokenizer_strategy

components(
  id TEXT PRIMARY KEY, name TEXT, version TEXT, version_status TEXT,
  kind TEXT, platform TEXT, upstream_url TEXT, license_spdx TEXT,
  implementation_status TEXT
)

sources(
  id TEXT PRIMARY KEY, component_id TEXT FK, url TEXT, title TEXT,
  source_kind TEXT, doc_version TEXT, git_ref TEXT, retrieved_at TEXT,
  content_sha256 TEXT, language TEXT, license_text TEXT,
  redistribution TEXT, verification_status TEXT
)

chunks(
  id INTEGER PRIMARY KEY, stable_key TEXT UNIQUE, source_id TEXT FK,
  section_anchor TEXT, heading TEXT, body TEXT, summary_zh_tw TEXT,
  keywords TEXT, applicability_json TEXT, implementation_status TEXT,
  confidence TEXT, content_sha256 TEXT
)

recipes(
  id TEXT PRIMARY KEY, component_id TEXT FK, title TEXT, goal TEXT,
  prerequisites_json TEXT, steps_json TEXT, input_schema_json TEXT,
  output_schema_json TEXT, example_text TEXT, expected_result TEXT,
  side_effects_json TEXT, network_requirements_json TEXT,
  mode_requirements_json TEXT, validation_status TEXT,
  applicability_json TEXT, known_limits TEXT
)

recipe_sources(recipe_id TEXT FK, chunk_id INTEGER FK,
  PRIMARY KEY(recipe_id,chunk_id))

compatibility(
  id TEXT PRIMARY KEY, component_a_id TEXT FK, component_b_id TEXT FK,
  relation TEXT, status TEXT, constraints_json TEXT, evidence_summary TEXT
)

compatibility_sources(compatibility_id TEXT FK, chunk_id INTEGER FK,
  PRIMARY KEY(compatibility_id,chunk_id))

aliases(alias TEXT, component_id TEXT FK, language TEXT,
  PRIMARY KEY(alias,component_id,language))
```

version_status 為 pinned/unknown；implementation_status 為上述四種；compatibility.status 為 verified/documented/unverified/incompatible。驗證日期與測試方法寫進證據，不能只有 true/false。沒有證據的關係保留 unverified，不推論成兼容。

至少建立 chunks_fts（heading/body/summary_zh_tw/keywords，unicode61），另提供 chunks_fts_trigram（同欄或檢索必要子集）。外部 content 模式須確保 rowid = chunks.id 且重建驗證；只讀成品不附會執行內容的自訂 trigger/view。若使用普通 content FTS，解釋空間代價。

### 檢索契約

提供簡單 Python 參考 reader（標準庫 sqlite3 即可），函式：

```text
search_dependency_docs(query, component=None, version=None, limit=8)
get_dependency_doc(chunk_id)
get_recipe(recipe_id)
```

每筆結果帶 chunk_id/component/version/title/snippet/source_url/section_anchor/retrieved_at/verification_status/implementation_status/score/match_kind。match_kind 至少 exact_version、version_unspecified、reference_only。指定版本不合時不能默默以最新版頂替；可附 reference_only，主回覆清楚指出缺證據。

英文 identifier 查 unicode61，中文長詞用 trigram；一至兩字短詞用別名與有上限的 LIKE fallback（正確 escape `%`、`_` 和 escape 字元）。不要說 unicode61 自動做中文斷詞。採 BM25 或清楚的 deterministic ranking，版本精確性優先於文字分數。

SQL 使用參數化；不要直接把 query 當 FTS 查詢語法，必須 tokenize/quote/限制長度。空 query、引號、括號、OR、星號、emoji、`n8n-nodes` 與中文短詞都不能造成崩潰或全庫無限扫描。limit 限 1..20、snippet 至多 1500 字、整體回傳上限 20000 字；設 progress handler 中斷過長查詢。

reader 以 URI mode=ro 開啟，設定 query_only=ON/trusted_schema=OFF，不允許載入 extensions，不提供任意 SQL 工具。需要 schema inspection 及 allowlist，拒絕未知附加 executable schema。正確處理 SQLite FTS shadow tables，不把合法 FTS 表誤判成惡意。

### 建置、驗證與交付

chunk 保留標題/段落/程式碼邊界，中文摘要與原文分欄；不要把程式碼切斷。除非授權允許且必要，不保存全文。增量建置以來源 URL + version/ref + hash 去重，內容更新後移除舊索引，不留下失效 recipe 引用。

驗證至少：

- PRAGMA integrity_check=ok、foreign_key_check 無錯、FTS 一致、全部 FK/來源引用存在。
- 確認實際產品 Python 的 SQLite 支援所用 tokenizer；若拿不到該 runtime，報未驗證，不假稱通過。
- 離線執行 reader；對 readonly DB 的 INSERT/UPDATE/DELETE 失敗；沒有外連或秘密。
- 核心元件與 pinned versions 覆蓋表；每個 recipe 至少一個具體來源 chunk；無證據列入 gaps。
- 至少 30 個檢索案例，包含中文/英文/API 名稱/錯誤/版本不符/短詞/空結果/惡意 FTS 字串；保存預期 component/來源與命中結果。
- 分辨官方功能與本產品 proposed Broker API；測試提問「OpenRPA 內建 8771 API 嗎」不回錯誤結論。
- 測試「Python staging 是否 OS 沙箱」及「Plan 能 publish 嗎」，答案符合架構並有來源。
- 記錄建置耗時、DB 大小、查詢 p50/p95、測試機與樣本，勿捏造效能數字。
- 檔案完成後 checkpoint/關閉連線，交付可單檔移動的 DB，不依賴遺留 WAL/SHM；checksum manifest 在 DB 外生成，避免自我 hash。

交付：

```text
dependencies.sqlite
schema.sql
build_kb.py
query_kb.py
validate_kb.py
sources.manifest.json
inventory.json
coverage.json
gaps.md
eval_cases.json
eval_results.json
checksums.sha256
BUILD_REPORT.md
README.md
```

README 說明輸入、可重現建置命令、離線查詢、版本更新、授權、匯入驗證、schema migration 及已知缺口。正式 DB 不包含測試用錯誤資訊、虛構內容、憑證、完整聊天、使用者檔案或安裝器 binary。

若缺版本或官方資料，先完成有證據的部分，對缺口列出所需輸入及影響。最終報告區分已驗證、文檔支援、尚待驗證；不能把未執行測試標記通過。

## Prompt 結束
