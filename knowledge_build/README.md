# 依賴知識庫建置目錄

本目錄獨立產出 `dependencies.sqlite`。通過 `validate_kb.py` 後再複製到 `filesystem/system/knowledge/dependencies.sqlite`。

## 可重現建置

在專案根目錄、使用產品 Python：

```
portable_python\python.exe knowledge_build\build_kb.py
portable_python\python.exe knowledge_build\validate_kb.py
```

建置為離線步驟：語料已寫入 `corpus.py`，內容來自建庫當日抓取的官方頁摘要，不是執行時上網。

## 離線查詢

```
portable_python\python.exe knowledge_build\query_kb.py search "OpenRPA 8771"
portable_python\python.exe knowledge_build\query_kb.py recipe r-openrpa-offline
```

## 版本更新

1. 依 `build.lock.json` 鎖定版本抓官方 tag 或官方文件。
2. 更新 `corpus.py`（禁止無來源補 API）。
3. 重建並跑 validate。
4. 以複製/版本檔切換產品 DB，不要覆寫正在開啟的檔案。

## 授權

DB 內為摘要與短引文。OpenRPA tag LICENSE 為 MPL-2.0；n8n@2.34.6 為 Sustainable Use License；CPython 為 PSF-2.0；SQLite 文件為公有領域。完整再散布請看各 `sources` 的 redistribution 欄。

## 匯入

產品 reader：`app/backend/knowledge.py`（`mode=ro`、`query_only`、allowlist 含 `kb_meta`）。
