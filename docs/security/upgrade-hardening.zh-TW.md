# 安全加固升級指南

[English](upgrade-hardening.md)

這項變更與 Forgejo 版本驗證及 OAuth 支援彼此獨立，不會新增 OAuth routes、token tables、database migrations、PAT scopes 或 MCP tools。

升級前請備份 database、Compose 設定與 encryption key。請勿提交備份或把其中的 credentials 輸出到畫面或 logs。

## 必要設定變更

- 將 `FMCP_FORGEJO_ALLOWED_BASE_URLS` 設為精確的可信 Forgejo base URL 清單。空清單現在會在所有環境拒絕帶有 PAT 的 request；production 若沒有這項部署端固定值，也會拒絕啟動。
- 只有需要使用 browser client 時才設定 `FMCP_MCP_ALLOWED_ORIGINS`。不帶 `Origin` 的 native client 仍受支援。CORS 並不是 authentication。
- 只有可信的直接 proxy 才能加入 `FMCP_TRUSTED_PROXY_CIDRS`。使用 application-level proxy chain 時應停用 Uvicorn 的 proxy-header rewriting；因此提供的 Compose command 使用 `--no-proxy-headers`。
- 依文件透過 database/password files 提供資料庫 credentials，不要把它們放在 container environment variables，且檔案權限應維持 `0600`。
- TLS verification 預設維持啟用。`FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS` 是明確的例外，不是建議的 production 設定。
- Private repository migration host 需要 `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS`。同時應保留 Forgejo 端 migration policy 與可抵禦 DNS rebinding 的 egress filtering。

## 升級既有 Compose 安裝

這是 credential 儲存方式的 migration，**不是密碼輪替**。不要對既有安裝執行 README 的全新安裝 secret-generation commands。PostgreSQL 只會在初始化空白 data directory 時使用 `POSTGRES_PASSWORD_FILE`；修改該檔案不會改變既有 role 的密碼。

1. 安全備份 database、既有設定與 secret files，並記錄目前的 Compose project name、database user/name 與 secret mount paths。不要修改現有的 `admin_password` 與 `credential_key`。
2. 使用既有 Compose 設定停止 stack（`docker compose ... down`），**不要加 `-v`**。啟動升級後的 stack 時，應保留相同 project name 與 `postgres-data` volume。不要用 `compose.example.env` 覆蓋既有 `deploy/.env`，而是合併必要設定。
3. 在 private directory（`umask 077`）建立 `deploy/secrets/postgres_password`，內容必須是**目前可用的 PostgreSQL 密碼**，不是新產生的密碼。使用安全 editor 或 secret manager；不要把密碼放進 command arguments、shell history、logs 或 commits。
4. 使用相同 credentials 與既有 database name 建立 `deploy/secrets/database_url`：`postgresql+asyncpg://<encoded-user>:<encoded-password>@postgres:5432/<encoded-database>`。URL components 必須 percent-encode，尤其是含有 `@`、`:`、`/`、`%`、`#` 或 `?` 的密碼；`postgres_password` 檔案則必須存放原始密碼，而非 URL-encoded value。不要更動 `POSTGRES_USER` 與 `POSTGRES_DB`。
5. 將兩個新檔案設為 `0600`。若使用自訂路徑，請在 `deploy/.env` 設定 `FMCP_POSTGRES_PASSWORD_FILE` 與 `FMCP_DATABASE_URL_SECRET_FILE`，並保留既有的 admin/encryption-key 自訂路徑。加入上一節所述的可信 Forgejo URL 與必要 proxy 設定。
6. 使用相同 project name 與 volume 啟動升級後的 stack，檢查 readiness、Dashboard login 與一個 authenticated MCP tool call。若 database authentication 失敗，請檢查檔案是否包含既有 credentials；**不要刪除 volume 或重新產生 encryption key**。
7. 驗證完成後，從目前使用的 `deploy/.env` 移除舊 `POSTGRES_PASSWORD` 設定，並保留受保護的升級前設定以便 rollback。

若確實需要輪替密碼，請在 maintenance window 中另外明確更新 PostgreSQL role 與兩個 secret files。

## 行為變更

不安全的 path segment、內嵌 remote credentials 與過大的 response 現在會被拒絕。Forgejo response 會在 decoding 時限制 decompression 大小；接受 gzip 與 zlib-wrapped deflate，但 chained 或不支援的 encoding 會 fail closed。沒有 body 的 204/304/HEAD response 會忽略 compression metadata。Invitation acceptance 會序列化；login throttling 依 client IP 與 normalized username 計算；logs 會遮罩 credentials。

Audit free text 使用 heuristic，而不是通用 secret classifier。類似時間的文字、明確數值比例與 release version notation 仍可讀取；不要把 free-text tool argument 當作傳遞 secret 的管道。

這項 PR 不需要 database migration。Rollback 時請還原相符的設定與 application image，不需還原或刪除 database data。Rollout 後應驗證 readiness、authenticated tools、無 token 時會拒絕 request，以及 hostile `Origin` 會回傳 403。Release 前應執行 PostgreSQL suite 與完整 Docker E2E。
