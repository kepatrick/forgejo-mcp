# Forgejo MCP 快速入門

[English](getting-started.md)

本指南說明如何從 source checkout 啟動 v0.1.0 Docker Compose deployment。這套 deployment 會執行 Forgejo MCP App、內建 Dashboard 與 PostgreSQL；一般使用情境需要既有的 Forgejo instance。

> v0.1.0 是早期的 self-hosted 開源版本，尚未完整達到 production-ready。正式使用或暴露至受保護網路以外的環境前，請先閱讀[已知限制](known-limitations.zh-TW.md)。

## 1. 系統需求

請先安裝：

- Docker Engine；
- Docker Compose v2（`docker compose`）；
- OpenSSL；
- 可以執行下列 command 的 shell。

你也需要符合已鎖定 Forgejo 16.0.2 API contract 的既有 Forgejo instance，而且 App container 必須能連到其 HTTPS API URL。

本指南的所有 command 都應在 repository 根目錄執行。

## 2. 建立部署設定

複製環境變數範例：

```bash
cp deploy/compose.example.env deploy/.env
```

開啟 `deploy/.env`，將 `POSTGRES_PASSWORD` 換成長度足夠的隨機值。使用 hexadecimal value 可以避免 URL encoding 歧義：

```bash
openssl rand -hex 32
```

如果直接透過 `http://127.0.0.1:8000` 存取，請維持：

```dotenv
FMCP_COOKIE_SECURE=false
```

App 位於 HTTPS 後方時應改成 `true`。一般部署應維持 `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=false`。

請勿提交 `deploy/.env`。

## 3. 產生必要 secrets

```bash
mkdir -p deploy/secrets
openssl rand -base64 32 > deploy/secrets/admin_password
openssl rand -base64 32 > deploy/secrets/credential_key
chmod 600 deploy/secrets/admin_password deploy/secrets/credential_key
```

- `admin_password` 是 Dashboard 管理員的初始密碼。
- `credential_key` 用來加密儲存的 Forgejo PAT。

請勿提交、分享或隨意替換這些檔案。替換 credential key 之後，既有的加密 PAT 將無法使用。Container 會先處理唯讀 secret mounts，接著以非特權 `app` user 執行應用程式。

## 4. 啟動服務

在背景啟動：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

第一次 build 可能需要數分鐘。Compose 會啟動 PostgreSQL、執行 Alembic migrations，接著啟動已包含 Dashboard 的 App。

若要在前景執行，請移除 `-d`。

## 5. 確認啟動成功

檢查 container 狀態：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

檢查 readiness：

```bash
curl http://127.0.0.1:8000/health/ready
```

App 應可透過 <http://127.0.0.1:8000> 存取。Readiness 失敗時請查看 logs：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml logs -f app
```

按 `Ctrl+C` 只會停止持續顯示 logs，背景 containers 仍會繼續執行。

## 6. 首次登入

Bootstrap username 預設為 `admin`；若已在 `deploy/.env` 修改 `FMCP_BOOTSTRAP_ADMIN_USERNAME`，則使用修改後的值。

從 `deploy/secrets/admin_password` 取得產生的密碼、登入 Dashboard，並立刻變更密碼。

若登入成功後，瀏覽器在 localhost HTTP 環境又回到登入頁，請確認 `FMCP_COOKIE_SECURE=false`，然後重新啟動 App。

## 7. 連接既有 Forgejo

在 Dashboard 中：

1. 輸入 Forgejo base URL；
2. 驗證連線；
3. 全域啟用需要的工具；
4. 建立並邀請使用者。

請使用不包含 credential、query string 或 fragment 的 HTTPS base URL。App 會透過 `/api/v1/version` 驗證 Forgejo。後續請參閱[管理員指南](admin-guide.zh-TW.md)。

## 8. 停止或重新啟動

停止並移除 containers，但保留 PostgreSQL data：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

再次啟動：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
```

Source 或 image 變更後重新 build：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

## 9. 清除本地資料

> **破壞性操作：** 下列 command 會移除 Compose PostgreSQL data，以及選用本地 Forgejo profile 建立的資料。

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml down -v
```

Secret files 與 `deploy/.env` 仍會保留在 disk。只有確定要建立全新 credentials 時才應另外刪除。

## 10. 選用的本地 Forgejo profile

Forgejo 不屬於一般 deployment stack。若只用於本地測試，先在 `deploy/.env` 設定：

```dotenv
FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true
```

再啟動測試 profile：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile test-forgejo up --build -d
```

測試 Forgejo endpoint 是 <http://127.0.0.1:3000>；從 App container 存取時，base URL 是 `http://forgejo:3000`。

這個 profile 只會啟動本地 Forgejo service，不代表受支援的公司部署方式，也不會自動提供 production-ready users、repositories 與 PATs。完整自動化 integration fixture 請使用 `./scripts/test-full-docker-e2e.sh`。

## 常見啟動問題

### Compose 顯示未設定 `POSTGRES_PASSWORD`

確認 command 包含 `--env-file deploy/.env`，而且該變數存在且不是空值。

### Secret mount 失敗

確認下列檔案存在：

```text
deploy/secrets/admin_password
deploy/secrets/credential_key
```

若透過 `FMCP_ADMIN_PASSWORD_FILE` 或 `FMCP_CREDENTIAL_KEY_FILE` 設定自訂 absolute path，請確認 Docker 可以讀取。

### Port 8000 或 5433 已被使用

修改 `deploy/.env` 中的 `FMCP_HTTP_PORT` 或 `POSTGRES_HOST_PORT`，再重新建立 stack。若修改 HTTP port，Dashboard 與 health URL 也要使用新 port。

### PostgreSQL healthy，但 App 尚未 ready

查看 App logs 中是否有 migration 或 configuration error：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml logs app
```

### Forgejo verification 拒絕 HTTP

一般部署要求 HTTPS。只有本地測試 profile 可以使用 HTTP，且必須設定 `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true`。

## 下一步

- [管理員指南](admin-guide.zh-TW.md)
- [使用者指南](user-guide.zh-TW.md)
- [MCP client 設定](mcp-client-configuration.zh-TW.md)
- [已知限制](known-limitations.zh-TW.md)
