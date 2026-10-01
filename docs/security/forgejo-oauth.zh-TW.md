# Forgejo OAuth 配置與權限限制

[English](forgejo-oauth.md)

## 先分清楚兩段 OAuth

```text
AI／MCP client ──MCP OAuth token──> Forgejo MCP ──使用者的 Forgejo OAuth token／PAT──> Forgejo
```

| 項目 | MCP client → Forgejo MCP | Forgejo MCP → Forgejo |
| --- | --- | --- |
| 用途 | 允許 AI client 呼叫選定的 MCP 工具 | 讓後端以使用者本人的 Forgejo 身分呼叫 API |
| 開啟方式 | 部署設定 `FMCP_OAUTH_ENABLED=true` | Admin Dashboard 的 Forgejo OAuth settings |
| Application | 通常由 client 在 MCP `/register` 動態註冊 | 管理員在 Forgejo 註冊一次，供此部署的使用者共用 |
| Callback | 屬於 MCP client，可能是臨時 localhost port | 固定為 Dashboard 的 `/api/me/credential/oauth/callback` |
| Secret | MCP 授權伺服器只接受 Public PKCE client | 可選 Confidential 或 Public，必須與 Forgejo application 一致 |

兩段互相獨立。只開啟 Forgejo OAuth 不會自動開啟 MCP OAuth，也不會自動授權工具。
Forgejo 的 Client ID／Secret 是 **application 設定**，不是多人共用的 Forgejo 使用者 token。
每個 invited user 都必須自行登入 Forgejo、同意授權，後端分別加密保存其憑證。
這不是匿名 SSO、自動註冊帳號或自動加入團隊；仍須先接受 Dashboard 的使用者邀請。

## 部署前提

- 正式支援的 Forgejo baseline 為 **16.0.3**。舊版本即使某次手動測試成功，也不代表正式支援。
- 正式環境使用可從使用者瀏覽器連線的 HTTPS Dashboard，並啟用 secure cookies。
- 部署的 `FMCP_FORGEJO_ALLOWED_BASE_URLS` 必須包含實際、可信的 Forgejo URL；Admin UI 無法擴大這個 allowlist。
- 升級既有部署前，備份 PostgreSQL 並保留 encryption key、資料庫密碼及設定。停止舊 App workers，執行 `alembic upgrade head`（至 migration 0016），再啟動對應版本。
- 不要重新產生既有 encryption key。升級不會清除既有 PAT／OAuth 憑證，但尚未完成的舊 Forgejo 授權流程需要重開。

## 一、在 Forgejo 註冊 application

1. 登入可信 Forgejo 帳號，前往 **使用者設定 → Applications**，即 `/user/settings/applications`。
2. 建立 OAuth application。每個 MCP 部署註冊一次，不是每個使用者註冊一次。
3. **不要使用 `/admin/applications` 的 instance-wide application**；Forgejo 16 文件警告這類 application 可能取得管理權限。
4. 設定完整 redirect URI，例如：

   ```text
   https://mcp.example.com/api/me/credential/oauth/callback
   ```

5. 保存 Client ID；若選 Confidential Client，也保存產生的 Client Secret。不要放進 Git、聊天或截圖。

### 本機測試

同一台機器的瀏覽器與 server 可使用：

```text
base URL:     http://127.0.0.1:8000
redirect URI: http://127.0.0.1:8000/api/me/credential/oauth/callback
```

HTTP 僅允許 loopback、非 production 測試。`localhost` 與 `127.0.0.1`、不同 port、callback 多一個 `/` 都不是可互換的註冊值；請保持完全一致。
其他機器的 `127.0.0.1` 指向它自己，不能拿這個 URL 當作多人使用的公開部署地址。

## 二、在 Admin Dashboard 配置

1. 以 **Dashboard admin** 登入，先設定並驗證 Forgejo instance。
2. 開啟 **Forgejo OAuth settings**，勾選 **Enable Forgejo OAuth linking**。
3. 填入 Client ID，選擇與 Forgejo application 完全一致的 client type：

   | Forgejo application | Dashboard | Secret |
   | --- | --- | --- |
   | 勾選 Confidential Client | Confidential | 必須填入產生的 Client Secret |
   | 未勾選 Confidential Client | Public | 不需要 Secret；仍使用 PKCE S256 |

