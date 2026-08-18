# Forgejo MCP 使用者指南

[English](user-guide.md)

本指南適用於受邀使用 Forgejo MCP，並希望將 MCP client 連線到 Forgejo 的一般使用者。

## 你需要準備什麼

請向管理員取得：

- Forgejo MCP Dashboard URL；
- 一次性邀請連結；
- 管理員為你登記的 Forgejo username；
- 你獲准使用的工具範圍。

你也需要能登入對應的 Forgejo 帳號，並具有建立 personal access token（PAT）的權限。

## 1. 接受邀請

1. 在邀請失效前開啟一次性連結。
2. 確認畫面上的帳號資訊。
3. 建立安全的本地 Dashboard 密碼。
4. 登入 Dashboard。

Dashboard 密碼與 Forgejo 密碼是兩套不同的密碼。管理員無法取得你的密碼；登入後請使用正常的密碼變更流程。

## 2. 建立 scoped Forgejo PAT

在 Forgejo 中建立新的 PAT：

1. 登入 Forgejo。
2. 點選右上角使用者頭像，進入 **Settings**。
3. 在設定頁面開啟 **Applications**。
4. 在 **Manage Access Tokens** 區域輸入容易辨識的 token 名稱，例如 `forgejo-mcp-laptop`。
5. 依預計使用的 Forgejo MCP 工具選擇必要權限。
6. 點選 **Generate Token**。
7. 立刻複製產生的 token；離開頁面後可能無法再次查看。

選擇權限時只授予預計使用的工具所需範圍：

- 檢視 repository、branch、commit、Issue 與 pull request 時只需要 read access；
- 只有執行 commit、Issue、review、merge、workflow、tag 或 release 時才需要 write access；
- 系統需要 identity/current-user access 來驗證 token 擁有者。

Forgejo scope 名稱可能因版本與 instance policy 不同。請依公司 Forgejo 規範設定，不要直接複製測試環境的廣泛權限。

Forgejo 版本或介面語言不同時，選單文字可能略有差異；Applications 頁面通常位於 `/user/settings/applications`。

建議：

- 可行時設定到期日；
- 不要把 PAT 貼到聊天、原始碼、截圖或 Issue comment；
- 為 Forgejo MCP 使用獨立 PAT，不要重複使用其他 automation token。

## 3. 提交並驗證 PAT

1. 開啟 Dashboard 的 credential 區域。
2. 貼上 Forgejo PAT 並送出。
3. 等待驗證成功。

Forgejo MCP 會呼叫 Forgejo current-user API，並要求回傳的 username 符合管理員設定的 username。PAT 會先加密再儲存，之後不會再次顯示。

若驗證失敗，請確認：

- PAT 屬於正確的 Forgejo 帳號；
- PAT 尚未到期或撤銷；
- PAT 具有 identity/current-user access；
- 已設定的 Forgejo instance 可以連線。

## 4. 建立 MCP token

1. 開啟 MCP token 區域。
2. 使用可辨識 client 或 device 的名稱。
3. 視需要設定到期日。
4. 建立 token。
5. 立刻複製 `fmcp_...` 值。
6. 開啟該 token 的工具權限，從管理員允許你的工具中勾選這個 client 實際需要的工具並儲存。

MCP token 只會顯示一次，請存放在 MCP client 的 secret storage。若遺失，請撤銷舊 token 並建立新 token。新 token 預設不會因為 user allowance 已設定就自動取得全部工具；若未完成第 6 步，client 可能可以連線但看不到任何工具。

MCP token 不是 Forgejo PAT。它用來向 Forgejo MCP 驗證身分；Forgejo MCP 套用集中權限後，才會使用你加密儲存的 Forgejo credential。MCP token 本身不包含也不會回傳 Forgejo PAT，因此無法拿來直接呼叫 Forgejo API。

## 5. 連接 MCP client

使用下列資料設定支援 authenticated MCP Streamable HTTP 的 client：

