# Forgejo MCP v1 Tool Catalog

本文件是 Forgejo MCP **v1.0 工具功能、公開名稱及 schema 邊界的規範文件**。實作、測試、Dashboard 權限顯示與相容性判斷均以本文件為準。

> 狀態：39 個 v1 工具已實作。公開 tool name 與已發布 schema 視為 SemVer public API。

## 1. v1 範圍

v1 提供 24 個唯讀工具及 15 個寫入工具，共 39 個。平台不提供任意 HTTP request、任意 URL 或通用 Forgejo API proxy；每個工具都必須對應 Forgejo v16-compatible OpenAPI endpoint。

| 批次 | 功能 | Tools | 狀態 |
|---|---|---:|---|
| 0 | Forgejo principal | 1 | 已完成 |
| 1 | Repository、contents 與 branch | 6 | 已完成 |
| 2 | Commit、compare 與 status | 4 | 已完成 |
| 3 | Issue 與 comments | 3 read + 3 write | 已完成 |
| 4 | Pull request、review 與 merge | 5 read + 6 write | 已完成 |
| 5 | File content 與 multi-file commit | 2 | 已完成 |
| 6 | Workflow dispatch、tag 與 release | 3 | 已完成 |
| 7 | Git tree、label、milestone 與 PR 查詢補強 | 6 read | 已完成 |

## 2. 共通契約

### 2.1 命名與授權

- Tool name 固定使用 `forgejo_*`。
- 新工具加入 registry 後預設全域停用，也不自動加入 User ceiling 或 Token grant。
- `tools/list` 只顯示通過所有授權層的工具；`tools/call` 每次重新授權。
- MCP Token 決定 internal User 及 Forgejo PAT；任何 tool argument 都不能指定 credential、User ID、PAT 或 Forgejo base URL。
- 有效權限是 MCP tool grant 與 User PAT scope 的交集。

### 2.2 共通輸入限制

| 欄位 | 規則 |
|---|---|
| `owner` | required，1–255 字元，不接受 `/`、控制字元或 URL |
| `repo` | required，1–255 字元，不接受 `/`、控制字元或 URL |
| `ref`、branch、SHA | 1–255 字元；SHA 若指定完整值最多 64 字元 |
| `path` | 1–1024 字元、相對 repository root、不得以 `/` 開頭、不得包含 NUL 或 `..` segment |
| `page` | default `1`，範圍 1–100000 |
| `limit` | default `30`，範圍 1–100，server 不接受無界列表 |
| 搜尋字串 | 最多 256 字元 |
| title | 1–255 字元，trim 後不可為空 |
| issue/PR body | 最多 65,536 字元 |
| comment body | 1–32,768 字元，trim 後不可為空 |
| timestamp | RFC 3339、必須包含 timezone，輸出統一為 UTC |
| 未宣告欄位 | JSON Schema `additionalProperties: false` |

Repository identity 一律使用分離的 `owner` 與 `repo`，不接受 `owner/repo` 混合字串，以避免解析歧義。

### 2.3 共通分頁輸出

有分頁的工具統一回傳：

```json
{
  "items": [],
  "page": 1,
  "limit": 30,
  "has_more": false
}
```

`has_more` 表示目前結果可能仍有下一頁，不承諾精確 total。不得為取得 total 而自動抓取所有頁面。

### 2.4 輸出原則

- 所有工具使用 structured content；同時保留 MCP SDK 產生的 JSON text content。
- 外部 Forgejo response 必須先驗證並轉成穩定的 normalized output，不直接 passthrough 未知欄位。
- URL 只回傳 Forgejo resource 的公開 `html_url`；不回傳帶 credential 的 URL 或 headers。
- 未提供的 Forgejo 欄位回傳 `null` 或省略，不能猜測值。
- File content、diff 與大型 body 必須遵守大小限制。

### 2.5 大小上限

