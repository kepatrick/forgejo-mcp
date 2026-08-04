# Forgejo MCP

[English](README.md)

Forgejo MCP 是一套自架的 [Model Context Protocol](https://modelcontextprotocol.io/) 伺服器與管理 Dashboard，讓公司能以集中治理、可控且可觀測的方式，開放 AI client 操作既有 Forgejo instance。

每位使用者透過自己的 scoped Forgejo personal access token（PAT）操作 Forgejo；管理員則決定哪些 MCP 工具可全域使用、可提供給特定使用者，以及可授權給只顯示一次的 MCP token。

> **v0.1.0 是第一個開源版本。** 核心流程已使用 Forgejo 16.0.2 完成本地驗證，但部分 production deployment 能力尚未完整。正式使用前請先閱讀[已知限制](docs/known-limitations.zh-TW.md)。

## 能做什麼

- 提供 38 個工具，涵蓋 repository、git tree、branch、commit、label、milestone、Issue、pull request、review、workflow、tag 與 release。
- 在 Forgejo 原有權限之外，增加全域、使用者與 token 三層工具授權。
- 使用者透過已驗證且限制權限範圍的 Forgejo PAT，以自己的 Forgejo 身分操作。
- 使用 AES-256-GCM 加密儲存 PAT，MCP token 只顯示一次。
- 透過 Web Dashboard 管理 Forgejo 連線、使用者、權限及稽核紀錄。
- 提供遮蔽敏感資訊的 invocation audit、structured logs、health endpoints 與 Prometheus metrics。

## 為公司設計的 MCP 治理層

Forgejo MCP 的定位不只是另一個 Forgejo API wrapper，而是公司 AI client 與 Forgejo 之間的治理層。

- **權限可管理：** 管理員可以集中控制全域啟用的工具、每位使用者可用的工具，以及每個 MCP token 實際取得的工具。
- **操作可控：** AI client 不會取得不受限制的共用 Forgejo token；每次操作仍受使用者 PAT scope、Forgejo repository permission 與 server-side input limit 約束。
- **身分可追溯：** 每個 MCP token 都對應特定使用者與 client，避免所有操作隱藏在共用 service account 後方。
- **行為可稽核：** 系統會記錄工具、使用者、操作目標、授權結果、執行狀態、時間與 correlation ID，並遮蔽敏感資訊。
- **服務可觀測：** Structured logs、health checks、Prometheus metrics，以及 request/user/invocation correlation，可協助公司掌握服務狀態與操作情形。
- **存取可撤銷：** 管理員可以單獨撤銷 client token、移除特定工具授權、停用 Forgejo credential，或停用使用者。
- **憑證相互隔離：** MCP token 與 Forgejo PAT 是不同的憑證。MCP token 不包含也不會暴露 PAT；如果只有 MCP token 外洩，可以直接撤銷該 token，無須更換 Forgejo PAT。

## 運作方式

```text
MCP client ──Bearer token──> Forgejo MCP /mcp ──user PAT──> Forgejo API
                                  │
Web Dashboard ──admin/user──> 權限、credential 與 audit records
                                  │
                              PostgreSQL
```

Forgejo MCP 不會取代 Forgejo 本身的授權。工具必須已全域啟用、允許該使用者使用、授權給該 MCP token，並且使用者的 Forgejo 帳號與 PAT 也有對應權限，才會出現在 MCP client 中。

## 系統需求

- 符合已鎖定 Forgejo 16.0.2 API contract 的既有 Forgejo instance
- Docker Engine 與 Docker Compose
- 用於產生本地 secrets 的 OpenSSL

v0.1.0 支援的部署方式會把 React Dashboard build 進 App image，並一起啟動 App 與 PostgreSQL，不需要另外啟動前端與後端 process。

## 快速啟動

在 repository 根目錄執行：

```bash
cp deploy/compose.example.env deploy/.env
# 繼續前請編輯 deploy/.env 並更換 POSTGRES_PASSWORD。

mkdir -p deploy/secrets
openssl rand -base64 32 > deploy/secrets/admin_password
openssl rand -base64 32 > deploy/secrets/credential_key
chmod 600 deploy/secrets/admin_password deploy/secrets/credential_key

docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

確認服務已經就緒：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
curl http://127.0.0.1:8000/health/ready
```

開啟 <http://127.0.0.1:8000>，使用下列資料登入：

- 使用者名稱：`admin`（或 `FMCP_BOOTSTRAP_ADMIN_USERNAME` 的設定值）
- 密碼：`deploy/secrets/admin_password` 內的值

登入後應立刻更換 bootstrap password。直接使用 localhost HTTP 時需要設定 `FMCP_COOKIE_SECURE=false`；前方有 HTTPS 時則應維持 secure cookie。

Logs、停止服務、清除資料、常見啟動錯誤，以及選用的本地 Forgejo profile，請參閱[快速入門](docs/getting-started.zh-TW.md)。

## 初次設定

登入後依序完成：

1. 更換 bootstrap administrator 密碼。
2. 設定並驗證 Forgejo base URL。
3. 全域啟用需要的工具。
4. 建立使用者、設定其 expected Forgejo username，並傳送一次性邀請。
5. 設定該使用者的工具 allowance。
6. 由使用者驗證 scoped Forgejo PAT 並建立 MCP token。
7. 將需要的工具授權給該 token。
8. 將 MCP client 連線至 `POST /mcp`。

完整流程請參閱[管理員指南](docs/admin-guide.zh-TW.md)與[使用者指南](docs/user-guide.zh-TW.md)。

## MCP 連線

Forgejo MCP 使用需要驗證的 MCP Streamable HTTP：

```text
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
Authorization: Bearer fmcp_...
```

MCP token 只會顯示一次，請存放在 client 的 secret storage；系統不接受 query-string token。欄位對應、連線確認與問題排查方式請參閱 [MCP client 設定](docs/mcp-client-configuration.zh-TW.md)。

## 文件

| 需求 | 文件 |
| --- | --- |
| 安裝並啟動服務 | [快速入門](docs/getting-started.zh-TW.md) |
| 設定 Forgejo、使用者與權限 | [管理員指南](docs/admin-guide.zh-TW.md) |
| 建立 PAT 與 MCP token | [使用者指南](docs/user-guide.zh-TW.md) |
| 連接 MCP client | [MCP client 設定](docs/mcp-client-configuration.zh-TW.md) |
| 確認目前限制 | [已知限制](docs/known-limitations.zh-TW.md) |
| 查詢工具 input 與行為 | [v1 工具目錄](docs/tools/v1-tool-catalog.md) |
| 檢視 credential 處理方式 | [Credential security](docs/security/credentials.md) |

## 開發與驗證

執行 disposable App/PostgreSQL/Forgejo full-stack E2E test：

```bash
./scripts/test-full-docker-e2e.sh
```

執行各項品質檢查：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
```

Forgejo image 固定為 `codeberg.org/forgejo/forgejo:16.0.2-rootless`。可以使用下列指令驗證其他 instance 的 Swagger contract：

```bash
uv run python scripts/verify_forgejo_openapi.py https://forgejo.example/swagger.v1.json
```

## 授權條款

本專案依 [Apache License 2.0](LICENSE) 授權。
