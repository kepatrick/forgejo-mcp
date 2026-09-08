# 發布 MCP Server image

[English](releasing.md)

本流程發布的是 **Forgejo MCP 自己的版本**，不是 Forgejo 的版本。
同一個 MCP image 可以支援多個已驗證的 Forgejo 版本；請在每次 release notes
列出實際測試過的版本，不要把未測試的相容性視為保證。

## 快速操作：選版號，再手動發布

同一支 `scripts/release.py` 現在支援版本準備與正式發布。準備階段不會建立
commit／tag 或 push；發布階段只發布已審查並合併到 `main` 的版本內容。

### A. 本機準備下一版

先提交已審查的變更，並在中英文 `[Unreleased]` 寫好實際變更說明。
腳本不會替你杜撰或翻譯 release notes。接著在 repository 根目錄執行：

```bash
# 只預覽：0.1.0 -> 0.1.1
python3 scripts/release.py patch --prepare

# 在乾淨工作目錄套用預覽內容
python3 scripts/release.py patch --prepare --apply

# 其他選項：擇一使用，不要依序全部執行
python3 scripts/release.py minor --prepare       # 0.1.0 -> 0.2.0
python3 scripts/release.py major --prepare       # 0.1.0 -> 1.0.0
python3 scripts/release.py 0.3.0 --prepare        # 指定版本
python3 scripts/release.py current --prepare    # 第一版／已準備好的版本
```

可用 `--date YYYY-MM-DD` 指定發布日期，預設為本機當天日期。
已準備好的版本會保留原本審查過的日期與 notes。現在初版 `0.1.0` 已有正式段落，
可用 `current`；該版本發布後，應選更高版本，不要重用版號。

`--apply` 自動更新七個檔案：`pyproject.toml`、`uv.lock`、前端兩個 package 檔案、
`deploy/compose.image.yaml` 及中英文 changelog。Unreleased 內容會移到新的日期版本
段落，歷史段落保持不變。相依套件解析結果不變，只同步 root package 版號 metadata。
部署文件、相容性承諾及 migration 仍需人工 review。

工作目錄不乾淨、降版、缺少翻譯 notes、來源版號不一致，或目標版本段落與 Unreleased
衝突時，會停止準備。預覽允許未提交內容；套用要求乾淨工作目錄。請 review diff、
跑測試，依既有流程提交並合併到 `main`。不要重複執行相對升版；`patch` 永遠從
目前 project 版號往上加。

### B. GitHub 頁面手動發布，不必在本機推送 tag

Workflow 與版本準備 commit 已合併到預設分支後：

1. 打開 **Actions → Release → Run workflow**。
2. 分支選 **main**。
3. 輸入已準備好的版本，例如 `0.1.1` 或 `v0.1.1`。
4. 按下 **Run workflow**。這是正式發布，不是預覽。
5. 等待驗證、CI、image 上傳及 GitHub Release 公開。

輸入版號必須和已提交 metadata 一致；網頁不會偷偷改版號或 commit。
其他分支的手動發布會被拒絕。Workflow 固定 checkout 觸發時的 commit，測試後
將 annotated tag 建在同一個 commit，即使 main 在測試期間前進也不會換成未測試版本。
已有 tag 若指向其他 commit 會拒絕；若指向相同 commit，可供復原流程重用，不會移動。

內建 `GITHUB_TOKEN` 推送的 tag **不會**觸發另一個 tag workflow，本次手動 workflow
會自行完成發布。Repository rules 必須允許 workflow 建立 release tag；不要為此
任意關閉 tag 保護。

也可用已登入的 GitHub CLI 手動觸發：

```bash
gh workflow run release.yml --ref main -f version=0.1.1
```

原本的 `python3 scripts/release.py 0.1.1 --publish` 仍可使用。同一版擇一使用
網頁／CLI 觸發或本機推送 tag，不要兩邊都執行。兩者都適用 draft reservation
與本文後面的失敗復原規則。

## 發布產物與前置設定

- Git annotated tag：`vX.Y.Z`。
- GHCR image：`ghcr.io/<owner>/<repo>:X.Y.Z`，名稱自動轉成小寫。
- GitHub Release：合併 `CHANGELOG.md` 與 `CHANGELOG.zh-TW.md` 對應版本的中英文段落，附 image digest。
- 目前只發布 stable SemVer 與 `linux/amd64`。不發布 `latest`、浮動 minor tag，
  也不自動將 GitHub Release 設為 Latest，避免較舊維護版覆蓋新版指向。