| 類型 | v1 上限 | 超限行為 |
|---|---:|---|
| 一般 Forgejo JSON response | 2 MiB | `response_too_large` |
| 單一 decoded file | 1 MiB | `content_too_large`，不回傳部分檔案 |
| Compare summary response | 2 MiB | `response_too_large` |
| PR diff text | 2 MiB | `diff_too_large`，不回傳部分 diff |
| 單頁 items | 100 | schema validation 拒絕更大 limit |
| Issue comments（上游無 page/limit 時） | 100 筆 | 回傳 `truncated: true` |

大小限制以 bytes 計算，不以 Unicode 字元數替代。

### 2.6 錯誤分類

Tool error 使用穩定類型，訊息不得包含 PAT、MCP Token、Authorization header、Cookie 或 Forgejo HTML error page。

| 類型 | 情境 |
|---|---|
| `authentication_failed` | Forgejo PAT 已失效或被 Forgejo 拒絕 |
| `mcp_forbidden` | MCP token/tool policy 不允許；不揭露隱藏 tool 細節 |
| `forgejo_forbidden` | MCP 已允許，但 PAT scope/resource permission 不足 |
| `not_found` | Repository、issue、PR、commit、ref 或 file 不存在 |
| `validation_failed` | Input schema 或 Forgejo validation 失敗 |
| `conflict` | State transition 或寫入發生衝突 |
| `rate_limited` | Forgejo `429`；只回傳安全的 retry metadata |
| `timeout` | Connect/read/total timeout |
| `response_too_large` | 一般 response 超限 |
| `content_too_large` | File 超限 |
| `diff_too_large` | Diff 超限 |
| `forgejo_unavailable` | Network error 或 Forgejo `5xx` |

唯讀 GET 可針對連線中斷及明確暫時性 `5xx` 做有限 jitter retry；所有寫入工具不得自動 retry。

## 3. Normalized resource shapes

以下是穩定輸出的核心欄位；新增 optional 欄位可做向後相容擴充，移除或改型別需要 major version。

### `UserSummary`

```text
id: integer
username: string
display_name: string | null
avatar_url: string | null
```

### `RepositorySummary`

```text
id: integer
owner: string
name: string
full_name: string
description: string
private: boolean
fork: boolean
default_branch: string
archived: boolean
html_url: string
updated_at: datetime | null
```

### `BranchSummary`

```text
name: string
commit_sha: string
protected: boolean
```

### `CommitSummary`

```text
sha: string
message: string
html_url: string | null
author_name: string | null
author_email: string | null
authored_at: datetime | null
committer_name: string | null
committed_at: datetime | null
parent_shas: string[]
stats: { additions: integer, deletions: integer, total: integer } | null
```

### `IssueSummary`

```text
number: integer
title: string
body: string | null
state: "open" | "closed"
html_url: string
user: UserSummary
assignees: UserSummary[]
labels: { id: integer, name: string, color: string }[]
milestone: { id: integer, title: string } | null
comments_count: integer
created_at: datetime
updated_at: datetime
closed_at: datetime | null
```

### `CommentSummary`

```text
id: integer
body: string
html_url: string | null
user: UserSummary
created_at: datetime
updated_at: datetime
```

### `PullRequestSummary`

```text
number: integer
title: string
body: string | null
state: "open" | "closed"
draft: boolean
mergeable: boolean | null
merged: boolean
html_url: string
user: UserSummary
base: { ref: string, sha: string, repository: string }
head: { ref: string, sha: string, repository: string }
labels: { id: integer, name: string, color: string }[]
created_at: datetime
updated_at: datetime
closed_at: datetime | null
merged_at: datetime | null
```

## 4. 唯讀工具規格

### 4.1 `forgejo_get_current_user`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/user`
- **預期最小 scope:** `read:user`
- **Input:** `{}`
- **Output:** `UserSummary` 的 `id`、`username`；v1 初版可逐步加入其餘 optional 欄位。
- **用途:** 驗證實際 Forgejo principal；不能接受 username 或 credential argument。

