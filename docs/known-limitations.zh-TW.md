# Forgejo MCP v0.1.0 已知限制

[English](known-limitations.md)

v0.1.0 是第一個開源版本，已提供完整 Forgejo 開發流程與核心安全模型，但部分 production-readiness 能力仍未完成。

## 相容性

- API contract 固定為 Forgejo `16.0.2+gitea-1.22.0`，image 固定為 `codeberg.org/forgejo/forgejo:16.0.2-rootless`。
- 其他 Forgejo 版本可能可以運作，但使用前必須執行 `scripts/verify_forgejo_openapi.py` 與本地 integration suite。
- Server 支援使用 Bearer authentication 的 MCP Streamable HTTP，但尚未驗證所有 MCP clients 的專屬設定格式。

## 部署

- v0.1.0 只支援 Docker Compose 部署；React Dashboard 已 build 進 App image，不需要另外啟動前端或後端開發 server。
- 尚未提供正式環境 TLS reverse-proxy 範例。
- 正式暴露 `/metrics` 前，必須透過 deployment network 或 reverse proxy 限制存取。
- PostgreSQL backup/restore scripts、credential-key backup procedures 與 restore drill 尚未完成。
- Upgrade、rollback 與 incident-response runbooks 尚未完成。
- 目前 Compose configuration 是從 source build 的 self-hosting 參考，不是完整的 production infrastructure platform。Operator 需自行負責 TLS termination、network controls 與 infrastructure operations。

## 擴展與可用性

- v0.1.0 App 設計為單一 replica。
- MCP 與 login rate-limit state 儲存在記憶體中，不會在 replicas 之間共享。
- Active MCP transport sessions 屬於單一 process，App restart 後 client 必須重新連線。
- Graceful shutdown 會在設定的 timeout 內等待 active tool invocations，但 host 或 database 被強制中斷時，工作仍可能中止。

## 稽核與管理

- 已提供 invocation audit list 與 detail views。
- 尚未實作 audit CSV/JSON export、retention automation 與 cleanup policies。
- 尚未實作進階 Dashboard filters 與獨立 operational status page。
- Forgejo MCP audit records 是 Forgejo repository history 與 Forgejo audit 的補充，不是替代品。

## 工具範圍

- 目前包含 47 個以 workflow 為導向的工具，不是一對一包裝所有 Forgejo API endpoints。
- Repository 建立僅支援既有組織，並受儲存的 PAT 在 Forgejo 中實際權限限制。
- Organization administration、repository deletion、Forgejo user administration、SSH key management、package administration 與 arbitrary API passthrough 明確排除。
- Workflow dispatch 需要 Forgejo Actions，以及 target repository 中既有的 workflow file。
- Forgejo MCP authorization 無法超越 Forgejo 本身拒絕的 repository access 或 PAT scopes。

## 測試

- 已提供 unit、integration 與 frontend quality checks。
- 真實 App/PostgreSQL/Forgejo development-flow E2E 透過 `scripts/test-full-docker-e2e.sh` 在本地執行，依 v0.1.0 決策不接入 workflow CI。
- Failure injection、security penetration testing、backup restore drill 與多版本 Forgejo compatibility testing 尚未完成。

## 安全邊界

- 使用者必須自行建立適當 scope 的 Forgejo PAT。
- 管理員可以控制工具可用性，但無法查看 PAT 或 MCP token 明文。
- Credential encryption key 遺失後，已儲存的 Forgejo PAT ciphertext 將無法使用；key backup guidance 與 disaster-recovery 工作一併延後。
- 同時取得 database 與 credential encryption key 可能暴露已儲存的 PAT，因此未來 production deployment 必須分開保護兩者。

## Production-readiness 規劃

下一個 production-oriented 工作包包含：

1. TLS reverse proxy 與 security headers；
2. `/metrics` monitoring-network restrictions；
3. PostgreSQL 與 secrets backup/restore automation；
4. 實際 restore drill；
5. Upgrade、rollback 與 incident-response runbooks；
6. Failure-injection 與 security validation；
7. Container publishing 與 SBOM generation。
