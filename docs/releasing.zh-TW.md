# 發布 MCP Server image

[English](releasing.md)

本流程發布的是 **Forgejo MCP 自己的版本**，不是 Forgejo 的版本。Forgejo 相容性另外記錄於[版本相容性矩陣](compatibility.zh-TW.md)及每個 release 的 changelog。

## 建議流程：從 GitHub 頁面發布

開始前，先將已 review 的程式、文件、相容性與升級說明合併到 `main`。`CHANGELOG.md` 與 `CHANGELOG.zh-TW.md` 的 `[Unreleased]` 都必須包含有意義且互相對應的內容。

1. 打開 **Actions → Release → Run workflow**。
2. Branch 選 **main**。
3. 輸入新的 stable MCP SemVer，可包含或省略 `v`，例如 `X.Y.Z` 或 `vX.Y.Z`。不要輸入 `patch`、`minor`、Forgejo 版本或 prerelease 版本。
4. 按下 **Run workflow**。這是正式 release request，不是預覽。
5. 等待版本準備、驗證、所有測試、image 發布及 GitHub Release 公開。

手動 workflow 會自行完成機械式升版：

1. 確認 workflow 從目前的 `origin/main` 啟動，並拒絕無效、較舊或衝突的版號。
2. 執行 `python scripts/release.py X.Y.Z --prepare --apply`。
3. 若產生修改，建立 `chore(release): prepare vX.Y.Z` commit 並 push 到 `main`。
4. 固定新 commit SHA；一般 CI、鎖定的 OpenAPI comparison 及完整 Forgejo E2E matrix 都 checkout 並測試這個相同 commit。
5. 所有檢查通過後，才在該 SHA 建立 annotated tag、保留 draft GitHub Release、建置含 provenance 與 SBOM 的版本化 GHCR image、加入 digest，並公開 Release。

版本準備只修改以下七個檔案：

- `pyproject.toml`；
- `uv.lock` 的 root package metadata；
- `frontend/package.json`；
- `frontend/package-lock.json` 的 root package metadata；
- `deploy/compose.image.yaml`；
- `CHANGELOG.md`；
- `CHANGELOG.zh-TW.md`。

Release preparation 不會改變 dependency resolution。已 review 的 `[Unreleased]` notes 會移到有日期的版本段落，並保留新的空白 `[Unreleased]`。

內建 `GITHUB_TOKEN` 推送的 commit 與 tag 不會觸發重複 workflow；目前這次 Release workflow 會自行完成所有必要測試與發布。

### 自動建立 release commit 所需的 repository 設定

GitHub Actions 與組織／repository rules 必須允許 Release workflow：

- 使用 `contents: write` 將產生的 release commit push 到 `main`；
- 使用 `contents: write` 建立受保護的 `v*` tag 與 GitHub Release；
- 使用 `packages: write` 發布 package。

若 `main` 要求 PR、signed commit，或 workflow 無法 bypass 的檢查，自動 commit 會在建立 tag 或 image 前失敗。只授予 Release workflow 必要的最小 bypass；或者改用下一節的本機準備與 PR 流程，不要全面降低 branch protection。

若同時有人更新 `main`，release commit push 會直接失敗，不會覆蓋較新的 commit。

### GitHub CLI 等效操作

```bash
gh workflow run release.yml --ref main -f version=X.Y.Z
```

同一版只能選擇 GitHub UI 或 CLI dispatch 其中一種，不要同時啟動。

## 按下 Run workflow 前必須 review 的內容

- 中英文 changelog 都正確描述實際變更。
- 相容性說明明確區分正式支援的 Forgejo 版本與 comparison baseline。
- 必要環境變數、secret-file 變更、database migration 與 rollback 限制都有文件。
- 相容性矩陣與詳細證據符合 release 承諾。
- Pull-request CI 全部通過。
- Operator 升級前已有 PostgreSQL 與 credential-encryption secrets 的可用備份方案。

對 v0.2.0 release line，既有安裝必須依[安全加固升級指南](security/upgrade-hardening.zh-TW.md)操作。正式支援 Forgejo 16.0.3；Forgejo 16.0.2 只保留為 comparison baseline。本版沒有 database 或 OAuth migration。