### 4.2 `forgejo_list_repositories`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/user/repos`
- **預期最小 scope:** `read:user`；private repository 能見度仍由 PAT 決定。
- **Input:** `page`、`limit`、`order_by`。
- **`order_by`:** `name | id | newest | oldest | recentupdate | leastupdate | alphabetically | reversealphabetically | size | reversesize | moststars | feweststars | mostforks | fewestforks`，default `recentupdate`。
- **Output:** paginated `RepositorySummary`。

### 4.3 `forgejo_get_repository`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`。
- **Output:** `RepositorySummary`，另含 optional `stars_count`、`forks_count`、`open_issues_count`、`permissions`。

### 4.3a `forgejo_create_organization_repository`

- **Risk:** `write`
- **Forgejo:** `POST /api/v1/orgs/{organization}/repos`
- **預期最小 scope:** 能在指定組織建立 repository 的 Forgejo PAT 權限；實際授權由 Forgejo 驗證。
- **Input:** required `organization`、`name`；optional `description`、`private`（default `false`）、`auto_init`（default `false`）、`default_branch`。
- **Output:** `repository: RepositorySummary` 與 `audit_event_id`。
- 不建立組織、不修改組織權限，亦不允許覆寫 Forgejo base URL。組織名稱會作為單一 path segment 驗證與編碼；repository 名稱、描述與 default branch 皆有長度及控制字元限制。

### 4.4 `forgejo_get_file_content`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/contents/{filepath}`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`path`、optional `ref`。
- **Output:**

```text
path: string
name: string
sha: string
ref: string | null
size: integer
encoding: "utf-8" | "base64"
content: string
html_url: string | null
```

- UTF-8 text 回傳 `utf-8`；binary 回傳 base64。decoded size 超過 1 MiB 時拒絕，不截斷。
- Audit 只保存 owner/repo/path/ref、size、SHA-256 hash，不保存 content。

### 4.5 `forgejo_list_branches`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/branches`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`page`、`limit`。
- **Output:** paginated `BranchSummary`。

### 4.6 `forgejo_list_commits`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/commits`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、optional `ref`（映射上游 `sha`）、optional `path`、`page`、`limit`。
- **Output:** paginated `CommitSummary`。
- v1 固定不要求 files payload，避免列表 response 膨脹。

### 4.7 `forgejo_get_commit`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/git/commits/{sha}`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`sha`。
- **Output:** `CommitSummary`，包含 stats；files 回傳 path/status 與上游有提供時的 additions/deletions/changes，最多 100 筆並附 `files_truncated`。

### 4.8 `forgejo_compare_refs`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/compare/{basehead}`，adapter 以 `base...head` 組合並安全編碼。
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`base`、`head`。
- **Output:**

```text
base: string
head: string
total_commits: integer
commits: CommitSummary[]
files: { path, status, additions, deletions, changes }[]
commits_truncated: boolean
files_truncated: boolean
```

Forgejo v16 compare response 不提供可靠的 ahead/behind 或 resolved base/head SHA，因此 v1 不猜測這些值；`base` 與 `head` 回傳正規化後的 request refs。

- 不回傳完整 patch；完整 PR diff 由專用工具提供。
- Audit 不保存 commit messages 或 file content，只保存 refs、counts 及 paths 摘要。

### 4.9 `forgejo_list_issues`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/issues`，固定上游 `type=issues`。
- **預期最小 scope:** `read:issue`
- **Input:** `owner`、`repo`、`state` (`open | closed | all`, default `open`)、optional `labels: string[]`、optional `milestones: string[]`、optional `query`、optional `since`、optional `before`、`sort`、`page`、`limit`。
- **`sort`:** `relevance | latest | oldest | recentupdate | leastupdate | mostcomment | leastcomment`，default `latest`。
- **Output:** paginated `IssueSummary`。

### 4.10 `forgejo_get_issue`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/issues/{index}`
- **預期最小 scope:** `read:issue`
- **Input:** `owner`、`repo`、`number`（integer >= 1）。
- **Output:** `IssueSummary`。
- Audit body 依 audit text limit 截斷；Dashboard 顯示必須 escape。

