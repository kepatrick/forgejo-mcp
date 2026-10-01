# 變更紀錄

[English](CHANGELOG.md)

本專案的重要變更皆記錄於此。格式採用 Keep a Changelog，版本遵循 Semantic Versioning。

## [Unreleased]

## [0.4.0] - 2026-10-01

### 新增

- 可選用的 Forgejo 帳號 OAuth 連結，與 MCP client OAuth 分開：session-bound PKCE S256、加密的個別使用者 access／refresh tokens、身分驗證與序列化 lazy refresh；保留 scoped PAT 支援（migration 0015）。
- Admin Dashboard OAuth application 設定：Client ID、加密且不回傳原文的 Client Secret、相符的 Public／Confidential 模式、MCP 對外 base URL 與固定可複製的 redirect URL；不需重啟即可套用（migration 0016）。
- MCP consent 的 Select all／Clear selection，只作用於當下允許的工具；不預選、不自動授權，也不擴大既有 grants。
- 中英文配置、疑難排解、權限界線與撤銷指南，並同步管理員／使用者流程。

### 安全性

- 將前端開發依賴 `brace-expansion` 更新至已修補版本；針對性 lockfile 更新後 npm audit 未發現已知漏洞。
- Application 設定要求 admin／CSRF 驗證，稽核不記錄密鑰；未完成授權綁定設定版本，替換憑證前重新檢查。
- 保留 Strict Dashboard cookies，搭配獨立一次性的 callback binding；驗證指定 username／numeric identity、固定可信 Forgejo destinations、限制 token response，並遮蔽 callback query。
- 區分 OAuth Bearer 與 PAT authentication，採用不同 encryption purposes，refresh 不跨越憑證／grant 界線。

### 修正

- 設定使用 shared read locks 讓多位使用者並行，設定變更與個別使用者 refresh 仍序列化。
- 桌面及手機 consent 的全選按鈕與工具清單保持間距。

### 部署與升級注意事項

- 正式支援 Forgejo 16.0.3，16.0.2 僅為 comparison baseline；舊版本的單次手動讀取不等於相容性保證。
- Schema head 為 `20261001_0016`。備份 PostgreSQL、部署設定與 credential keys，停止舊 App workers，使用相符 release code 升級；不要重新產生密鑰或執行 `down -v`。
- Migrations 0015／0016 升級時保留既有 PAT 與 grants；未完成的舊 Forgejo 授權需重開。已儲存的 Dashboard 設定優先於部署 defaults，包含明確停用。
- Downgrade 會撤銷本地 OAuth 憑證，不會將它們視為 PAT；0016 也刪除 pending attempts 及 Dashboard client 設定。請使用協調的備份／回滾計畫；若需維持停用，先清除部署 defaults。

### 已知限制

- Forgejo OAuth 沒有細分 API scopes。MCP 是工具層級政策，不是獨立 repository／path allowlist；需要更窄的上游權限時使用 scoped PAT 或限制 Forgejo 帳號 membership。
- 清除本地憑證／設定或停止 server 不會撤銷 Forgejo application approval；MCP 與 Forgejo grants 的生命週期分開。
- 既有 CIMD DNS 再解析／rebinding 風險，以及 `/token` 非 ASCII resource 驗證回傳 HTTP 500 的問題仍未修正；非必要不要啟用 CIMD，並閱讀 `docs/security/oauth-2.1.md`。

## [0.3.0] - 2026-09-30

### 新增

- 新增可選用的 OAuth 授權，支援 PKCE S256、動態註冊、有期限的同意授權，以及輪替的不透明 refresh token。
- 新增具交易一致性的 token family 撤銷、歷史資料回填，以及 PostgreSQL concurrency／lifecycle 測試；套用 migrations 0009–0012 前請先閱讀 `docs/security/oauth-upgrade.md`。
- 新增 Claude／OpenAI edge 疑難排解說明，涵蓋 discovery、registration、token exchange 與 Cloudflare bot challenge。
- 在 OAuth consent 中新增工具選擇及授權期限設定；選擇結果會在 authorization code exchange 與 refresh 流程中保留，且不會擴大權限（migration 0014）。

