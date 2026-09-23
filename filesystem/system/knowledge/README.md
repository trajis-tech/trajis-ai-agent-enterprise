# 依賴知識庫匯入位置

將其他 AI 依 `docs/DEPENDENCY_KNOWLEDGE_DB_PROMPT.md` 建置的 `dependencies.sqlite` 放到此資料夾。

- 產品只做唯讀檢索，不會在執行期寫入或自動產生內容。
- 檔名必須是 `dependencies.sqlite`。
- 匯入後請以唯讀檔案權限部署；Agent 工具不會執行任意 SQL。
- `127.0.0.1:8771` 是本產品自製 OpenRPA Broker，不是 OpenRPA 官方 REST。