### 4.11 `forgejo_list_issue_comments`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/issues/{index}/comments`
- **預期最小 scope:** `read:issue`
- **Input:** `owner`、`repo`、`number`、optional `since`、optional `before`。
- **Output:** `{ items: CommentSummary[], truncated: boolean }`，最多 100 筆。
- 同一 endpoint 同時適用 issue 與 PR conversation comments。

### 4.12 `forgejo_list_pull_requests`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`state` (`open | closed | all`, default `open`)、optional `base`、`head`、`label_ids: integer[]`、optional `milestone_id`、`sort`、`page`、`limit`。
- **`sort`:** `oldest | recentupdate | recentclose | leastupdate | mostcomment | leastcomment | priority`，default `recentupdate`。
- **Output:** paginated `PullRequestSummary`。

### 4.13 `forgejo_get_pull_request`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls/{index}`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`number`。
- **Output:** `PullRequestSummary`，另含 optional commit/addition/deletion/changed-files counts。

### 4.14 `forgejo_get_pull_request_diff`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls/{index}.diff?binary=false`
- **預期最小 scope:** `read:repository`
- **Input:** `owner`、`repo`、`number`。
- **Output:** `{ number, format: "diff", size, sha256, content }`。
- Diff 超過 2 MiB 時拒絕，不回傳部分 diff。
- Audit 只保存 number、size、SHA-256，不保存 diff content。

### 4.15 `forgejo_get_git_tree`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/git/trees/{sha}`
- **Input:** `owner`、`repo`、`sha`、optional `recursive`、`page`、`limit`。
- **Output:** resolved tree SHA、bounded entries（path、mode、type、size、SHA）、total count 與 truncated flag。

### 4.16 `forgejo_list_labels`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/labels`
- **Input:** `owner`、`repo`、optional `sort`、`page`、`limit`。
- **Output:** paginated repository labels，包含 description、exclusive 與 archived 狀態。

### 4.17 `forgejo_list_milestones`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/milestones`
- **Input:** `owner`、`repo`、`state` (`open | closed | all`)、optional `name`、`page`、`limit`。
- **Output:** paginated milestones，包含 issue counts、timestamps 與 due date。

### 4.18 `forgejo_list_pull_request_commits`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls/{index}/commits`
- **Input:** `owner`、`repo`、`number`、`page`、`limit`。
- **Output:** paginated `CommitSummary`；固定關閉 files 與 verification payload。

### 4.19 `forgejo_get_pull_request_review`