### 修正

- 在保留瀏覽器 Origin 驗證與跨來源 referrer 隱私的前提下，允許已註冊的 OAuth callback 通過 consent page 的 CSP。
- 使用 grant-family identity 保留 OAuth refresh 後的 MCP session，並在每則訊息執行 token 授權與稽核。
- 在解壓縮前拒絕壓縮的 CIMD 文件，並限制原始 response buffering 大小。
- 允許 public client 在未提供 `client_secret` 的情況下提出撤銷請求。
- OAuth 頁面共用 Dashboard 樣式，並在授權前說明 PAT 缺失、工具未獲允許、使用者帳號要求，以及請求已過期等狀況。
- 在 authorization code exchange 過程中保留省略的 redirect URI（migration 0013），並新增 PostgreSQL 與 Chromium regression coverage。

## [0.2.0] - 2026-09-09

### 相容性

- 將最低且唯一正式支援的部署目標提高至 Forgejo `16.0.3+gitea-1.22.0`；Forgejo 16.0.2 僅保留為 CI comparison baseline，不受此 release 正式支援。
- 鎖定官方 16.0.3 Swagger checksum。相較 16.0.2，唯一 schema 差異是未使用的 `IssueMeta` required fields，對已註冊 endpoints 沒有影響。
- 新增有版本紀錄的相容性矩陣 `docs/compatibility.zh-TW.md`，以及詳細的 Forgejo 16.0.3 相容性報告 `docs/forgejo-16.0.3-compatibility.md`。

### 新增

- 在 pull request 與 release CI 執行 OpenAPI comparison，並針對 Forgejo 16.0.3 及保留的 16.0.2 baseline 執行完整 Docker E2E。
- 新增 repository search 與 repository webhook create/list 的 E2E coverage。
- 新增 Dashboard 密碼變更功能；變更後保留目前 session，並撤銷該帳號的其他 active sessions。
- 支援必須登入才能查詢 API version 的 Forgejo instance，透過有大小限制的 same-origin fallback 取得版本，且不傳送 PAT。

### 變更

- 將預設開發用 Forgejo image 從 `16.0.2-rootless` 改為 `16.0.3-rootless`。
- 將 E2E 的廣泛 Forgejo PAT 權限改為明確的 `read:user`、`write:organization`、`write:repository` 與 `write:issue` scopes。
- 在 integration 與 Docker E2E 明確指定 MCP `2025-06-18` negotiation。

### 安全性

- 固定 Forgejo destinations、驗證 remote/path inputs、限制 decompression 大小、遮罩 credentials、序列化 invitation acceptance，並加固 browser/proxy boundaries。
- 將 Compose database credentials 移至受保護檔案，並要求明確設定可信 Forgejo destinations；請閱讀 `docs/security/upgrade-hardening.zh-TW.md`。
- 保留既有 token lifecycle 並加入針對性 regression tests；不包含 OAuth routes 或 migrations。
- 將 `nanoid` 更新至 3.3.18、`cryptography` 更新至 50.0.1，並將 development test stack 更新至已修補的 pytest 9 系列；目前 npm 與 Python dependency audits 均未發現已知漏洞。

### 部署與升級注意事項

- 既有安裝必須依 `docs/security/upgrade-hardening.zh-TW.md` 升級；不要重新產生 PostgreSQL 密碼或 credential encryption key。
- 本版需要新的 database credential files 與可信 Forgejo URL 設定，但沒有 database migration。
- 升級前請備份 PostgreSQL、Compose 設定與 credential encryption secrets。Rollback 時需要使用相符的 image 與設定；不要刪除或重新建立 database data。

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