4. **MCP public base URL** 填的是 Dashboard 的對外 URL，不是 Forgejo URL。只能填 scheme、host／port，不可填 path、帳密、query 或 fragment。
5. Callback 路徑固定；旁邊 **Forgejo redirect URL** 顯示完整地址，可用 **Copy redirect URL** 複製回 Forgejo。
6. 按 **Save Forgejo OAuth settings**，確認啟用開關仍勾選。只儲存 Client ID／base URL、不勾開關，仍然是停用狀態。

儲存後立即生效，不需要編輯 `.env`、掛載 Secret 檔或重啟 App。正在執行的操作可能讓儲存短暫等待；使用者應重新整理頁面並重開未完成的授權。
此 base URL 只用於 **Forgejo callback**，不會一併修改另一段 MCP OAuth 的 issuer／resource。

### Secret 與設定優先序

- Secret 以 AES-GCM 加密存入 PostgreSQL，API 不回傳原文，重新載入 UI 時輸入框保持空白。
- Secret 留空可保留既有值；更換 Confidential Client ID 時必須提供新的 Secret。
- Public 模式會移除保存的 Secret，也不會偷偷沿用部署環境的 Secret。
- 每次儲存設定都會更新版本，要求尚未完成的 Forgejo 授權重新開始。
- 只輪替 Secret、保留 Client ID 時，既有 grants 保留，之後 refresh 使用新 Secret。更換 Client ID 或 Forgejo URL 後，既有 OAuth 憑證需重新連結。
- 已儲存的資料庫設定優先於環境變數，**包括明確停用**。
- 只有從未儲存 Dashboard 設定時，才使用 `FMCP_FORGEJO_OAUTH_CLIENT_ID`、`FMCP_FORGEJO_OAUTH_REDIRECT_URL` 及選用的 `FMCP_FORGEJO_OAUTH_CLIENT_SECRET_FILE`。部署-only 設定及 migration rollback 請參閱[英文詳細指南](forgejo-oauth.md)。

## 三、使用者連結自己的 Forgejo 帳號

1. Admin 邀請 Dashboard user，指定其正確 Forgejo username，並設定工具 allowance。
2. 使用者接受邀請、以 **user 而非 Dashboard admin** 登入。
3. 在 **My Forgejo credential** 點 **Connect with Forgejo OAuth**。
4. 在 Forgejo 登入自己的指定帳號並同意 application 授權。
5. 後端驗證 username 及既有 numeric user ID 相符後，才替換原憑證。拒絕、交換失敗或身分不符會保留原有憑證。

Dashboard 的 Admin 設定好 application，不等於其他使用者已連結完成。
授權 state 為一次性、十分鐘有效，綁定原 Dashboard session、Forgejo instance、client 與設定版本。
不要重用過期連結，也不要在不同瀏覽器中途接續原流程。

## 四、MCP OAuth 選擇工具

如需用 OAuth 連入 MCP，另行啟用 `FMCP_OAUTH_ENABLED`，配置公開 issuer／resource；詳見 [MCP OAuth 運作與升級](oauth-upgrade.md)。
AI client 連線 `/mcp` 並完成自己的 OAuth 註冊／授權，不要把它的 callback 與 Forgejo 的固定 callback 混用。

使用者在 MCP consent 選擇授權期限與工具：

- 預設不勾任何工具；Admin 必須先全域啟用工具，再給此使用者 allowance。
- **Select all** 只選取當下顯示且允許的工具；**Clear selection** 清除勾選。
- 這兩個按鈕不會自動送出授權。選好後仍須按 **Authorize**。
- 每個 token 可有不同工具集合。增加全域／user 權限不會自動擴大舊 token。
- Refresh 只保留或縮小原 grant，也不延長原 MCP 授權期限；要恢復移除的工具或增加工具，必須重新 consent。

## 權限控制的界線

每次操作都必須同時通過：

```text
全域啟用工具 ∩ 使用者 allowance ∩ MCP token 工具 grant
                          ＋ Forgejo 帳號／憑證對該資源的實際權限
```

### MCP 不能把 Forgejo OAuth token 變成 scoped PAT

Forgejo 16 OAuth 沒有實作細分 API scopes。MCP 會限制 AI client 能呼叫的工具，但不會把上游 token 本身變成唯讀或限定幾個 API。
即使 MCP 只選 read 工具，如果上游 token 或後端 encryption key 外洩，攻擊者可能使用該 Forgejo token 本身所能取得的權限。

需要更窄的上游 API 權限時，使用 **scoped PAT**；避免連結 Forgejo 管理員帳號。

### 工具限制不等於 repository allowlist