- **Risk:** `read-sensitive`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls/{index}/reviews/{id}`
- **Input:** `owner`、`repo`、`number`、`review_id`。
- **Output:** normalized review summary，shape 與 review list item 相同。

### 4.20 `forgejo_get_pull_request_merge_status`

- **Risk:** `read`
- **Forgejo:** `GET /api/v1/repos/{owner}/{repo}/pulls/{index}/merge`
- **Input:** `owner`、`repo`、`number`。
- **Output:** `{ number, merged }`。此工具只表示 PR 是否已合併；是否可合併仍使用 `forgejo_get_pull_request` 的 `mergeable`。

## 5. 一般寫入工具規格

所有寫入工具均為 `write` risk、不得自動 retry，成功 response 必須包含 server 產生的 audit event ID。v1 不提供 client-controlled idempotency key；timeout 後 client 應先用唯讀工具確認結果，再決定是否重試。

### 5.1 `forgejo_create_issue`

- **Forgejo:** `POST /api/v1/repos/{owner}/{repo}/issues`
- **預期最小 scope:** `write:issue`
- **Input:** `owner`、`repo`、`title`、optional `body`、optional `assignees: string[]`（最多 20）、optional `label_ids: integer[]`（最多 50）、optional `milestone_id`。
- **Output:** `{ issue: IssueSummary, audit_event_id: string }`。

### 5.2 `forgejo_update_issue`

- **Forgejo:** `PATCH /api/v1/repos/{owner}/{repo}/issues/{index}`
- **預期最小 scope:** `write:issue`
- **Input:** `owner`、`repo`、`number`，以及至少一個 `title`、`body`、`state` (`open | closed`)、`assignees`、`label_ids`、`milestone_id`。
- `null` 與未提供必須有明確區別；不得 passthrough 未宣告欄位。
- **Output:** `{ issue: IssueSummary, audit_event_id: string }`。

### 5.3 `forgejo_comment_issue`

- **Forgejo:** `POST /api/v1/repos/{owner}/{repo}/issues/{index}/comments`
- **預期最小 scope:** `write:issue`
- **Input:** `owner`、`repo`、`number`、`body`。
- 同時支援 issue 與 PR conversation comment。
- **Output:** `{ comment: CommentSummary, audit_event_id: string }`。

### 5.4 `forgejo_create_pull_request`

- **Forgejo:** `POST /api/v1/repos/{owner}/{repo}/pulls`
- **預期最小 scope:** `write:repository`
- **Input:** `owner`、`repo`、`title`、`head`、`base`、optional `body`、optional `draft`。
- 只允許由既有 branch 建立 PR；不建立 branch、commit 或 fork。
- **Output:** `{ pull_request: PullRequestSummary, audit_event_id: string }`。

### 5.5 `forgejo_update_pull_request`

- **Forgejo:** `PATCH /api/v1/repos/{owner}/{repo}/pulls/{index}`
- **預期最小 scope:** `write:repository`
- **Input:** `owner`、`repo`、`number`，以及至少一個 `title`、`body`、`state` (`open | closed`)、`base`。
- **Output:** `{ pull_request: PullRequestSummary, audit_event_id: string }`。

### 5.6 Repository contents、branch 與 commit

| Tool | Forgejo endpoint | 說明 |
|---|---|---|
| `forgejo_list_repository_contents` | `GET /repos/{owner}/{repo}/contents[/{filepath}]` | 列出指定 ref 的檔案或目錄，最多 100 筆 |
| `forgejo_create_branch` | `POST /repos/{owner}/{repo}/branches` | 從 branch、tag 或 commit 建立 branch |
| `forgejo_commit_changes` | `POST /repos/{owner}/{repo}/contents` | 以單一 commit 建立、更新、刪除或移動最多 100 個檔案 |

`forgejo_commit_changes` 接受 `branch`、optional `new_branch`、`message`、`signoff` 與 `changes[]`。每個 change 包含 `operation`、`path`，update/delete 必須提供 `sha`；非 delete 操作必須提供 UTF-8 或 base64 `content`。

### 5.7 Pull request files、reviewers、reviews 與 merge

| Tool | Forgejo endpoint |
|---|---|
| `forgejo_get_pull_request_files` | `GET /repos/{owner}/{repo}/pulls/{index}/files` |
| `forgejo_request_pull_request_reviewers` | `POST /repos/{owner}/{repo}/pulls/{index}/requested_reviewers` |
| `forgejo_remove_pull_request_reviewers` | `DELETE /repos/{owner}/{repo}/pulls/{index}/requested_reviewers` |
| `forgejo_list_pull_request_reviews` | `GET /repos/{owner}/{repo}/pulls/{index}/reviews` |
| `forgejo_submit_pull_request_review` | `POST /repos/{owner}/{repo}/pulls/{index}/reviews` |
| `forgejo_merge_pull_request` | `POST /repos/{owner}/{repo}/pulls/{index}/merge` |

Review event 限定 `APPROVED`、`REQUEST_CHANGES` 或 `COMMENT`，可包含最多 100 個 inline comments。Merge 支援 Forgejo OpenAPI 宣告的 merge、squash、rebase、rebase-merge 與 manually-merged strategy。

### 5.8 Commit status、workflow、tag 與 release

| Tool | Forgejo endpoint |
|---|---|
| `forgejo_get_commit_status` | `GET /repos/{owner}/{repo}/commits/{ref}/status` |
| `forgejo_dispatch_workflow` | `POST /repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches` |
| `forgejo_create_tag` | `POST /repos/{owner}/{repo}/tags` |
| `forgejo_create_release` | `POST /repos/{owner}/{repo}/releases` |

Workflow 工具只提供 Forgejo v16-compatible OpenAPI 已確認的 `workflow_dispatch`；run、job、log 與 rerun 工具須在最低支援版本 Swagger 確認後才能新增。

## 6. Audit 規格

每次允許或拒絕的 `tools/call` 都必須建立 invocation record：

- event ID、User ID、MCP Token ID、Forgejo principal snapshot。
- tool name/version/risk、開始與完成時間、duration、結果狀態。
- owner/repo、issue/PR number、path/ref/SHA 等 normalized target。
- authorization decision 或拒絕原因。
- 脫敏後 arguments；欄位名符合 token/secret/password/authorization/cookie 時一律遮蔽。
- Forgejo HTTP status 與穩定 error classification。
- item count、response bytes、truncated flag、content/diff hash。

永遠不保存：

- Forgejo PAT、MCP Token、Authorization/Cookie。
- 完整 file content 或 diff。
- 未截斷的大型 issue/PR/comment body。
- Forgejo 原始 HTML error page 或 response headers。

寫入工具在 invocation audit 無法建立或完成時 fail closed。唯讀工具 v1 也預設 fail closed；未來若要允許 configurable fail-open 必須另立 ADR。

## 7. 明確排除的工具

v1 不實作也不在 registry 中預留以下工具：

- Delete repository、branch、tag、issue、PR、release 或 comment。
- Update/delete repository；建立 repository 僅限既有組織，且只能透過 `forgejo_create_organization_repository`。
- Protected branch、collaborator、team、organization 權限管理。
- Webhook、deploy key、GPG key、OAuth application 管理。
- 未由最低支援 Forgejo OpenAPI 確認的 Actions run/job/log/rerun，以及 runner、package、secret 或 variable 管理。
- Generic Forgejo API request/proxy。
- 任意 URL fetch 或讓 argument 覆寫 Forgejo base URL。

新增上述能力必須經 threat model 更新、獨立規格與風險審查，不能只新增 handler。

## 8. 實作與驗收順序

1. Repository adapter 共通模型、pagination、error mapping與 response size guard。
2. `forgejo_list_repositories`、`forgejo_get_repository`、`forgejo_list_branches`。
3. Commit/compare tools。
4. Invocation audit pipeline、redaction 與查詢 API；在寫入工具前完成。
5. Issue read tools。
6. PR read tools。
7. File/diff size-sensitive tools。
8. Issue/PR write tools。
9. Contract schema snapshots、真實 Forgejo integration、MCP client compatibility tests。

每個工具的完成條件：

- Registry metadata 及 bounded JSON schema。
- Typed Forgejo adapter method與 normalized output。
- `tools/list` visibility 與 direct `tools/call` authorization tests。
- 2xx、401、403、404、429、5xx、timeout、oversized response tests。
- Audit target、redaction、result summary tests。
- 真實支援版本 Forgejo integration test。
- Tool schema snapshot，確認未發生非預期 breaking change。

## 9. 上游 API 版本基準

最低支援版本鎖定為 Forgejo `16.0.2+gitea-1.22.0`，測試 image 固定使用 `codeberg.org/forgejo/forgejo:16.0.2-rootless`。

- `tests/contracts/forgejo-v16-openapi.json` 保存 39 個 MCP tools 對應的 method、path、operation ID，以及完整 `/swagger.v1.json` SHA-256。
- `scripts/verify_forgejo_openapi.py` 驗證實際 instance 的版本、checksum、registry 完整性與每個 operation。
- `scripts/test-full-docker-e2e.sh` 在每次 CI 以 pinned image 執行 contract verification 及完整 MCP development flow。
- 正式發布前仍須加入最低與最新支援版本的 integration matrix。
- 若上游版本差異影響 schema，必須在 adapter 做 compatibility mapping，不改變公開 MCP tool schema。