- 需要 Python 3.12+、Git，以及可推送 repository tag 的身分。
- GitHub Actions 必須啟用，組織政策須允許 workflow 使用
  `contents: write` 與 `packages: write`。使用內建 `GITHUB_TOKEN`，不需要額外 PAT。
- 首次發布後，確認 GHCR package 的 visibility；若要公開下載，請在 package
  settings 設為 public。已有同名 package 時，需授權此 repository 的 Actions 存取。
- 建議保護 `main` 與 `v*` tags，禁止修改／刪除已發布版本，限制 release 權限。
  Draft reservation 是本流程的防重發機制，不是 registry 層級的 immutable-tag 保證。

## 發布到哪裡？

本 repository `kepatrick/forgejo-mcp` 的發布目的地：

| 產物 | 位置 |
| --- | --- |
| Git tag | GitHub repository 的 `vX.Y.Z` tag |
| Release notes 與 image digest | <https://github.com/kepatrick/forgejo-mcp/releases> |
| Docker image | `ghcr.io/kepatrick/forgejo-mcp:X.Y.Z` |
| Container package 頁面 | <https://github.com/users/kepatrick/packages/container/package/forgejo-mcp> |
| 發布執行狀態 | <https://github.com/kepatrick/forgejo-mcp/actions/workflows/release.yml> |

本機腳本在 publish 模式負責檢查、建立及推送 Git tag；prepare 模式只預覽或更新
本機版本 metadata。也可由手動 Actions 建立 tag。Image 在 GitHub Actions runner 上建置，
再推送到 **GitHub Container Registry（GHCR）**，不是 Docker Hub。
它不會發布 Python 套件到 PyPI，也不會自動更新你的部署。
上面的 image／package 需等第一次成功發布後才可使用；新 package 也需確認公開權限。
若在 fork 執行，image 路徑會改用該 fork 的 owner／repository。

## 1. 準備 release commit

先將本流程合併進 `main`。發布前完成：

1. 建議使用 `python3 scripts/release.py patch --prepare --apply`（或其他版號選項）
   同步版本檔案。如果手動修改，則更新 `[project].version`、執行 `uv lock`，並同步
   前端與 image override。第一版若使用現有 `0.1.0`，不需為了發布任意提高版本。
2. 將 `CHANGELOG.md` 與 `CHANGELOG.zh-TW.md` 要發布的內容移到有日期的版本段落，
   保留新的 `[Unreleased]`；兩種語言使用相同版號與實際發布日期。
3. 明確寫出 Forgejo 相容性、環境變數變更、migration、升級與回滾限制。
4. Review、commit、合併並 push 到 `origin/main`。

Changelog 格式（日期與內容請依實際 release 填寫）：

```markdown
## [Unreleased]

## [0.1.0] - YYYY-MM-DD

### Added
- Initial release.

### Compatibility
- Tested against Forgejo 16.0.2.

### Upgrade notes
- Back up PostgreSQL and credential encryption secrets before upgrading.
- Describe required migrations and rollback compatibility here.
```

只有明確指定 `--prepare --apply` 才會更新版號及 lockfile，且不會替你 commit。
`--publish` 只發布已提交的 metadata，不會隱式升版。

### 首次 v0.1.0 發布準備清單

目前準備的 release 以 Forgejo 16.0.2 為目標，不包含 PR #3。
Project、lockfile 與前端版本均已是 `0.1.0`，不需要提高版號。
Changelog 暫定日期為 `2026-09-08`；若改天發布，請同步調整中英文日期。

- [ ] 確認中英文 changelog，特別是相容性與升級說明。
- [ ] Review `scripts/release.py`、測試、兩份 Actions workflow 與 image override。
- [ ] 確認 Actions／package 寫入權限，安排首次發布後設定 GHCR public access。
- [ ] 自行檢查未追蹤的巢狀 `forgejo-mcp/` checkout；需要保留時移到此工作目錄外。
      不要把它加入 release commit，也不要直接刪除。
- [ ] 執行 `python3 scripts/release.py 0.1.0 --check` 與測試。
- [ ] 依專案 review 政策提交變更、合併並推送到 `main`。需包含中英文 changelog、
      `scripts/release.py`、`tests/unit/test_release_script.py`、`.github/workflows/ci.yml`、
      `.github/workflows/release.yml`、`deploy/compose.image.yaml`、中英文發布指南與 README。
      未檢查 untracked files 前，不要直接 `git add .`。
