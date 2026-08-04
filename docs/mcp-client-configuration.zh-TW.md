# MCP client 設定

[English](mcp-client-configuration.md)

本指南說明連接 Forgejo MCP 所需的設定值。不同 MCP client 使用不同 configuration schema，因此應把下列資料對應至 client 的欄位，不要假設同一份 JSON 可以套用到所有 client。

> v0.1.0 支援需要驗證的 MCP Streamable HTTP。只有在指定 client 與版本完成實際測試後，才應加入該 client 的專屬設定範例。

## 連線前準備

你需要：

- 管理員提供的 Forgejo MCP base URL；
- Dashboard 中有效且已驗證的 Forgejo credential；
- 尚未到期、以 `fmcp_` 開頭的 MCP token；
- 至少一個已全域啟用、允許該使用者使用，並授權給該 token 的工具；
- 支援 Streamable HTTP 與自訂 authorization header 的 MCP client。

Credential 與 token 的建立及維護方式請參閱[使用者指南](user-guide.zh-TW.md)。

## Token 要設定在哪裡

是的，每位使用者都要把自己在 Dashboard 建立的 `fmcp_...` token，加入自己的 MCP client／agent 設定。Token 應放在該 MCP server entry 的 `Authorization` header：

```json
{
  "mcpServers": {
    "forgejo": {
      "url": "https://forgejo-mcp.example/mcp",
      "headers": {
        "Authorization": "Bearer fmcp_請替換成自己的token"
      }
    }
  }
}
```

這是通用結構範例；不同 client 可能使用不同的 server、transport 或 HTTP type 欄位名稱。重點是 `/mcp` URL 與下列 header：

```http
Authorization: Bearer fmcp_...
```

MCP client 會在連線、列出工具及呼叫工具時，自動把這個 header 帶到共用的 Forgejo MCP server。Agent model 本身不需要知道或讀取 token；它只會看到 server 根據該 token 身分與權限所提供的工具。每位使用者應在自己的 client 設定自己的 token，不可多人共用。

## 必要連線資訊

```text
Server name:   forgejo-mcp
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
HTTP header:   Authorization: Bearer fmcp_...
```

請用實際 deployment 提供的 hostname 與 token 取代範例值。Endpoint path 是 `/mcp`，不是 Dashboard root，也不是 Forgejo API path。

Client configuration 在概念上必須包含：

```yaml
name: forgejo-mcp
transport: streamable-http
url: https://forgejo-mcp.example/mcp
headers:
  Authorization: Bearer fmcp_...
```

這段 YAML 是欄位對照，不是可以直接複製到所有 client 的設定檔。實際 property name 與 secret storage 用法請依 client 文件設定。

## Token 保存方式

- Client 支援時，請把 token 存在 secret 或 credential storage。
- 不要放入 source control、截圖、聊天、Issue comment 或 URL query string。
- Client 支援時，優先使用 environment variable 或 secret reference，不要直接寫入 plaintext configuration。
- 每個 client 或 device 使用不同 MCP token，才能個別撤銷。
- Token 遺失時，請在 Dashboard 撤銷並建立新 token；原 token 無法再次顯示。

Forgejo MCP 不接受 query-string authentication。Token 必須以 Bearer token 放在 `Authorization` request header。

## 確認連線

儲存設定後：

1. 視 client 需求重新啟動或 reload；
2. 連接 Forgejo MCP server；
3. 要求 client 列出可用工具；
4. 確認預期的 `forgejo_...` 工具已出現；
5. 先執行檢視 current user 或列出已授權 repository 等 read-only operation。

成功登入 Dashboard 不代表 MCP 已經連線。Dashboard session 與 MCP Bearer token 是不同的 authentication mechanism。

## 工具為什麼沒有出現

工具只有在每一層都允許時才會列出：

```text
已全域啟用
    + 允許該使用者使用
    + 授權給這個 MCP token
    + Forgejo PAT 有效且已驗證
    = client 可以看到工具
```

工具執行時仍會套用 Forgejo repository permission 與 PAT scope。Forgejo MCP 無法授予 Forgejo 本身拒絕的權限。

## 疑難排解

### Client 不支援 Streamable HTTP

請改用支援 MCP Streamable HTTP 與自訂 HTTP headers 的 client 或相容 integration。v0.1.0 server 沒有提供已記錄於文件中的 stdio endpoint。

### Client 連到 Dashboard 而不是 MCP

確認 URL 以 `/mcp` 結尾。Dashboard root、`/api` routes 與 Forgejo 自己的 URL 都不是 MCP endpoint。

### Server 回傳 401

請檢查：

- Header name 是 `Authorization`；
- Value 以 `Bearer ` 開頭，後方為完整 `fmcp_...` token；
- Token 尚未到期、停用或撤銷；
- Client 沒有把 token 放進 URL query string。

### 連線成功但沒有列出工具

確認 Dashboard 中的 Forgejo credential 有效且已驗證，並請管理員檢查 global tool setting、user allowance 與 token grant。

### 工具已列出，但 Forgejo 拒絕操作

Forgejo PAT 可能缺少必要 scope，或 Forgejo 帳號無法存取 target repository。請調整 Forgejo permission，或換成具有適當 scope 的 PAT。

### Server 回傳 429

請等待 `Retry-After` 指定的時間。持續重新連線可能繼續消耗每個 token 或 user 的 request allowance。

### App restart 後 client 斷線

v0.1.0 的 active MCP transport sessions 屬於單一 process。App restart 後請讓 client 重新連線。

## 安全提醒

MCP token 用來讓 client 向 Forgejo MCP 驗證身分，並不是使用者的 Forgejo PAT。Forgejo MCP 會先套用自身 authorization rules，再使用使用者加密儲存的 PAT 執行允許的 Forgejo 操作。

MCP token 本身不包含也不會暴露 Forgejo PAT，因此不能直接用來存取 Forgejo API。若只有 MCP token 外洩，請立即在 Dashboard 撤銷該 token 並檢查 audit history；通常不需要更換 Forgejo PAT。不過在撤銷前，外洩的 MCP token 仍可透過 Forgejo MCP 執行已授權工具。

部署前請閱讀 [credential security notes](security/credentials.md)與[已知限制](known-limitations.zh-TW.md)。
