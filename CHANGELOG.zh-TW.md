# 變更紀錄

[English](CHANGELOG.md)

本專案的重要變更皆記錄於此。格式採用 Keep a Changelog，版本遵循 Semantic Versioning。

## [Unreleased]

## [0.1.0] - 2026-09-08

### 相容性

- 第一個 MCP Server release，以 checksum 鎖定的 Forgejo 16.0.2 API contract 為目標。發布 workflow 會在發布前執行既有 Forgejo 16.0.2 Docker E2E。
- 本版不包含 PR #3 提出的 Forgejo 16.0.3 相容性與 OAuth 變更。
- Container 平台：`linux/amd64`。Python package、前端與 MCP release 版本皆為 `0.1.0`。

### 部署與升級注意事項

- 版本化 image：`ghcr.io/kepatrick/forgejo-mcp:0.1.0`，需待 workflow 完成及 package 存取權限設定完成後才可下載。不發布 `latest` image tag。
- 使用 tag `v0.1.0` 的部署檔案。`deploy/compose.image.yaml` 選用已發布 image，保留原有資料庫、secrets 及啟動時 migration 設定。
- 啟動前設定 `POSTGRES_PASSWORD`、bootstrap admin 與 credential encryption secret 檔案，以及 cookie／TLS 設定。本版沒有引入 PR #3 的 OAuth 或必要 Forgejo URL 白名單設定。
- Compose 會先執行 `alembic upgrade head` 再啟動 app；本版 schema head 為 `20250802_0008`。從既有原始碼部署升級前，請備份 PostgreSQL 與 credential encryption secrets。
- 只換回舊 image 不會回滾資料庫。請先驗證 schema 相容性，或還原配套備份。不要把 `docker compose down -v` 當作一般升級或回滾步驟。
- 正式使用前請閱讀已知限制，包括單一 process 的部署限制。

### 新增

- 初始 Python、React、PostgreSQL、Alembic 與 Docker Compose 專案架構。
- Bootstrap Admin 驗證：Argon2id 密碼、server-side session、CSRF 保護、登入限流、session 管理與管理操作稽核事件。
- React 登入與 bootstrap 密碼強制變更流程。
- 管理員設定外部 Forgejo 連線、版本驗證與選用的本地 Forgejo 16 Compose profile。
- 每位使用者的 Forgejo PAT 驗證、AES-256-GCM 加密儲存、輪替與撤銷，以及管理員狀態／撤銷控制和使用者自助 Dashboard。
- 使用者生命週期、管理員與使用者的固定授權邊界、短效單次邀請、啟用流程及停用時立即撤銷 session。
- 管理員使用者管理與邀請接受畫面。
- PostgreSQL 本地開發 port mapping：`127.0.0.1:5433`。
- Application service 與依使用情境劃分的 repository，分離 HTTP、商業交易、稽核寫入與 SQLAlchemy 查詢。
- 使用者自助建立只顯示一次的 MCP token，支援到期時間、雜湊儲存、列表與撤銷；管理員可查詢 metadata 並強制撤銷。
- 靜態工具 registry、全域開關、使用者權限上限、token grants 與預設拒絕的分層授權。
- 已驗證的 MCP Streamable HTTP endpoint，含常數時間 opaque token 比對、session credential 綁定、過濾後的工具探索、呼叫時授權及 `forgejo_get_current_user`。
- 有界的 repository 列表／詳情及 branch 列表工具，具正規化輸出、嚴格 schema、分頁、回應大小限制及 Forgejo 錯誤處理。
- 組織 repository 建立：metadata 限制、可見性與初始化選项、Forgejo 端權限檢查、操作稽核及專屬安全審查。
- Commit 列表／詳情及 ref 比對，含正規化 metadata、有界檔案摘要、path／ref 驗證及輸出 schema 驗證。
- 不可變的 MCP invocation audit，涵蓋允許、拒絕、失敗與成功呼叫；寫入前遞迴遮罩、有界參數、正規化目標與不含內容的結果摘要。
- 依角色限制的 invocation audit 查詢／詳情 API 與 Dashboard 篩選：使用者僅可查詢自己的紀錄，管理員可檢視所有紀錄。
- 有界 Issue 與留言讀寫，具正規化使用者、label、milestone、分頁、時間戳驗證及寫入事件 ID。
- Pull request 讀寫、有界 diff 及 SHA-256 摘要，以及基於 branch 的建立／更新契約。
- 有大小限制的 repository 檔案內容讀取，回傳 UTF-8 或 base64，稽核摘要不含檔案內容。
- Forgejo API-backed repository contents、branch 建立與原子多檔案 commit。
- Pull request 變更檔案、reviewer 新增／移除、review 提交／列表及 merge 工具。
- Combined commit status、workflow dispatch、tag 建立及 release 建立工具。
- Git tree、repository label／milestone、pull request commit／review 及已合併狀態查詢，構成 v1 的 50 個工具目錄之一部分。
- 選用的真實 Forgejo 開發流程 E2E，從 repository 設定、Issue 工作到 review、merge、workflow dispatch、tag 及 release。
- 完整 Docker Compose E2E，涵蓋 Dashboard provisioning、PostgreSQL persistence、真實 Forgejo PAT、MCP 授權及透過 `POST /mcp` 執行完整流程。
- Forgejo 16.0.2 image pin 與註冊工具使用的 checksum-locked OpenAPI operation contract。
- Actions run、job、log、artifact，以及 repository migration 與 pull mirror 管理工具，使 registry 達到 50 個工具。
- 具安全檢查的 release 腳本，支援 patch／minor／major 或指定版號準備、唯讀預覽，以及同步中英文 changelog 與 package 版本。
- 可重用 CI、GitHub Actions 手動發布、版本化 GHCR image，以及附中英文 notes 和 image digest 的 GitHub Release。
- 中英文發布文件與選用已發布 image 的 Compose override。
- 降權 container entrypoint，將唯讀 `0600` secret 檔案安全地提供給非特權 app process。
- MCP request 與多檔案 commit 大小限制、分開的 Forgejo timeout、安全讀取重試，以及 token／user 層級 MCP rate limit。
- 平順停止 invocation、持久化 audit 完成、PostgreSQL pool 釋放與本地 Docker restart 測試。
- Structured JSON request／invocation correlation，以及 Prometheus HTTP、MCP、Forgejo、rate limit 與 database pool metrics。
- 相依服務感知 readiness，回報 PostgreSQL 與 MCP 接受請求狀態。