```text
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
Authorization: Bearer fmcp_...
```

請使用管理員提供的完整 URL，並把自己建立的 `fmcp_...` token 設定在 MCP server entry 的 `Authorization: Bearer ...` header。MCP client 之後會自動在連線與工具呼叫時帶上這個 token；agent model 本身不需要讀取 token。請將 token 存放在 client 的 secret storage，而且每位使用者都必須使用自己的 token。系統不接受 query-string token。不同 client 使用不同 configuration schema；完整範例、欄位對應、連線確認與問題排查方式請參閱 [MCP client 設定](mcp-client-configuration.zh-TW.md)。

連線後可以要求 client 列出工具。工具只有在下列條件全部成立時才會出現：

1. 管理員已全域啟用；
2. 允許你的使用者使用；
3. 已授權給這個 MCP token；
4. 你的 Forgejo PAT 仍有效且已驗證。

## 6. 典型工作流程

依授權範圍，MCP client 可以：

1. 檢視 repositories、git tree、branches、commits、labels、milestones 與既有 Issues；
2. 建立 Issue；
3. 建立 branch；
4. 以單一 commit 變更多個檔案；
5. 建立 pull request，並檢視其中的 commits、diff 與 changed files；
6. 要求 reviewer，並提交、列出或讀取特定 review；
7. 檢視 commit status、dispatch workflow，並查看 Actions run、job、log 與 artifact；
8. 取消執行中的 Action，或刪除已完成的 Action run；
9. 確認 pull request 是否已合併，或執行 merge；
10. 建立 tag 與 release。

Write tools 會直接修改真實 Forgejo repository。允許 client 執行前，請檢查工具名稱、repository、branch 與 proposed arguments。`forgejo_get_pull_request_merge_status` 只表示 PR 是否已經合併；是否可合併請查看 `forgejo_get_pull_request` 的 `mergeable`。

若 write tool 發生 timeout 或連線中斷，不要立刻重試；請先使用 read tool 確認 Issue、commit、PR、merge、tag 或 release 是否已建立，避免重複操作。

全部 47 個工具的 schema 與行為請參閱 [v1 工具目錄](tools/v1-tool-catalog.md)。

## Token 與 credential 維護

下列情況應撤銷 MCP token：

- device 遺失；
- client 設定外洩；
- token 已不再需要；
- audit history 中出現可疑行為。

下列情況應更換 Forgejo PAT：

- PAT 到期；
- 需要變更 scope；
- Forgejo 顯示 PAT 已撤銷；
- PAT 或 Forgejo MCP credential key 可能外洩。

撤銷一個 MCP token 不會撤銷 Forgejo PAT 或其他 MCP tokens。若確認只有 MCP token 外洩，應立即撤銷該 token 並檢查 audit history；通常不需要更換 Forgejo PAT。MCP token 在撤銷前仍可透過 Forgejo MCP 執行其已獲授權的工具，因此外洩事件不可忽略。撤銷 Forgejo PAT 則會停止所有依賴它的 Forgejo 操作。

## 疑難排解

### Server 回傳 401

MCP token 遺失、格式錯誤、過期、停用或已撤銷。請確認 client 送出 `Authorization: Bearer fmcp_...`。

### 工具未出現在列表中

三層權限至少有一層未授權，或 Forgejo credential 已失效。請先在 Dashboard 檢查該 MCP token 的 tool grants；若工具不在可選範圍，再請管理員檢查 global setting 與 user allowance。

### Forgejo 拒絕操作

PAT 可能缺少必要 Forgejo scope，或 Forgejo 帳號沒有 repository 權限。Forgejo MCP 的權限無法超越 Forgejo 本身的拒絕結果。

### Server 回傳 429

已達每個 token 或 user 的 request limit。請依 `Retry-After` 等待，不要持續重新連線。

### Server 顯示 Forgejo unavailable

Forgejo 可能 timeout、rate limit 或暫時無法使用。安全讀取操作可能自動重試；寫入操作不會自動重試。
