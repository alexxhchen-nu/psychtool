# WORKLOG — psychtool

本檔記錄每次實質進展：完整時間戳（America/Chicago）、執行模型、變更、實際核驗結果與未解決事項。不含真實患者資料、密鑰或敏感原文。

---

## 2026-11-24 12:24 CST — PT-01 瀏覽器瘦路徑（walking skeleton）

**執行模型**：kimi-for-coding via Grok Workhorse

### 變更

- 後端新增離線 `FakeTransport`（`psychtool/gateway/fake.py`）：預設模型傳輸，永不開啟 socket，回傳固定合成占位文字。
- `psychtool/config.py` 新增 `transport` 設定（`PSYCHTOOL_TRANSPORT`）：預設 `fake`；未知值**安全回落至 `fake`**（fail closed）；只有明確 `http` 才走真實端點。
- `psychtool/server/app.py`：
  - `POST /api/workspaces`（201/409/400），`_CASE_ID_RE` 錨定 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`，`_workspace_path` 於所有路由不可逃逸。
  - `POST /api/workspaces/{case_id}/materials/paste`：需 `synthetic_confirmed`；錯誤回應只回固定通用字串，不回顯 `str(exc)`。
  - send 端點改用 `_select_transport`，FakeTransport/HTTP/閘道全部檢查（核准 hash、send-once 鎖、data_tier、輸出 PII 閘門）皆在路徑上。
- 前端：`PRIVACY_BANNER`（核准文案）常駐於 `web/src/App.tsx`；新增 `CreateCasePanel`、`PasteMaterialPanel`、`web/src/case-form.ts`（`validateCaseId`/`validatePaste`）；`web/src/api.ts`、`web/src/types.ts` 對應新增。
- 測試：
  - 新增後端測試 `tests/test_fake_transport.py`、`tests/test_create_case_api.py`、`tests/test_paste_material_api.py`、`tests/test_server_transport.py`（含無網路預設 send、transport 選擇、未知值回落、重開持久化）。
  - 既有 `tests/test_egress_api.py` 的 `_configure` 明確 `monkeypatch.setenv("PSYCHTOOL_TRANSPORT", "http")`（這些測試 monkeypatch `http_transport`、無真實網路，需顯式 opt-in 才到得了該傳輸），斷言未刪減。
  - 前端單元測試 `web/tests/case-form.test.ts`。
  - Playwright 端到端 `web/e2e/walking-skeleton.e2e.ts`（以 role/label 定位、無固定 sleep）：建案 → 貼上（確認合成）→ 建候選 → 接受 1 條證據 → prepare → approve → send → fake 文字進入未存編輯器 → 存段落 → 重新整理後核對文字/證據/橫幅。
- `web/playwright.config.ts`：testDir `./e2e`、chromium、webServer `uv run psychtool-server`（倉庫根）、全新暫存 `PSYCHTOOL_WORKSPACES_DIR`、`reuseExistingServer: false`；`testMatch: '**/*.e2e.ts'` 使 bun 不誤抓 e2e、Playwright 仍能發現；移除 transport 覆寫（fake 為預設）。
- `web/package.json` 只加 `"e2e": "playwright test"` script；`web/bun.lock` 保留既有 Playwright 相依。
- `.github/workflows/ci.yml`：PR + push 觸發；`uv run --extra dev pytest -q`；setup-bun + `bun install --frozen-lockfile` / `bun test` / `bun run build`；`bunx playwright install --with-deps chromium`；`bun run e2e`；actions 釘版本標籤。
- `pyproject.toml`：dev extra 加 `httpx>=0.27`、`pythonpath = ["."]`；`uv.lock` 保留（未追蹤→本輪納入）。
- 三份 README（繁/簡/英）同步加入「瀏覽器應用程式」段落與跑/測命令；事實一致、無徽章、無未驗證測試結果聲稱。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **259 passed**（本輪完成後複驗）。
- `cd web && bun test` → **99 passed / 0 fail**（`*.e2e.ts` 命名 + `testMatch` 使 bun 不抓取 e2e）。
- `cd web && bun run build` → 建置成功（tsc + vite）。
- `bunx playwright test --list` → 正確發現 1 個 e2e 測試。
- In-process 端到端煙霧測試（TestClient）：health → 建案 201 → 貼上（p001/p002）→ suggestions → accept → prepare/approve/send（FakeTransport 文字）→ 存段落 → 新 app 實例重開，文字/材料/證據一致。

### 未解決事項

- Playwright 瀏覽器二進位在本沙箱無法執行；e2e 已就緒（spec + config + CI 步驟），由 supervisor 於沙箱外實際執行驗證，狀態為 **pending supervisor verification**。
- `test_unknown_transport_value_falls_back_to_fake` 已通過；`config.py` fail-closed 回落行為為新增語意，已於程式註解與本檔記錄。

---

## 2026-11-24 12:29 CST — PT-01 supervisor review run 2 修正

**執行模型**：kimi-for-coding via Grok Workhorse

### 變更（對應 supervisor 六項回饋）

1. **E2E strict-mode locator**：`getByLabel('Case')` 原解析到 3 個元素（topbar combobox、create-case section、new-case input）。改為 `page.getByRole('combobox', { name: 'Case', exact: true })`（步驟 1 與 reload 步驟皆改）。逐一稽核其餘 `getByLabel`/`getByText`：`New case ID`、paste 面板各欄（`Anonymous material ID` 等）、`Section text`、`Approve request`/`Send once`/`Save section` 按鈕皆為唯一可存取名稱，無 strict 衝突；`Review intake claims` 按鈕位於 paste 面板內、intake 面板為其兄弟節點，定位範圍已註記。
2. **人工審閱核准路徑**：spec 流程為「讀完整外送文字後核准」。因 e2e 釘選 `PSYCHTOOL_DATA_TIER=synthetic`，UI 對 synthetic tier 只顯示 reason 欄（reviewer 欄僅 real tier），且 egress 狀態機對 synthetic 核准**必填** reason。故：先以 `region 'Exact model input'` 斷言完整外送文字可見（她先讀），勾選「I confirm ... reviewed the complete input」checkbox（人工審閱確認），再填 tier 必填的 reason 欄後核准。
3. **Playwright webServer env**：明確釘選 `PSYCHTOOL_TRANSPORT: 'fake'` 與 `PSYCHTOOL_DATA_TIER: 'synthetic'`，避免開發者 shell 的 `PSYCHTOOL_TRANSPORT=http` 讓 e2e 觸網（Playwright 會併入 process.env）。
4. **paste 未知個案 500 → 404 BUG**：`POST /api/workspaces/{case_id}/materials/paste` 對不存在個案原拋未處理 `FileNotFoundError`。改用既有但未使用的 `_existing_workspace_path`（回 404 "case not found"），新增 pytest `test_paste_returns_404_for_unknown_case`；`_pasted_import` 因不再使用已刪除（無 dead code）。
5. **建案後清空輸入**：`CreateCasePanel` 原於成功後 `setCaseId('')`，但順序為先 `onCreated` 後清空。改為先 `setCaseId('')` 再 `onCreated(created)`，並於 e2e 斷言 `New case ID` 於建案後為空。
6. 重跑測試，結果如下。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **260 passed**（含新增 404 測試）。
- `cd web && bun test` → **99 passed / 0 fail**。
- `cd web && bun run build` → 建置成功（tsc + vite）。
- `bunx playwright test --list` → 正確發現 1 個 e2e 測試。
- In-process 驗證：未知個案 paste → **404 `{'detail': 'case not found'}`**。

### 未解決事項

- E2E 瀏覽器執行仍待 supervisor 於沙箱外複跑（locator 修正已針對其回報的 strict-mode 錯誤）。

---

## 2026-11-24 12:32 CST — E2E 證據掛接修正（run 3）

**執行模型**：kimi-for-coding via Grok Workhorse

### 變更（spec only，未動 App.tsx）

- supervisor 於沙箱外複跑 e2e：case/paste/evidence 步驟已通過，但 `preview.toContainText('Synthetic practice note')` 失敗——prepared request 的 `<source_material>` 為空，因 spec 從未為 History 段落勾選已接受的證據（`claim_ids=[]`）。
- `web/e2e/walking-skeleton.e2e.ts`：
  - 選取 History 段落後、Prepare 前，勾選來源清單中的證據 checkbox：`page.getByRole('checkbox', { name: /e2e-material/ })`（可存取名稱來自包覆的 `<label class="claim-row">`，含 claim id 與文字，無需改 App.tsx）。
  - 保留「exact outgoing preview 含貼上證據文字」之斷言。
  - reload 後新增斷言：同一證據 checkbox 對已存段落仍為 checked（`toBeChecked()`），取代原 `claim-list` 純文字斷言。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **260 passed**。
- `cd web && bun test` → **99 passed / 0 fail**。
- `cd web && bun run build` → 建置成功。
- `bunx playwright test --list` → 1 個 e2e 測試被正確發現。

### 未解決事項

- E2E 瀏覽器執行仍待 supervisor 於沙箱外複跑。

---

## 2026-11-24 12:38 CST — PT-01 supervisor 核驗（沙箱外、全新 clone）

**執行者**：Grok Workhorse supervisor（worker：kimi-for-coding；未觸發 deepseek fallback）

### 變更

- run 4：`create_workspace` 併發建案競態（`FileExistsError`）回 409，並加測試；移除 `tests/test_fake_transport.py` 未使用的 import。
- `web/.gitignore` 加入 `test-results/`、`playwright-report/`。
- 本檔時區標記由 CDT 更正為 CST（11 月為標準時間）。

### 實際核驗結果（分支 `pt-01-walking-skeleton` @ `170807f`，全新 clone）

- `uv run --extra dev pytest -q` → **261 passed**，exit 0。
- `cd web && bun install --frozen-lockfile` → exit 0；`bun test` → **99 pass / 0 fail**；`bun run build` → exit 0。
- `cd web && bun run e2e` → **1 passed**（Chromium，建案 → 貼上 → 接受 1 條證據 → prepare → approve → send（FakeTransport）→ 存段落 → 重新整理仍在）。
- 手動實跑 `uv run psychtool-server`：以 curl 走完整路徑；未核准即 send → 409；重送 → 409；重啟伺服器後段落文字與證據仍在；伺服器日誌不含材料正文。
- GitHub Actions `ci`（push）在先前提交上為 success。

### 未解決事項

- `web/tsconfig.app.tsbuildinfo` 為既有受追蹤的建置產物，每次 build 都會變動（本 PR 未提交其變動）。
- CLI `psychtool send` 仍直接使用真實 `http_transport`（既有行為，非 PT-01 範圍）。

---

## 2026-11-24 13:36 CST — PT-02：伺服器/瀏覽器儲存切換為 SQLite（個案隔離）

**執行者**：kimi-for-coding via Grok Workhorse

### 變更

- 新增 `psychtool/store/`（`sqlite_store.py` + `importer.py`）：單一 SQLite 資料庫（stdlib `sqlite3`），WAL + `synchronous=FULL` + `foreign_keys=ON`，`PRAGMA user_version` 管理 schema；全部實體以 `case_id` 開頭的複合主鍵，claims→passages 複合外鍵在資料庫層拒絕跨案引用；egress 請求行內鎖列（owner 校驗釋放）。
- 共享出閘安全層 `psychtool/core/egress_store.py`（`EgressStore` 協定 + `JsonDirStore` + `SqliteGatewayStore`），egress/gateway/review/intake/sections/draft 全部 store-aware，安全邏輯不分叉；JSON 工作區仍是 CLI/評測鏈路格式。
- `psychtool/server/app.py` 全面改用 `SqliteStore`（`PSYCHTOOL_DB_PATH`，預設 `local-data/psychtool.db`）；`_case()` 綁定器（400/404/409）；`_mount_spa` 的 SPA 回退不再應答 `/api/*`（未知 API 路徑回 JSON 404）。
- 新增 `import-json <dir> [--db PATH]` CLI；新增合成範例 `fixtures/case_a001/`（5 份材料，m3 含跳脫引號）。
- 測試：`tests/test_sqlite_store.py`（28）、`tests/test_case_isolation.py`（19，含跨案洩漏與敵意 id）、`tests/test_store_durability.py`（2：SIGKILL 掉電 + 雙實例持久化）、`tests/test_import_json.py`（5）、`tests/test_spa_fallback.py`（5）；六份既有 API 測試改以 `PSYCHTOOL_DB_PATH` 播種。
- `web/playwright.config.ts` 每次執行用全新暫存資料庫（`mkdtempSync` + `PSYCHTOOL_DB_PATH`），釘死 `PSYCHTOOL_TRANSPORT=fake`、`PSYCHTOOL_DATA_TIER=synthetic`。新增 `web/e2e/case-switch.e2e.ts`（R1-AC2：切換個案只見本个案材料與證據）。
- 文件：ADR 0010（取代 ADR 0005 於應用儲存）；ADR 0005 加取代註記；三份 README 同步（資料庫位置、`PSYCHTOOL_DB_PATH`、`import-json`）。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **320 passed**（沙箱 uv cache 唯讀，`uv run --extra dev pytest -q` 無法初始化 cache，以 venv 直跑等價命令）。supervisor 複審後補三項（import-json 預設走 `default_db_path()`、importer 拒絕非 synthetic data_tier、新增確定性 mid-transaction SIGKILL 測試），再跑 → **323 passed**。
- `cd web && bun install --frozen-lockfile` → exit 0；`bun test` → **99 pass / 0 fail**；`bun run build` → exit 0。
- `cd web && bunx playwright test` → **2 passed**（case-switch + walking-skeleton；沙箱無法下載 Playwright 瀏覽器，本次以臨時本機 Chromium 設定執行，正式驗證以 repo 預設的 Playwright 瀏覽器為準）。
- 沙箱外完整指令（`uv run --extra dev pytest -q && cd web && bun install --frozen-lockfile && bun test && bun run build`）：**pending supervisor**。

### 未解決事項

- `web/tsconfig.app.tsbuildinfo` 為既有受追蹤的建置產物，build 後有變動（未提交）。
- Playwright e2e 在沙箱外以 repo 預設設定執行（`bunx playwright install chromium` 後 `bun run e2e`）；沙箱內因無法下載瀏覽器未能以預設設定驗證。
