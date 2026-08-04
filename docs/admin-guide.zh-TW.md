# Forgejo MCP 管理員指南

[English](admin-guide.md)

本指南說明 v0.1.0 Dashboard 中的 Forgejo 連線、使用者 onboarding 與 MCP 工具權限管理流程。請先依照[快速入門](getting-started.zh-TW.md)安裝並啟動服務。

## 管理模型

Forgejo MCP 不會取代 Forgejo 授權，而是在 Forgejo 前方增加第二層控制：

```text
MCP token authentication
        +
global tool setting
        +
user tool allowance
        +
token-specific grant
        +
Forgejo account and PAT permission
        =
MCP client 可以使用該工具
```

管理員負責本地存取控制，但無法取得使用者 Forgejo PAT 或只顯示一次的 MCP token 明文。

## 開始前

請先完成[快速入門](getting-started.zh-TW.md)，並確認 `/health/ready` 成功，再繼續本指南。React Dashboard 已包含在 App image 中，不需要另外啟動前端與後端 server。

## 1. Bootstrap administrator

第一個管理員由下列設定建立：

- `FMCP_BOOTSTRAP_ADMIN_USERNAME`；
- `FMCP_BOOTSTRAP_ADMIN_PASSWORD_FILE` 指向的檔案。

首次登入時：

1. 從受保護的 secret file 取得 bootstrap password；
2. 登入 Dashboard；
3. 立刻變更密碼；
4. 確保 secret file 不會進入 source control。

## 2. 設定 Forgejo instance

在 Dashboard 輸入公司的 Forgejo base URL。Forgejo MCP 會 normalize URL，並驗證 `/api/v1/version` 後才儲存。

一般部署應遵守：

- 使用 HTTPS；
- URL 不得包含 credential、query string 或 fragment；
- 確保 App 可以連到 Forgejo API；
- 維持 `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=false`。

只有明確啟用的本地測試 profile 才允許 HTTP。

v0.1.0 已依 Forgejo `16.0.2+gitea-1.22.0` contract 測試。連接其他版本前請先閱讀[已知限制](known-limitations.zh-TW.md)。

## 3. 設定全域工具

檢查 38 個工具，並只啟用組織預計提供的工具。Global disable 是最高層的 kill switch：停用後，所有使用者與 token 都無法使用該工具。

建議逐步開放：

- 先啟用 read tools；
- write tools 只提供給實際需要的 repositories 與 users；
- 另外審查 merge、workflow、tag 與 release 權限。

工具風險與 schemas 請參閱 [v1 工具目錄](tools/v1-tool-catalog.md)。升級後新增的工具預設維持全域停用，也不會自動加入既有 user allowances 或 token grants；管理員應先審查風險，再逐層開放。

## 4. 建立並邀請使用者

1. 在 Dashboard 建立本地使用者。
2. 正確設定其 expected Forgejo username。
3. 產生 30 分鐘有效、只能使用一次的 invitation link。
4. 透過經核准的私密管道傳送連結。
5. 請使用者接受邀請並建立本地密碼。

本地 Dashboard username 與 expected Forgejo username 用途不同。Forgejo username 用來驗證 PAT 擁有者，normalize 後必須符合 Forgejo current-user response。

邀請若過期或使用失敗，請建立新邀請，不要重複使用舊 URL。

## 5. 設定 user allowance

User allowance 定義使用者能授權給自己 MCP tokens 的最大工具集合。

Least privilege 建議：

- 只允許符合使用者角色的工具；
- 將 read-only user 與可寫入或 merge 的 user 分開；
- release 與 workflow tools 另行審查；
- 使用者角色或專案改變時移除不再需要的權限。

## 6. 使用者 credential 與 MCP token

使用者必須：

1. 登入 Dashboard；
2. 提交 scoped Forgejo PAT；
3. 通過 username verification；
4. 建立只顯示一次的 MCP token；
5. 在 allowance 範圍內選擇授權給 token 的工具。

管理員可以查看狀態與 metadata，但不能查看 PAT 或 MCP token 明文。

## 7. 檢查稽核紀錄

Tool invocation records 包含：

- user 與 MCP token identity；
- Forgejo username；
- tool name、version 與 risk；
- authorization decision 與 denial reason；
- 遮蔽後的 arguments 與 extracted target；
- status、duration 與 bounded result summary；
- 不含 credential 明文的 error classification。

可使用 request ID 與 invocation ID，將 Dashboard records 和 structured application logs 關聯起來。

Forgejo MCP audit records 用來補充 Forgejo repository history 與 Forgejo 本身的 audit，不是取代它們。

## 8. 停用或撤銷存取

請採取最小但有效的處置：

- 只有單一 client 或 device 受影響時，撤銷該 MCP token；
- 只需移除一項能力時，移除 token grant；
- 使用者角色改變時，移除 user allowance；
- PAT 失效或外洩時，停用 Forgejo credential；
- 需要全面暫停時，停用 user。

停用 user 會撤銷其本地 sessions，並阻止 MCP tokens 繼續驗證。

## 操作 endpoints

- `/health/live`：確認 process 正在執行。
- `/health/ready`：確認 PostgreSQL 可用，而且 MCP 正在接受工作。
- `/metrics`：Prometheus metrics；正式使用前必須限制存取。
- `/api/system/version`：回報應用程式版本。

Logs 預設為 JSON，並包含 request、user 與 invocation correlation fields。Logs 不可當成 secret storage。

## v0.1.0 部署狀態

v0.1.0 是 self-hosted 開源版本，production deployment 能力尚未完整。Operator 需自行負責 TLS termination 與 infrastructure operations；目前未包含 backup/restore automation 與 production incident runbooks。正式使用前請閱讀[已知限制](known-limitations.zh-TW.md)。
