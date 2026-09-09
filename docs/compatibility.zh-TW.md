# Forgejo 版本相容性

[English](compatibility.md)

Forgejo MCP 與 Forgejo 使用彼此獨立的版本號。Forgejo MCP release 只正式支援下表明確列出的 Forgejo 版本。CI comparison baseline 不代表正式支援的部署目標。

## 相容性矩陣

| Forgejo MCP 版本 | 正式支援的 Forgejo 版本 | Comparison baseline | 狀態 |
| --- | --- | --- | --- |
| `v0.1.0` | `16.0.2+gitea-1.22.0` | 無 | 歷史 release |
| `v0.2.0` | `16.0.3+gitea-1.22.0` | `16.0.2+gitea-1.22.0` | 目前 release line |

在 `v0.2.0` tag 發布前，該列代表 `main` 上已完成 review 的 release target。對 v0.2.0 release line 而言，Forgejo 16.0.3 是最低且唯一正式支援的部署目標。Forgejo 16.0.2 保留在 CI 中，只用於偵測相較上一個 MCP release 的 regression。

未列為正式支援的版本即使可能可以運作，也不在支援政策內。Swagger checksum 相符只代表受測 API 文件沒有 drift；這項結果本身不會把其他 Forgejo 或 Forgejo MCP release 納入支援範圍。

## 證據與發布政策

- 16.0.2 到 16.0.3 的 API 與 E2E 詳細評估請見 [Forgejo 16.0.3 相容性報告（英文）](forgejo-16.0.3-compatibility.md)。
- Pull request 與 release CI 都會執行鎖定的 OpenAPI comparison，以及正式支援版本與保留 baseline 的完整 Docker E2E。
- 每個 GitHub Release 與 changelog 版本段落都會記錄該不可變 MCP release 的相容性承諾。
- 支援更新的 Forgejo 版本時，必須提供完成 review 的 contract 證據與 E2E coverage、更新此矩陣，並發布新的 Forgejo MCP 版本。不能只依較新的 patch 或 minor 版號推定相容。