目前 MCP policy 是工具層級，不是獨立的 repository／path allowlist。
允許一個 repository 工具後，client 可指定該 Forgejo 帳號有權存取的 repository。
要限定 repository，應在 Forgejo 限制帳號／team membership，或使用專用的低權限帳號。

`forgejo_get_repository` 回傳的 `permissions.admin/push/pull` 是 **Forgejo 權限資訊**。
例如回傳 `admin=true`，不代表 MCP token 自動取得所有寫入／管理工具；反過來，勾選 MCP 寫入工具也不能越過 Forgejo 的唯讀權限。

## 停用、撤銷與停止服務並不相同

| 操作 | 效果與限制 |
| --- | --- |
| Admin 停用 Forgejo OAuth linking | 停止連結／使用 OAuth 憑證；不刪除 PAT，不撤銷上游 approval，也不等於撤銷 MCP token family |
| Revoke saved credential | 清除本地保存的 Forgejo access／refresh secrets；仍須另外在 Forgejo 撤銷 application approval |
| Dashboard 撤銷 MCP token／grant | 撤銷該 MCP client 的授權，不會撤銷 Forgejo application approval |
| 移除 client 設定或停止本地 server | 只停止該本地連線，不等於撤銷上游 approval 或刪除資料庫／server grants |

若要完整收回權限，分別撤銷 MCP grant、移除本地 client 憑證，並在授權使用者的 Forgejo settings 移除 application approval。
Forgejo token 的到期／refresh 與 MCP consent 的有效期限是兩個獨立生命週期。

### 本機測試收尾

對 Pi，從 `~/.pi/agent/mcp.json` 的 `mcpServers` 只移除本地測試項目，例如 `forgejo-local-oauth`；不要覆寫其他連線。
如也需清除 client 的 OAuth 憑證，先在其 MCP 介面 sign out。現行 Pi 內建功能使用 `/mcp logout <server>`；安裝替代 MCP extension 時應依該 extension 的指令操作。
外部修改設定後，執行 **`/reload`** 或重啟 Pi，避免目前 session 仍保留舊工具。

使用原部署的 Compose project／env／override 執行 `docker compose ... stop`，保留原 volumes 與秘密檔。
**不要執行 `down -v`、刪除備份或重新產生密鑰**，除非明確要不可逆地清空資料。
之後恢復時使用同一部署設定與 volume，先啟動 PostgreSQL，再啟動 App；不要順便啟動本地 Forgejo／runner。

## 常見問題

| 現象 | 檢查方式 |
| --- | --- |
| linking is not enabled | 檢查 Admin 的 enable 開關、已儲存設定、Forgejo instance 與部署 allowlist；使用者重新整理頁面 |
| denied／expired／unverified | 這是通用提示，不代表一定是 username 不符；用無秘密的 event／status 確認失敗階段 |
| token exchange HTTP 400 | 先核對 Public／Confidential、Client ID／Secret、完整 redirect URI，再重開授權；目前 log 不保存 provider 錯誤 body，僅 400 不能確定唯一原因 |
| 身分驗證失敗 | 切換到 invitation 指定的 Forgejo 帳號；username 與既有 numeric ID 都要相符 |
| OAuth 連結成功但不能 MCP consent | 檢查全域工具與 user allowance，並至少勾一個工具 |
| MCP 只有少數工具 | 檢查本 token 選擇、全域／user 政策與 client 的工具 exposure／cache |
| 私有 repo 回傳 not found | 核對 owner/name 及帳號可見範圍；404 本身不能證明 OAuth 失敗 |
| refresh 失敗 | 重新連結或改用 PAT；不要盲目重放可能已輪替的 refresh token |

請勿公開 codes、state、tokens、密碼或 Client Secret，也不要在反向代理記錄 callback query／Admin 設定 request body。
自動化整合測試的 Forgejo token／principal endpoints 使用 mocks；一次手動讀取成功只驗證該次帳號／資源，不代表所有寫入工具或不受支援版本都通過。

## 相關文件

- [英文完整配置與安全設計](forgejo-oauth.md)
- [MCP OAuth 安全與部署](oauth-2.1.md)
- [MCP OAuth 升級與生命週期](oauth-upgrade.md)
- [Credential 安全](credentials.md)
- [版本相容性](../compatibility.zh-TW.md)
- [目前已知限制](../known-limitations.zh-TW.md)

官方參考：
- https://forgejo.org/docs/v16.0/user/authentication/oauth2-provider/
- https://forgejo.org/docs/v16.0/user/api/usage/