## 選用的本機準備與 tag 發布

若 repository rules 要求 release commit 必須透過 PR review，可改用本機腳本，而不是讓 workflow 自動 push。

在乾淨工作目錄預覽或套用升版：

```bash
python3 scripts/release.py patch --prepare
python3 scripts/release.py patch --prepare --apply

# 其他選項：擇一使用
python3 scripts/release.py minor --prepare
python3 scripts/release.py major --prepare
python3 scripts/release.py X.Y.Z --prepare
```

`--apply` 不會建立 commit 或 push。Review 並提交產生的七個檔案，合併到 `main` 後，再使用相同版號執行手動 workflow，或在本機發布 tag：

```bash
python3 scripts/release.py X.Y.Z
python3 scripts/release.py X.Y.Z --publish
```

本機發布要求工作目錄乾淨、位於 `main`、`HEAD` 等於目前 `origin/main`、release metadata 全部一致，且本機與遠端都沒有衝突 tag。同一個 release 只能選一種發布路徑。

只檢查已準備的 metadata，不檢查 Git 狀態：

```bash
python3 scripts/release.py X.Y.Z --check
```

檢查內容包含 Python project 與 lockfile 版號、前端 package 與 lockfile 版號、Compose image 版號，以及中英文 changelog 中非空的正式日期版本段落。

## 發布產物

- Git annotated tag：`vX.Y.Z`。
- GHCR image：`ghcr.io/<owner>/<repo>:X.Y.Z`，名稱自動轉成小寫。
- GitHub Release：合併中英文 changelog notes 並附上 image digest。
- 平台：`linux/amd64`。
- OCI source、version、受測 commit revision labels、minimal provenance 與 SBOM。

Workflow 不發布 `latest` 或浮動 minor tags、不自動把 GitHub Release 標示為 Latest、不發布到 PyPI 或 Docker Hub，也不會更新執行中的部署。

本 repository 的位置：

| 產物 | 位置 |
| --- | --- |
| Releases | <https://github.com/kepatrick/forgejo-mcp/releases> |
| Container image | `ghcr.io/kepatrick/forgejo-mcp:X.Y.Z` |
| Container package | <https://github.com/users/kepatrick/packages/container/package/forgejo-mcp> |
| Workflow runs | <https://github.com/kepatrick/forgejo-mcp/actions/workflows/release.yml> |

若需要匿名下載，請確認 GHCR package 已設為 public。已有 package 時，必須授權此 repository 的 Actions 存取。

## 使用已發布 image

請使用同一個 release tag 的部署檔案與升級說明。未經 review，不要混用新版 Compose 與舊 image。

```dotenv
FMCP_IMAGE=ghcr.io/kepatrick/forgejo-mcp:X.Y.Z
```

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml pull app
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml up -d --no-build
```

Production 建議使用 release notes 中以 digest 固定的 `ghcr.io/...@sha256:...`。升級前請備份 PostgreSQL 與 credential-encryption secrets。切換回舊 image 不會自動回滾 database schema 或設定。

## 發布失敗與重試

**不要 force-push、移動 release tag，或覆蓋已發布 image。**

- **自動 release commit push 被拒絕：**尚未建立 tag 或 image。修正 repository rule，或改由本機準備並透過 PR review，之後可用相同版號重試。
- **Preparation commit 已 push，但 validation／CI 在建立 tag 前失敗：**暫時性錯誤可用相同版號重跑，workflow 會重用已準備的 metadata。若必須修改程式或 changelog，請準備新的 patch 版，不要把內容加入已準備好的版本段落。
- **本機 tag push 失敗：**先檢查 `git ls-remote origin refs/tags/vX.Y.Z` 與 Actions。本機 annotated tag 會刻意保留；若遠端沒有 tag，推送現有 tag，不要重建或移動。
- **已有 draft、但尚未 push image：**確認 GHCR 沒有該版本 image，刪除 draft、不要刪 tag，再 rerun。
- **Image 已 push、但 Release 公開失敗：**不要 rebuild。確認 image revision 等於 tag commit，以 `docker buildx imagetools inspect` 取得 digest，補入現有 draft 後手動公開。
- **Release 已存在：**修正內容必須使用新的 patch 版本發布。