- [ ] 確認工作目錄乾淨，且本機 `main` 與遠端 `main` 一致。
- [ ] 預覽後，確定要公開發布時才執行 `--publish`。
- [ ] 等待 Release workflow，確認 GHCR digest／公開權限，並測試免登入 pull。

## 2. 預覽，再明確發布

在 repository 根目錄：

```bash
python3 scripts/release.py 0.1.0
# 確認 version、commit 與 notes 無誤後才執行：
python3 scripts/release.py 0.1.0 --publish
```

預設只有檢查與預覽，不建立 tag、不 push。
檢查包含版號／lockfile 一致、非空的正式 changelog、乾淨工作目錄（含 untracked）、
位於 main、HEAD 等於遠端 main、tag 在本機與遠端都不存在。
它會以 `git ls-remote` 讀取遠端，不會自動 fetch、merge 或 push branch。

若有未追蹤的資料夾，請先自行確認內容，再移到 repository 外，或依專案政策忽略；
不要為了通過檢查直接執行 `git clean`。

只檢查 release metadata（不代表可安全發布）：

```bash
python3 scripts/release.py v0.1.0 --check
```

## 3. GitHub Actions 執行流程

推送 `v*` tag 或使用 **Run workflow** 後，`.github/workflows/release.yml` 會：

1. 驗證 stable tag、metadata，以及該 commit 已包含在遠端 main。
2. 重用 CI：Python lint／typecheck／PostgreSQL 測試、前端檢查與 build、
   現有完整 Docker E2E。相容性測試範圍仍以當時的 CI 設定為準；目前不是多版本 matrix。
3. 手動發布時先在已測試 commit 建立或驗證 tag，再確認沒有同 tag 的 GitHub Release
   （包含 draft），建立 draft 作為發布保留記錄。
4. Build 並 push 版本 image，附 OCI version、revision、source labels、provenance 與 SBOM。
5. 將 digest 加入 notes，公開 GitHub Release。

任一測試失敗都不進入 publish job。推送 tag 不等於發布完成，請確認 Actions 結果。

## 使用已發布 image

以下指令僅適用於該版本確實發布後。請使用該 release 的部署檔案及升級說明，
不要任意混用新版 Compose 與舊 image。範例 image 路徑：

```text
ghcr.io/kepatrick/forgejo-mcp:0.1.0
```

現有 `deploy/compose.yaml` 預設為本地 build。已附上的 `deploy/compose.image.yaml`
預設使用 `ghcr.io/kepatrick/forgejo-mcp:0.1.0`。若要選擇其他已發布版本、fork image
或 digest，可在 `deploy/.env` 設定 `FMCP_IMAGE`（或在 shell export）：

```dotenv
FMCP_IMAGE=ghcr.io/kepatrick/forgejo-mcp:0.1.0
```

沿用既有 secrets／環境設定，並明確禁止本機 build：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml pull app
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml up -d --no-build
```

正式部署可將 image 改成 release notes 中的 `ghcr.io/...@sha256:...`。
資料庫 migration 不一定向後相容，回滾不能只換回舊 image；升級前應備份資料庫
及 credential encryption secrets，並閱讀 release 的回滾限制。

## 發布失敗與重試

**不要 force-push、移動 Git tag，或覆蓋已發布 image。**

- 本機 tag push 失敗：腳本保留 annotated tag，因為網路錯誤不代表遠端沒有收到。
  先檢查 `git ls-remote origin refs/tags/vX.Y.Z` 與 Actions；確認遠端沒有該 tag 後，
  可手動 `git push origin refs/tags/vX.Y.Z`，無須重建 tag。
- 驗證或 CI 失敗、尚未建立 draft：若是暫時性問題，可以 rerun；若需修改程式，
  用新 commit／新版本，不要把既有 tag 移到修正版。
- Draft 已建立但 image 尚未 push：workflow 會拒絕直接重跑。人工確認 GHCR
  **確實沒有**該版本 image 後，才刪除 draft（不要刪 Git tag），再 rerun。
- Image 已 push，但 Release 公開步驟失敗：不要重建 image。核對 image revision
  與 tag commit，使用 `docker buildx imagetools inspect ghcr.io/<owner>/<repo>:X.Y.Z`
  取得 digest，將 image／digest 補入現有 draft，再手動 publish draft。
- Release 已存在：腳本／workflow 拒絕重新發布。修正請發新 patch 版本。
