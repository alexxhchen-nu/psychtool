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

---

## 2026-11-24 14:41 CST — PT-03：本地安全基線與僅附加稽核日誌（S3/S4/S6）

**執行者**：kimi-for-coding via Grok Workhorse

### 變更

- 新增 `psychtool/server/security.py`：每次啟動一組工作階段權杖（顯式參數 → `PSYCHTOOL_SESSION_TOKEN` ≥32 字元 → `secrets.token_urlsafe(32)`），所有 `/api/*`（除 `GET /api/health`）要求 `X-Psychtool-Token`；Host 僅允許 loopback hostname（否則 400）；每個回應帶嚴格 CSP 與 `nosniff`/`no-referrer`/`DENY`；SPA index 注入 `<meta name="psychtool-session">` 且 `Cache-Control: no-store`。權杖值永不進日誌。
- 新增 `psychtool/server/selfcheck.py`：啟動自檢逐項記錄（bind/token/host-check/csp/data-dir/disk-encryption/audit-chain/send-lock-recovery）；資料庫位於雲端同步資料夾即拒絕啟動（整段路徑元件比對，`Dropboxed-notes` 不誤判）；磁碟加密（FileVault/dm-crypt/BitLocker）僅警告。
- `psychtool/server/main.py`：僅綁定 loopback，非 loopback 的 `PSYCHTOOL_HOST` 以 exit 2 拒絕啟動；啟動前跑自檢。
- `psychtool/server/app.py`：接線 middleware 與稽核事件；所有錯誤回應改固定文案（不再回傳 `str(exc)`）。
- 新增 `psychtool/store/audit.py`：SQLite `audit_log` 表（schema v2），`BEFORE UPDATE/DELETE` trigger 擋修改，`entry_hash` 雜湊鏈（sha256 of canonical JSON）可偵測繞過 trigger 的竄改；writer 結構性拒絕自由文字（action/object_type/destination 白名單、object_id 限識別符形狀含 `-`/`_` 開頭、content_hash 限 64 hex）。
- 新增 `psychtool/store/recovery.py`：crash 後 fail-closed 復原——外來 boot id 的 send lock：status `sent` 只清鎖；其餘標記終態 `send_interrupted`（永不可再送）；僅 transition lock 陳舊時以 `egress.transition_lock_recovered` 稽核；本 boot 的鎖不動；每列 UPDATE 以觀察到的 owner 為條件（掃描後被改的列跳過）；冪等。
- Schema v2 遷移：新增 audit_log + triggers，並重建 `egress_requests`（SQLite 無法改 CHECK；`PRAGMA defer_foreign_keys=ON` + 建新表/複製/drop/rename + `PRAGMA foreign_key_check`）。
- `EgressStatus` 新增終態 `send_interrupted`，貫穿 `types.ts`、`egress-state.ts`（phase/message/validateRecoveredRequest）、`EgressReviewPanel.tsx`（標籤「Send interrupted — prepare a new request」，terminal，不可 send）。
- 前端 `api.ts` 從 meta tag 讀權杖並附於每個 API 請求；`vite.config.ts` proxy 從 `PSYCHTOOL_SESSION_TOKEN` 注入權杖。
- 測試：新增 `tests/test_security.py`（36）、`tests/test_selfcheck.py`（37）、`tests/test_audit_log.py`（26，含 token_urlsafe `-`/`_` 開頭 request id 與 v1→v2 重建後 recovery）、`tests/test_send_lock_recovery.py`（7，含 SIGKILL 子进程、sent 後 crash、本 boot 鎖不動、競態跳過、冪等）；`tests/conftest.py` 提供 `build_client`；前端新增 `web/tests/api-session-token.test.ts`（6）與 `egress-state` 的 send_interrupted 測試（5）；e2e 新增 `web/e2e/security.e2e.ts`（CSP 標頭、無 CSP console 錯誤、無權杖 401）。
- 文件：ADR 0011；三份 README 同步（本地安全基線、開發權杖提示、新測試）。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **428 passed**（連跑 3 次全綠；沙箱 uv cache 唯讀，`uv run --extra dev pytest -q` 無法初始化 cache，以 venv 直跑等價命令）。supervisor 指出的 request id 開頭 `-`/`_` 導致稽核 500 的真 bug 已修（白名單放寬），非 flake。
- `cd web && bun test` → **110 pass / 0 fail**；`bun run build` → exit 0；`web/dist/index.html` 無內聯 script/style，與嚴格 CSP 相容。
- 正常啟動的 self-check 輸出（`run_self_checks`，generated 權杖）：
  - `self-check ok: bind 127.0.0.1`
  - `self-check ok: session token: generated (not shown)`
  - `self-check ok: Host header restricted to loopback names`
  - `self-check ok: strict Content-Security-Policy on all responses`
  - `self-check ok: data dir is not inside a cloud-sync folder`
  - `self-check warn: system disk encryption: off (warning only in M1)`（沙箱機無 FileVault/dm-crypt，屬預期警告）
  - `self-check ok: audit chain verified (0 entries)`
  - `self-check ok: stale send-lock recovery: 0 recovered`
- 沙箱外完整指令（`uv run --extra dev pytest -q && cd web && bun install && bun test && bun run build`）與 Playwright e2e：**pending supervisor**（沙箱無法下載瀏覽器）。

### 未解決事項

- Playwright e2e（含新 `security.e2e.ts`）需在沙箱外以 repo 預設設定執行。
- 稽核鏈防「可被發現的竄改」，不防有檔案權限者 drop trigger 後重算整條鏈（ADR 0011 已聲明）；本專案尚未符合 HIPAA。

---

## 2026-11-24 15:15 CST — PT-03 修正：稽核列與狀態變更同交易（supervisor round 2）

**執行者**：kimi-for-coding → deepseek-flash via Grok Workhorse（Kimi 5 小時配額用盡，HTTP 429，自動 fallback）

### 變更

- **稽核原子性（阻塞項）**：把四個事件從路由層移進 store 層既有交易內。
  - `claim.accept`：改由 `CaseStore.add_claim` 在插入 claim 的同一交易寫入（content_hash 為 claim.text 的 sha256，永不寫 claim 文字）。
  - `egress.prepare` / `egress.approve` / `egress.invalidate` / `egress.send`：`CaseStore.save_egress_request` 在交易內先讀該列前一 status，僅在 status 實際變更時寫對應稽核列（同狀態不重複寫），與狀態保存同一交易。
  - `egress.send` 的 destination：server 在呼叫 `send_approved` 前設 `case.audit_destination = config.transport`（`fake`/`http`）；寫入時仍過白名單。`SqliteGatewayStore` 轉發該屬性。
  - 新增白名單 action `egress.invalidate`（`AuditAction` + `AUDIT_ACTIONS`）。
  - JSON store 路徑（`JsonDirStore` / core `save_egress_request`）維持不變，不寫稽核。
  - 移除路由層 `claim.accept`、`egress.prepare`、`egress.approve`、`egress.send` 的 `append_audit`，以及 send 外層吞錯的 `except Exception`。保留 `egress.output_blocked`（事件非狀態變更），其失敗日誌改固定字串 `logger.error("could not audit blocked model output")`，不再用 `exception()`。
- **日誌衛生（小項）**：確認 `recovery.py` 無任何 logging（不會外洩例外文字）；`selfcheck.py` 的 `except` 只回傳固定狀態字串（`unknown`/`not-encrypted`），不含例外訊息。
- **測試**（`tests/test_audit_log.py`）：
  - `test_claim_accept_and_audit_row_roll_back_together`：注入 `append_audit` 失敗於 claim accept，斷言 claim 與稽核列皆回滾（注入錯誤以 500 回應呈現）。
  - `test_sent_save_and_audit_row_roll_back_together_fail_closed`：注入 `egress.send` 稽核失敗，斷言 status 仍為 `approved`、無 `egress.send` 列、send 鎖仍持有（fail-closed）；以新 boot id 復原 → `send_interrupted` 且恰一列 `egress.send_lock_recovered`，仍無 `egress.send`。
  - `test_full_flow_produces_one_audit_row_per_event_in_order`：完整流程恰好一列、依序 `case.create`、`material.import`、`claim.accept`、`egress.prepare`、`egress.approve`、`egress.send`，且 send 列的 destination 為 `fake`、content_hash 相符。
  - `test_invalidation_writes_audit_row_in_same_transaction`：`invalidate_request` 產生 `egress.invalidate` 列，content_hash 相符。
- **文件**：ADR 0011 更新為「事件與狀態同一交易」，補上 `egress.invalidate` 與 `audit_destination` 機制。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **432 passed**（連跑 3 次全綠）。
- `cd web && bun test` → **110 pass / 0 fail**；`bun run build` → 成功。
- 說明：沙箱 `uv` cache 唯讀，`uv run --extra dev pytest -q` 無法初始化；以 `.venv/bin/python -m pytest -q` 等價執行。

### 未解決事項

- Playwright e2e 仍需沙箱外執行（沙箱無法下載瀏覽器）。
- 稽核鏈只讓竄改「可被發現」，不防有檔案權限者 drop trigger 後重算整鏈（ADR 0011 已聲明）；本專案尚未符合 HIPAA。

---

## 2026-11-24 15:23 CST — PT-03 supervisor 核驗與修正（沙箱外、全新 clone）

**執行者**：Grok Workhorse supervisor（worker：kimi-for-coding，run 4–6 遇 Kimi 配額 HTTP 429 後自動 fallback 至 deepseek-flash 完成 round 2）

### supervisor 直接修正

- `web/src/App.css`：移除 Google Fonts 遠端 `@import`（被嚴格 CSP 擋下、`security.e2e.ts` 抓到，也違反 S3「無遙測/無外連」）；改為本機字型堆疊。
- 新增 `tests/test_no_telemetry.py`：掃描 `psychtool/**/*.py` 與 `web/src`（ts/tsx/css/html）及 `web/index.html`，非 loopback 的 http(s) URL 一律失敗。
- `psychtool/server/main.py`：替 `psychtool` logger 加 INFO handler，啟動日誌才會真的顯示通過的自檢項（原本只看得到 warn 行）；`create_app` 改在雲端同步檢查之後才 import。
- `psychtool/server/app.py`、`psychtool/server/__init__.py`：模組層 `app` 改為延遲建立，import 不再開啟預設資料庫（同步資料夾會在建立 DB 檔前就被拒）。
- `psychtool/server/security.py`：權杖以 bytes 比對，非 ASCII 權杖回 401 而非 500；Host 的 port 必須是純數字（`127.0.0.1:80@evil.example` 拒絕）。
- 新增 `tests/test_startup.py` 與 `test_security.py` 新案例；每項修正都先確認在舊程式上失敗（red）再通過（green）。
- 修正本檔 PT-03 前兩則的時間（原寫成 UTC 數字）與執行者。

### 實際核驗結果（commit 565e5b2，全新 clone）

- `uv run --extra dev pytest -q` → **440 passed**（連跑 3 次）。
- `cd web && bun install --frozen-lockfile && bun test` → **110 pass / 0 fail**；`bun run build` → 成功；`bun run e2e` → **3 passed**（case-switch、security、walking-skeleton）。
- 實機 `uv run psychtool-server`（port 8811/8812）：無權杖、錯誤權杖、非 ASCII 權杖 → 401；`evil.example` 等 Host → 400；正確權杖 → 200；四次啟動的日誌都找不到權杖；稽核列與日誌都找不到標記字串 `ZEBRA-MARKER-7f3a`；直接對 DB 下 `UPDATE`/`DELETE audit_log` → `IntegrityError: audit log is append-only`；`verify_audit_chain` → `(True, 14, None)`。
- 發送中途當機：http transport 指向本機掛住的假端點，送出後 SIGKILL 伺服器 → 重啟後請求變 `send_interrupted`、鎖清除、寫入一筆 `egress.send_lock_recovered`；再送 → 409；假端點總共只收到 **1** 次請求；再重啟 → `0 recovered`（冪等）。
- `PSYCHTOOL_HOST=0.0.0.0` → exit 2；資料庫在 `Google Drive` 下 → exit 2。

---

## 2026-11-24 15:57 CST — PT-04：M1 上傳規則、每案合成確認與僅記錄型別的錯誤處理

**執行者**：Kimi for Coding（kimi-for-coding）

### 變更

- `psychtool/core/ingest.py`：新增伺服器專用 `parse_server_upload`——僅 `.txt`/`.md`、上限 10 MiB（讀 MAX+1 判定）、無 OCR；拒絕以 `ServerUploadError` 攜帶白名單 reason code 與固定文案（`too_large`/`unsupported_type`/`scan_not_supported`/`not_utf8`/`empty`）；CLI `parse_upload` 行為不變。
- `psychtool/store/sqlite_store.py`：schema v3——`cases` 新增 nullable `synthetic_confirmed_at`（v2→v3 為 `ALTER TABLE`）；`confirm_synthetic()` 以 `UPDATE ... WHERE ... IS NULL` 實現 set-once。
- `psychtool/store/audit.py`：白名單新增 `case.confirm_synthetic`。
- `psychtool/server/app.py`：上傳路由改走 `parse_server_upload`，拒絕回 `{detail, reason}`（413/400）且先於任何寫入；未確認個案回 409 `confirmation_required`；新增 `POST .../synthetic-confirmation` 與 `GET /api/workspaces/{case_id}`；貼上路徑確認後亦記 `case.confirm_synthetic`（set-once）；新增捕捉全部例外的 500 處理器（固定 body，只記例外型別名）。
- `psychtool/server/main.py`：`_uvicorn_log_config()` deep-copy 已安裝 uvicorn 的 `LOGGING_CONFIG`，沿 logger 樹找到實際有 handler 的一層掛 `UvicornErrorTraceFilter`（uvicorn 0.54 的 `uvicorn.error` 無 handler，記錄向上傳播）；filter 把帶 `exc_info` 的記錄改寫為 `unhandled error: <型別名>`。
- `psychtool/server/security.py`：新增純 ASGI `SecurityHeadersASGIMiddleware`，在 app.py 包到已建成中介軟體堆疊最外層——ServerErrorMiddleware 送的固定 500 也帶 PT-03 安全標頭（原本會遺漏）。
- 前端：`web/src/upload.ts`（僅 .txt/.md 驗證、R12 固定說明、顯示伺服器白名單拒絕文案）、`web/src/api.ts`（`ApiError.serverMessage`、`confirmSynthetic`、`getWorkspace`）、`MaterialUploadPanel.tsx`（首次上傳確認閘門）、`App.tsx`（載入確認狀態）。
- 測試：`tests/test_upload_api.py`（R2-AC1/2/3、R12、版本、無回顯標記、500 捕捉、uvicorn 子程序 stderr 掃描）；`tests/test_audit_log.py`（v1/v2 遷移改用 `_SCHEMA_VERSION`、新增 v2→v3 遷移測試、full-flow 稽核序含 `case.confirm_synthetic`）；`tests/test_ingest.py`（先確認再上傳）；`tests/conftest.py`（`build_client` 加 `raise_server_exceptions`）；`web/tests/upload.test.ts` 改寫（並把 raw NUL byte 改為 `` 跳脫）；新增 `web/e2e/upload.e2e.ts`。
- 文件：ADR 0012；三份 README 各加一段材料上傳說明。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **468 passed**（沙箱 `uv` cache 唯讀，`uv run` 不可用；以 `.venv` 直跑等價）。
- `cd web && bun test` 與 `bun run build`、Playwright e2e：沙箱限制，待 supervisor 沙箱外執行。

### 未解決事項

- Playwright e2e（含新 `upload.e2e.ts`）需在沙箱外跑瀏覽器。
- M1 無 OCR 為刻意取捨；掃描檔支援需另開 ADR。

---

## 2026-11-24 16:05 CST — PT-03 review answers from Alex, and PT-04 supervisor verification

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding: runs 1–2 hit the 5-hour quota (HTTP 429), and from run 3 the automatic retry succeeded. The deepseek-flash fallback was not triggered.

### Alex's answers to the 4 PT-03 questions (2026-11-24)

1. **Vite dev-mode Host check:** keep relying on Vite's own Host check. Not changed in M1.
2. **User-chosen case / material ids:** switch to generated ids before real data arrives. Tracked separately; not in PT-04.
3. **Audit hashes:** switch to HMAC (keyed hashes) before real data arrives, together with SQLCipher. Tracked separately; not in PT-04.
4. **Unexpected errors in logs:** add a catch-all error handler that logs only the exception type. The client gets a fixed 500. **Done in PT-04.**

### Supervisor direct fixes

- `CaseStore.confirm_synthetic` now writes the `case.confirm_synthetic` audit row in the **same transaction** as the confirmation. The worker version wrote it in the route as a separate transaction, which broke ADR 0011. Added a rollback test that injects an audit failure: the confirmation rolls back too. The test was confirmed failing on the old code first.
- `web/e2e/upload.e2e.ts`: the PDF step now actually submits and checks the R12 message. Added a server-side check (direct API upload of a PDF → 400 `scan_not_supported`, material count unchanged).

### Verification (fresh clone)

- `uv run --extra dev pytest -q` → **469 passed**; `bun test` → **114 pass / 0 fail**; `bun run build` → ok; `bun run e2e` → **4 passed** (case-switch, security, upload, walking-skeleton). 
- Live `uv run psychtool-server`:
  - Upload before confirmation → 409 `confirmation_required`.
  - Confirming twice writes only 1 audit row.
  - .md upload works (2 passages); same id again → v2, v1 unchanged.
  - 11 MiB → 413 `too_large`; .pdf / .png → 400 `scan_not_supported`; non-UTF-8 → 400 `not_utf8`; .docx → 400 `unsupported_type`. Material, passage and audit counts are unchanged after every rejection.
  - The marker is in neither the audit rows nor the logs.
- Live catch-all check:
  - The real `main()` with one store method forced to raise an exception carrying a marker → response `500 {"detail":"internal error"}` with the CSP header.
  - The log has only `unhandled error: RuntimeError`, with no marker and no Traceback.
  - Control run with the uvicorn filter removed: the marker and the Traceback both appear, which proves the filter is what stops them.

## 2026-11-24 16:42 CST — PT-04 review answers from Alex, and PT-05 supervisor verification (GROK-35)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with three follow-up rounds after the step limit was hit. The deepseek-flash fallback was not triggered.

### Alex's answers to the 2 PT-04 questions (2026-11-24)

1. **Oversized uploads:** rejecting an oversized body before it is received (instead of spooling it and then returning 413) is a separate task. Not in PT-05.
2. **Tracebacks in dev:** yes to a dev-only switch that logs full tracebacks. It is off by default and never allowed with real data. **Done in PT-05:** `PSYCHTOOL_DEBUG_TRACEBACKS=1` works only in the synthetic tier; with `PSYCHTOOL_DATA_TIER=real` the server refuses to start (exit 2), and `create_app` forces it off.

### Supervisor direct fixes and review changes

- Fixed a `return ... from exc` syntax error and a docstring typo left by the worker.
- The JSON workspace import kept renumbering passages after a block, which would have pointed claims at the wrong passages. It now keeps the original passage ids, and rejects the whole import if a claim quotes protected text or cites a blocked passage.
- The egress re-screen skipped refs it could not load (fail-open). Any load or check error now refuses the prepare.
- Identifier findings are now computed over the kept paragraphs only.
- Found in review: the CLI `psychtool import` command wrote to the JSON material store without the screen. The screen now runs inside `workspace.import_material`, which covers the CLI and the eval harness. The CLI prints a held-back line, or exits 1 with nothing written.
- `fixtures/adolescent-background.json`: the synthetic sentence "本资料没有提供测验分数、诊断或常模资料。" matched the keyword list (a false positive of keyword matching). It now reads "…或标准化比较资料。" Meaning unchanged.

### Verification (fresh clone)

- `uv run --extra dev pytest -q` → **534 passed**; `bun test` → **120 pass / 0 fail**; `bun run build` → ok; `bun run e2e` → **5 passed** (new: `R13-AC1 norm table paragraph is held back`).
- Mutation checks: with the keyword check disabled, 6 R13 tests fail; with the real-tier refusal removed, the switch test fails; with the screen removed from `workspace.import_material`, the 3 CLI tests fail.
- Live CLI: `psychtool import` of a file with a "Scoring key: …" paragraph → exit 0 and a held-back line, with the text absent from the stored JSON. An all-blocked file → exit 1, no material file.
- Live `psychtool-server` (synthetic):
  - An upload with a "Norm table: …" paragraph → 200, `blocked_paragraphs: 1`, the plain reason shown. Only the 2 normal paragraphs are stored; the blocked text is in neither the DB dump, the response nor the log. One `material.protected_blocked` audit row (count 1 + sha256), and the chain verifies.
  - "normal / Normally / 常规" → nothing blocked. All paragraphs blocked → 400 `protected_content`, no material. Paste is filtered the same way.
  - Checker forced to raise → 503 `protected_check_failed`; material, passage and audit counts are unchanged.
- Live traceback switch (one store method forced to raise a marker):
  - Default → 500 and only `unhandled error: RuntimeError`; no marker, no Traceback.
  - `=1` → a startup warning, and the Traceback and the marker are logged.
  - `=yes` → off.
  - `=1` with `PSYCHTOOL_DATA_TIER=real` → refuses to start, exit 2, no DB file created.

## 2026-11-24 17:19 CST — PT-05 review answers from Alex, and PT-06 supervisor verification (GROK-36)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with two follow-up rounds after the step limit was hit. The deepseek-flash fallback was not triggered. The sandbox worktree had no synced `.venv` and no `node_modules`, so the supervisor ran `uv sync --extra dev` and `bun install --frozen-lockfile` there (offline cache).

### Alex's answers to the PT-05 questions (2026-11-24)

1. **Traceback switch with real data:** keep the server-wide refusal (`PSYCHTOOL_DATA_TIER=real` + `PSYCHTOOL_DEBUG_TRACEBACKS=1` → exit 2). Later, the switch is to be forced off whenever **any** real data exists, not decided per case.
2. **Fixture wording** (…或常模资料 → …或标准化比较资料): OK.
3. **Whole-prompt R13 check on the JSON/CLI egress path:** OK.
4. **HTTP codes:** 400 `protected_content` and 503 `protected_check_failed` are OK.
5. **Added scope, done in PT-06:** NFKC normalization before R13 matching, everywhere the check runs; stored text stays original. No spaced-letter detection, and over-blocking such as "no norm data provided" is accepted.

### Supervisor review changes

- **Sentence splitting:** the ported prototype regex cut sentences at "a.m." ("until about 1 a" / "before falling asleep"). A "." now ends a sentence only when it is followed by whitespace and doesn't come after a known abbreviation (a.m., p.m., Dr., Mr., e.g., …). Decimals like "7.5" stay inside the sentence.
- **Minimum length:** the prototype's 6-character minimum dropped short Chinese sentences (e.g. "他周末会补觉"). Quotes that contain CJK now need 4 characters.
- **Performance (found in review):** evidence extraction was quadratic. 8,000 paragraphs took 1.5 s, and about 100k paragraphs (9 MB, under the upload limit) didn't finish in 2 minutes. There is now a per-material passage index, and the abbreviation check no longer copies the text before each dot. A perf guard test was added. Live: an 8.7 MB upload gives `/evidence` 190,000 items in 3.4 s.
- **Scroll e2e (added by the supervisor):** the R4-AC2 test now uses a 41-paragraph material, so the highlight is only in view if the panel scrolled. It was confirmed failing with `scrollIntoView` removed and passing with it.

### Verification (fresh clone)

- `uv run --extra dev pytest -q` → **583 passed**; `bun test` → **129 pass / 0 fail**; `bun run build` → ok; `bun run e2e` → **7 passed** (new: 2 evidence tests covering R4-AC1/AC2/AC3).
- Mutation checks:
  - NFKC removed → 5 R13 tests fail.
  - Span check bypassed → the dropped-candidate test fails.
- Live `psychtool-server` (synthetic):
  - "Ｎｏｒｍ ｔａｂｌｅ: raw 12 = T 55." was held back.
  - The kept full-width paragraph ("ＡＢＣ school note, normal day. 他周末会补觉。") is stored as uploaded, not normalized.
  - `GET /evidence` → 7 items, each with quote == passage[start:end]; this includes "Dr. Lee…", "7.5 hours", the "1 a.m." sentence, a CJK sentence and a sentence after an emoji (code-point offsets).
  - Case B's text is not in case A's evidence; row counts are unchanged after the GET; an unknown case → 404; no material text in the log.

## 2026-11-24 18:15 CST — PT-06 review answers from Alex, and PT-07 supervisor verification (GROK-37)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with three follow-up rounds. The deepseek-flash fallback was not triggered. The supervisor provisioned `.venv`/`node_modules` in the sandbox worktree and ran Playwright outside it.

### Alex's answers to the PT-06 questions (2026-11-24)

1. **Persist evidence:** evidence is stored (schema v5 `evidence` table) instead of recomputed on every request. Each item has a stable id derived only from its location (case, material, version, passage, start, end), so her category and role choices survive later changes to the extraction or category rules. `test_correction_survives_rules_change` covers it.
2. **Sentence evidence as the only source** (paragraph claim suggestions cite evidence ids; the parallel paragraph path removed): **deferred, not done in PT-07.** It changes the claims model and schema (claims FK, egress lineage, the walking-skeleton e2e and about 7 test files), which is outside this card's categories/reasons/roles scope. Flagged for WBPM to track as its own card. Claims are unchanged.
3. **Pagination:** waits for PT-10; not added.
4. **English-only abbreviation list:** fine for M1; unchanged.

### Supervisor review changes

- After her correction the item still showed the rule's reason next to her chip. It now shows "You chose this category." / "You chose this source role."; the rule's reason stays in `suggested_*_reason`.
- `GET /evidence` ran one material query per item (N+1, 190k queries for a 9 MB upload). `paragraph` now comes from a JOIN on passages, and ordering follows passage position (the passage-id string sorted "p1000" before "p999").
- `refresh_evidence` preloads existing rows per material; import-triggered refresh covers only the imported material. 50k-paragraph perf guard added (refresh 1.5 s, list 0.5 s in the sandbox).
- GET no longer reports `dropped` (it would have been an in-memory recount); only `POST /evidence/refresh` does. e2e fixes: re-select the case after reload; read `dropped` from refresh.

### Verification (fresh clone)

- `uv run --extra dev pytest -q` → **658 passed**; `bun test` → **140 pass / 0 fail**; `bun run build` → ok; `bun run e2e` → **10 passed** (new: 3 category tests for R5-AC1, R5-AC2 and correction across reload/refresh).
- Mutation checks (each made the named tests fail):
  - categorize always returns uncategorized → 26 tests;
  - refresh overwrites her category → 5, including the rules-change correction test;
  - unstable id → 6, including `test_stable_id_depends_only_on_location`;
  - superseded rows deleted → 2;
  - rule reason shown after her choice → 2.
- Live `psychtool-server` (synthetic):
  - "Teacher says he reads slowly in class" → Development & school, role School, each with a reason quoting "Teacher";
  - "The weather was cloudy that week" → Uncategorized / To confirm with the fixed no-guess reasons;
  - a PUT correction (Other, Clinician) survived refresh with the same id;
  - bad key / extra field → 400; cross-case or unknown id → 404;
  - GET writes nothing; refresh with no change writes no audit row; audit rows hold ids and counts only, no text; case B text is not in case A; no material text in the log;
  - a 4.9 MB, 80,000-paragraph upload took 7.8 s including extraction, and GET returned 80,000 items in 1.9 s.
- G-Stack review additions (supervisor, written directly because the Workhorse MCP was unavailable after a box restart):
  - `test_import_survives_failed_auto_extraction`: a failed auto-extraction keeps the material; the log holds only the exception type; a later refresh recovers.
  - `test_refresh_route_reports_dropped`: a forged non-verbatim candidate is counted as dropped and not stored.
  - Each test was confirmed red under its mutation (try/except removed; `dropped` forced to 0).

## 2026-11-24 23:20 CST — PT-08 dimension mapping (GROK-38 / R7)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with four follow-up rounds. The deepseek-flash fallback was not triggered. The supervisor provisioned `.venv`/`node_modules` in the sandbox worktree, ran Playwright outside it, and made small direct fixes (v4 fixture INSERT, genuine v5→v6 migration test, e2e case re-select after reload, per-line split for dims lists so "Source: your list, paragraph n" points at the list line).

### Alex's PT-07 answers folded in

3. **Audit rows record the value she picked:** allowlisted values only, never her text. Schema v6 adds `audit_log.value`. `evidence.categorize` stores a CATEGORY_KEYS key or `reset`; `evidence.set_role` stores a ROLE_KEYS key or `reset`; `evidence.set_dimension` stores `confirm` | `none` | `reset` | a `dim_[0-9a-f]{24}` id (the id, never the name). Anything else is rejected at the audit layer. Covered by `tests/test_dimensions_store.py`. Pagination still waits for PT-10. Sentence evidence as the only source remains GROK-51, not started.

### Scope delivered

- Dimension list upload (`kind=dims`), one list per case, comparison suggestions, the four hard rules from tech-design §4, and Needs review actions (Confirm / Change to… / Wrong, no dimension).
- Dimensions page matches the prototype (copy, grouping, chips, source highlights). Screenshot: supervisor compared `web/test-results/dimensions-page.png` to `cur.html` `pDims`/`dimRow`/`dimChip`.
- All nine R7 ACs have API tests (`test_r7_acN_*`) and e2e titles containing `R7-ACN` (AC7 is the API guard; AC1–AC6 plus Wrong-no-dimension are in Playwright).
- ADR 0016. R6 invalidation is PT-09; citecheck/draft filtering is PT-12.
- Follow-up: push CI (`ci.yml` on push) failed once on R7-AC5 because `setupCase` posted materials before the synthetic-confirmation request had landed (403). The test now waits for the confirmation notice to disappear, matching `upload.e2e.ts`. The pull_request CI run on the same head was already green.

## 2026-11-24 23:59 CST — PT-20 sentence evidence as the only source (GROK-51)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with two follow-up rounds (schema/migration, then suggestions/routes/lineage, then UI/e2e). The deepseek-flash fallback was checked first and was down (HTTP 524); it was not used. PT-09 was not started.

### Scope delivered

- Schema v7 adds the `claim_evidence` junction table (composite FKs block cross-case citation). `Claim` / `ClaimSuggestion` carry `evidence_ids`. A genuine v6→v7 migration links each existing claim to the active same-case, same-passage sentence evidence; superseded and cross-case rows are not linked; claims whose passage has no evidence get zero junction rows. Audit rows are not rewritten; the chain still verifies.
- `suggest_claims` emits one paragraph suggestion per passage that has stored active sentence evidence, citing those `ev_` ids (never empty). The parallel paragraph-only path is gone. `accept_suggestion` and `POST /claims` require at least one id and reject unknown or cross-case ids with a fixed message that does not reveal whether the id exists on another case.
- Egress `SourceRef` for kind=claim records the cited ids; they persist in `source_refs`. Protected-content screening also covers the cited evidence quotes.
- Intake suggestion cards show the cited ids (`data-testid="cited-evidence-ids"`). Walking-skeleton e2e asserts an `ev_` id is visible before accept.
- ADR 0017. R6 invalidation remains PT-09.


## 2026-11-25 11:42 CST — PT-09 one-step correction (GROK-39 / R6)

**Executor:** Grok Workhorse supervisor. The worker was kimi-for-coding (profile `default`), in one task with two follow-up rounds (store cascade + atomicity, then routes/toast payload, then UI/e2e). The deepseek-flash fallback was checked first and was up; it was not used. PT-10 was not started.

### Scope delivered

- When the effective displayed category or dimension actually changes, one SQLite transaction updates the evidence row and audit, returns citing verified/conflict-viewed claims to pending (text and evidence ids unchanged), returns approved sections that cite any claim built on that evidence to Needs review (saved text unchanged), and invalidates prepared/approved (not sent) egress requests that reference the evidence. Role-only writes, no-op writes, and confirming an already-displayed suggestion do not cascade. Schema stays v7.
- Both PUT routes return a structured `invalidation` (id lists + the exact English toast). The SPA renders that toast verbatim (`data-testid="correction-toast"`). Unsaved section editor text is never rewritten; an open approved section may only have its status pill updated.
- Tests: store atomicity (injected mid-transaction failure rolls everything back), toast 0/1/2+ counts, category reset when the effective label changes, approved sections and kind=claim-only egress on already-pending claims, API parity, bun helpers (toast + unsaved text not rewritten), and a Playwright e2e that types unsaved text, changes the cited category, checks the toast, and confirms the prepared request is invalidated.
- ADR 0018. Supervisor review findings (category-reset trigger; section/egress matching every citing claim) were fixed in chunk 2. Supervisor also fixed the e2e after the worker hit its step limit: accept the stored suggestion, share the Playwright DB path across runner and worker, mark the claim verified through CaseStore, seed sessionStorage so the egress panel can restore an API-prepared request, and only show the editor “Needs review” note when the open approved section actually flips.



## 2026-11-25 12:39 CST — PT-10：三欄工作區、GitBook 主題、來源卡（GROK-40 / R8）

**執行模型**：chunk 1 為 kimi-for-coding via Grok Workhorse；kimi 觸及週配額後，chunk 2 改走 deepseek-v4.1-flash-1017（其後 HTTP/2 GOAWAY）。chunk 3（對比、截圖、e2e、文件）由 supervisor 在同一工作樹完成。

### 變更

- `_r6_invalidation_toast` 中段永遠寫出回到 Needs review 的段落數（含「0 sections were returned to Needs review.」）；開頭／結尾不變；不再使用 “Nothing else needed to be updated.” 陳述與 egress 句仍只在數量非零時出現。對應測試已更新。
- 三欄工作區（`256px minmax(0,1fr) minmax(340px,0.66fr)`，1280／1024 收合）與 GitBook 主題 token（`--paper #FFFFFF`、`--ink #1D1D1D`、`--accent #E8460F`、`--accent-ink #C42A00` 等）移植自原型。隱私橫幅為 ink 底白字；主按鈕用 accent-ink 以達文字 4.5:1；表單邊框用 `--ctl`（≥3:1）。OFL Proto Sans／Mono 以 `'self'` 字體檔嵌入。
- 右欄來源卡（R8）：點證據或已引用陳述顯示原文範圍、材料／版本、角色、是否未確認；中欄編輯器保持可見、無彈窗。位置列只由真實欄位組成（1-based 閉區間顯示半開的碼位偏移）；絕不編造頁碼。不移植 Export（Q7）。
- 新增 `docs/adr/0019-r8-three-column-workspace.md`；三份 README 各加一行。對比腳本與原型基線納入 `web/scripts/contrast.js`、`web/e2e/prototype/`、`web/e2e/baselines/`。
- 測試：bun `source-card.test.tsx`、`export-ui.test.ts`；Playwright `workspace.e2e.ts`（R8 + Q7）、`contrast.e2e.ts`、`visual.e2e.ts`（1440／1280／1024，遮罩可變內文與原型匯出控制，工作閾值 5%）。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **798 passed**。
- `cd web && bun test` → **180 passed / 0 fail**。
- `cd web && bun run build` → 成功（含 6 個嵌入字體）。
- `cd web && bun run e2e` → **21 passed**（含既有套件）。對比：149 筆量測、**0 failures**，最低 3.69:1（表單邊框）。截圖差異（chrome／版面／主題，遮罩可變內文與原型 Export）：1440 **0.71%**、1280 **0.94%**、1024 **1.54%**，皆低於 5%。

### 未解決事項

- 截圖「約定閾值」在 PT-03–PT-09 筆記中沒有寫下數字；本 PT 以 5% 為工作閾值，若另有約定需再對齊。
- 未開始 PT-11 或 GROK-53。


## 2026-11-25 17:55 CST — PT-11：章節編輯與保存（GROK-41 / R9）

**執行模型**：chunk 1–2 為 deepseek-v4.1-flash-1017 via Grok Workhorse（kimi 週配額已用盡）。chunk 3（一個主按鈕、e2e 修補、ADR／README／WORKLOG）由 supervisor 在同一工作樹完成。

### 變更

- 視覺回歸約定閾值改為每視窗 **2%**（`THRESHOLD = 0.02`；ADR 0019 同步）。不把 `tech-design.md` 加入倉庫。
- 臨床者專屬章節（`diagnostic_conclusion` / `recommendation`，本案為 Clinical Impressions 與 Recommendations）：`build_section_request_input` 在組 prompt 之前拒絕；準備 API 回固定 400。介面不畫模型請求面板，並提示「You write this」。她仍可勾選證據作為提示，但生成回呼不會寫入正文。
- 普通章節：生成結果以未保存狀態進入編輯區，來源陳述保持勾選。保存列顯示 Unsaved changes / Saved。切換章節不丟未保存文字；保存後刷新或再打開內容一致。
- 一個主按鈕：送出面板有可執行步驟時（Approve request / Send once）保存列退為次按鈕；否則可批准時主按鈕為 Approve section，有未保存修改時為 Save section。建立個案仍是次按鈕。不新增 Export。
- 新增 `docs/adr/0020-r9-section-editing-and-saving.md`；三份 README 各加一行。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **803 passed**。
- `cd web && bun test` → **194 passed / 0 fail**。
- `cd web && bun run build` → 成功。
- `cd web && bun run e2e` → **24 passed**。對比：137 筆量測、**0 failures**，最低 3.69:1。截圖差異：1440 **0.71%**、1280 **0.94%**、1024 **1.54%**，皆低於 2%。

### 未解決事項

- 未開始 PT-12、PT-22 或 GROK-53／PT-21。
- 句子級引用篩選（R9-AC1「每條事實性陳述應能指向所用證據」在本 PT 以章節上已勾選、可點開的來源陳述為準）。

## 2026-11-25 18:50 CST — PT-12：逐句核引用與 Summary 用語攔截（GROK-42 / R10）

**執行模型**：deepseek-v4.1-flash-1017 via Grok Workhorse（kimi 週配額仍用盡）寫了 citecheck 核心與 schema v8 初稿；supervisor 在同一工作樹補完測試、ADR 0021、API、句子編輯介面與 e2e。

### 變更

- 新增 `psychtool/core/citecheck.py`：逐句對本案證據做字面重疊引用；無出處標 Unverified；My judgment 不偽裝成材料事實。草稿過濾**拒絕、不改寫**。
- schema v8：`section_sentences` / `sentence_evidence`（外鍵帶 case_id）。v7→v8 只加表，不為舊列憑空造引用。
- Summary 含診斷或建議用語時 citecheck 標記 blocked，保存回固定 400。其他可模型起草的章節套用 R7-AC6/8（診斷用語、未上傳的標準編號／手冊片段）。臨床者專屬章節不套用此過濾。
- `POST .../sections/{id}/citecheck`：只註記、不寫庫；blocked 仍為 200。
- 介面：無出處句波浪下劃線與「Unverified · no source found」標籤；可標為 My judgment；引用角標可打開來源卡。標記保存後仍在。
- 新增 `docs/adr/0021-citecheck-and-summary-guard.md`；三份 README 各加一行。未做 Export、PT-22、PT-21、PT-13。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **828 passed**。
- `cd web && bun test` → **205 passed / 0 fail**。
- `cd web && bun run build` → 成功。
- `cd web && bun run e2e` → **27 passed**。對比：137 筆量測、**0 failures**，最低 3.69:1。截圖差異：1440 **0.71%**、1280 **0.94%**、1024 **1.54%**，皆低於 2%。

### 未解決事項

- 未開始 PT-22、PT-21 或 PT-13。
- Export（M2／Q7）仍不做；Unverified 標記以保存為準。
- Fake transport 仍回傳固定占位文字（各句皆為 Unverified）；引用命中由單元測試與含本案證據原文的草稿覆蓋。

## 2026-11-25 19:30 CST — PT-12 後續：citecheck 失敗保留草稿、假傳輸引用句、加寬 Summary 建議攔截

Alex 批准 PT-12 並要求三項跟進，寫在同一分支、同一 PR #14，目標仍是 main。

### 變更

- Send once 成功後若 citecheck 因傳輸錯誤或 5xx 失敗，生成正文保留為未保存草稿，全部標 Unverified，並顯示錯誤；不丟字。用語攔截仍走 200 `blocked` 路徑，不落地違規草稿。
- 假傳輸在信封含 `<source_material>` 時回一句引用原文、一句無出處句（仍帶 FAKE OFFLINE RESPONSE 標記），讓 e2e 能點 `[n]` 打開來源卡，並看到無出處句的 Unverified 標記。提取時忽略提示詞裡對該標籤的提及。
- Summary 建議用語改為詞幹（recommend / advis / suggest / refer）與句式（should be / should receive / should undergo / should consider）。仍拒絕並回 400，絕不剝除或重寫。ADR 0021 將詞表標為待心理師驗證（待验证）。「the results suggest」「referred by her school」「should be noted」目前都會被攔下，測試記錄此行為，未為迴避誤傷而放寬規則。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **835 passed**。
- `cd web && bun test` → **208 passed / 0 fail**。
- `cd web && bun run build` → 成功。
- `cd web && bun run e2e` → **29 passed**。對比：137 筆量測、**0 failures**，最低 3.69:1。截圖差異：1440 **0.69%**、1280 **0.92%**、1024 **1.57%**，皆低於 2%。
- 突變：拿掉失敗落地、讓假傳輸忽略信封、收窄建議攔截，對應測試皆轉紅。

### 未解決事項

- 未開始 PT-22、PT-21 或 PT-13。
- Export（M2／Q7）仍不做。
- 建議用語詞表待心理師驗證；上述三句誤傷候選未放寬。

## 2026-11-25 19:50 CST — PT-23：修正 Summary 建議用語攔截誤傷（GROK-55）

Alex 於 19:39 CT 將 #14 合入 main（merge f92340f）。本卡只做兩處修正，Python 與 TypeScript 守衛同步，拒絕仍回 400，絕不改寫。

### 變更

- 恢復攔截字面短語 “treatment plan”。
- 將 `refer` 從光禿詞幹收窄為轉介用語：`refer to`、`refer her/him/them to`、`refer … to/for`（中間最多三詞）、`referral to/for`、`should be referred`、`referred to/for`。因此 “for reference”“the reference group”“referred by her school” 可以通過。
- 不改動 “the results suggest”“should be noted”“advisory”“suggestion”；ADR 0021 將這四類標為待心理師驗證（待验证）。

### 實際核驗結果

- `.venv/bin/python -m pytest -q` → **855 passed**。
- `cd web && bun test` → **226 passed / 0 fail**。
- `cd web && bun run build` → 成功。
- `cd web && bun run e2e` → **29 passed**。截圖差異：1440 **0.69%**、1280 **0.92%**、1024 **1.57%**，皆低於 2%。
- 突變：拿掉 “treatment plan”；把 `refer` 改回光禿詞幹（Python 與 TS）——對應測試皆轉紅。

### 未解決事項

- “the results suggest”“should be noted”“advisory”“suggestion” 仍待心理師驗證。
- 未開始 PT-22、PT-21 或 PT-13。

## 2026-11-25 20:25 CST — PT-13：Vertex AI Gemini 適配器（GROK-43 / R11）

Alex 於 20:00 CT 將 #15 合入 main（merge a3e0c5b）並批准本卡。Workhorse 的 kimi 與 deepseek-flash 均在 0 回合停滯後取消；由 supervisor 依同一 brief 完成。

### 變更

- 新增 Vertex AI Gemini 輸送層（OpenAI 相容 `/chat/completions`，stdlib urllib）。權杖只來自 `PSYCHTOOL_VERTEX_ACCESS_TOKEN` 或測試注入的 `token_provider`，不探測 ADC。
- 命名設定檔 `fake` / `vertex` / `real`。Google AI Studio / Gemini Developer API 主機在 `vertex` 與 `http` 輸送層一律拒絕。
- `real` 檔（無 BAA 開關）拒絕非本機端點；測試以 socket egress guard 證明零出網。本機回環仍可依 ADR 0003 經人工批准。
- 外發預覽標題改為「De-identified preview — exact model input」。ADR 0022 記錄上述決定與即時 Vertex 呼叫所需條件。

### 驗證（本機工作樹）

- `pytest -q`：875 passed。
- `cd web && bun test`：226 pass / 0 fail。
- `bun run build`：通過。
- `bun run e2e`：29 passed；截圖差異 1440 0.69%、1280 0.92%、1024 1.57%（皆低於 2%）。
- Walking-skeleton e2e 以 FakeTransport 完成合成檔即時檢查（Prepare → 去標識預覽 → Approve → Send once → 未存草稿）。
- Mutation：hash binding、成功後不可重發、AI Studio 拒絕、`real` 檔雲端出網拒絕，均殺掉對應測試。

### 未解決事項

- 未做即時 Vertex「用 A-001 真生成一章」：需要 Google Cloud 專案、區域、型號與驗證方式（例如安全密鑰中的短期權杖或日後的 ADC）。
- 未開始 PT-21、PT-22 或 PT-14。

## 2026-11-25 21:10 CST — PT-14：啟動器與錯誤文案（GROK-44 / R1-AC3 + R16）

Alex 於 20:52 CT 將 #16 合入 main（merge a38a2a0）並批准本卡。Workhorse 的 kimi（0 回合）與 deepseek-flash（2 回合後停滯約 4 分鐘）均取消；由 supervisor 依同一 brief 完成。既有 Workhorse 金鑰未改。未做即時 Vertex（改期 PT-24）；未改 ADR 0003 的本機回環規則。

### 變更

- 新增 `launchers/Start Psychtool.command`（macOS）與 `launchers/Start Psychtool.cmd`（Windows）：雙擊後啟動本機伺服器並打開瀏覽器。形式為無額外依賴的腳本（ADR 0023）。
- 服務未起、斷網（Q5）、保存失敗（Q5）三條文案為常數，並有位元組級測試。保存失敗後編輯區文字保留（e2e）。空個案提示不再出現命令列或工作目錄說明。可見狀態文字不再使用「API」。
- 即時 Vertex「生成一章」與 PT-21、PT-22、PT-24 均未開始。

### 未驗證

- 未在真實 Finder 或檔案總管中雙擊；未驗證 macOS Gatekeeper／隔離屬性；未驗證 Windows SmartScreen。未增加 windows/macos CI 矩陣。

### 驗證（本機工作樹）

- `pytest -q`：883 passed。
- `cd web && bun test`：236 pass / 0 fail。
- `bun run build`：通過。
- `bun run e2e`：32 passed（含 3 條 error-copy）；截圖差異 1440 0.69%、1280 0.92%、1024 1.57%（皆低於 2%）。
- Mutation：斷網文案、保存失敗文案、服務未起文案的逐字測試，以及「保存失敗後清空編輯區」的 e2e，均殺掉對應測試後還原。
- Linux 啟動器腳本測試（假的健康檢查與記錄打開的 URL）通過。未做真實 Finder／檔案總管雙擊、Gatekeeper 或 SmartScreen。

---

## 2026-11-25 21:27 CST — PT-15：M1 驗收（GROK-45）

Alex 於 21:15 CT 將 #17 合入 main（merge 3a925cc）並批准本卡。Workhorse 在 PT-13 與 PT-14 已連續三次停滯（kimi 0 回合；deepseek-flash 思考中掛起）；本卡未再等待第四次停滯，由 supervisor 依同一 brief 完成。既有 Workhorse 金鑰未改。未做即時 Vertex（改期 PT-24 / GROK-56）；未改 ADR 0003 的本機回環規則；未開始 PT-21、PT-22、PT-24。

### 變更

- 從 PRD R1–R16 的 Given/When/Then 子彈自行點算：共 48 條 AC，其中 R12×3 與 R14×3 屬 M2，M1 範圍 42 條，與 ticket / tech-design §7 一致。
- 新增驗收報告 `docs/m1-acceptance-report.md`：每條 AC 一列（ID、需求、M1 或 M2、證明測試、結果）；R7 內部驗收清單；NOT VERIFIED（真實雙擊／Gatekeeper／隔離屬性／SmartScreen、即時 Vertex、所有待验证项）。報告內每項主張都連到測試、CI 或 commit。
- 新增合成資料抽查腳本 `scripts/spotcheck.py`（實作於 `psychtool/acceptance/spotcheck.py`）：列印 10 項 pass/fail，不寫報告匯出，不是 PRD 第 5 節仍待同意的產品成功門檻。
- R15 補測：`tests/test_privacy_copy.py`、`web/e2e/privacy.e2e.ts`（橫幅在工作頁／上傳／貼上面板可見；介面不得聲稱 HIPAA 合規）。
- 矩陣與報告由 `tests/test_m1_ac_matrix.py` 鎖定（48 / 42 / 6，每個 M1 列都有真實測試名稱）。
- 三份 README 與本 WORKLOG 已更新。

R3-AC1、R10-AC2 中的匯出子句因 Q7 在 M1 不可行使；已證明隔離與 Unverified 保存後仍在，並記錄介面沒有 Export 入口。未把 M1 掃描拒絕當成 R12 M2 AC 通過。

### 未驗證

- 未在真實 Finder 或檔案總管中雙擊；未驗證 macOS Gatekeeper／隔離屬性；未驗證 Windows SmartScreen。未增加 windows/macos CI 矩陣（Alex 將自行嘗試真實雙擊）。
- 未做即時 Vertex「生成一章」（改期 PT-24 / GROK-56）。
- 待心理師裁定的待验证项（含 ADR 0021 詞表與「the results suggest」「should be noted」「advisory」「suggestion」誤傷，以及 tech-design §7 服務未起文案）見報告 NOT VERIFIED。

### 驗證（本機工作樹）

- `pytest -q`：890 passed。
- `cd web && bun test`：236 pass / 0 fail。
- `bun run build`：通過。
- `bun run e2e`：33 passed（含新增 privacy e2e）；截圖差異 1440 0.69%、1280 0.92%、1024 1.57%（皆低於 2%）。
- 抽查腳本：10 passed, 0 failed。
- Mutation：矩陣測試名稱打錯、App.tsx 加入「is HIPAA compliant」、抽查種子插入編造摘錄，均使對應測試失敗後還原。
- 全新 clone（`0ceba7d`）：pytest 890 passed；bun test 236 pass；build 通過；e2e 33 passed，截圖差異同上；抽查腳本 10 passed。
- 後續：抽查腳本結束後還原 `PSYCHTOOL_*` 環境變數（避免污染同進程測試）；pytest 891 passed。
- CI（`cd2abb7`）綠：push https://github.com/alexxhchen-nu/psychtool/actions/runs/45749449296 ；pull_request https://github.com/alexxhchen-nu/psychtool/actions/runs/45749454118 。

---

## 2026-11-27 12:06 CST — PT-24：即時 Vertex 章節檢查（GROK-56）

Alex 今日批准本卡。PR #18（PT-15）已合入 main（merge 4a3d57f）。本分支自最新 origin/main 拉出。Workhorse（default / MiniMax-M3.1-Flash）於約 5 分鐘超時前寫出核心模組與 29 項離線測試，但未來得及補 ADR／README／WORKLOG，且因本機同時切了功能分支被標為 integrity_violation；由 supervisor 審閱、修補並補齊文件後完成。從未對 Vertex 或 Gemini 發出即時呼叫，未尋找或使用任何 Google Cloud 憑證，未開始 PT-21／PT-22。ADR 0022 的 `real` 檔拒絕與「不探測 ADC」規則未改。

### 變更

- 新增獨立、雙重選擇加入的本機路徑（ADR 0024）：須同時有 `PSYCHTOOL_LIVE_VERTEX=1` 與 `--opt-in`；`profile` 或 `data_tier` 為 `real` 時即使選擇加入也拒絕；只使用合成夾具 `fixtures/case_a001`。
- 命令：`uv run --extra live psychtool-live-vertex --opt-in`（亦有 `scripts/live_vertex_chapter.py` 與 `psychtool live-vertex-chapter`）。驗證走 Application Default Credentials；可選 extra `live`（`google-genai>=2.34.0`），CI 不安裝、不執行即時呼叫。
- 預設模型 `gemini-4-hydrogen`（官方 GA ID）、專案 `fb-ailogic26vrt-3252`、區域 `global`，皆可由環境變數或旗標覆寫。產出套用既有 citecheck 與用語攔截，並列印 cited／uncited、攔截結果、token 與費用估計。
- 費用估計取自官方 Model Garden 定價頁的 Standard PayGo Global 標價（輸入 1.50／輸出 7.50 美元每百萬 token，2026-11-27 查閱）；其他模型或區域標為 unknown。
- 離線測試 `tests/test_live_vertex_chapter.py`（29 項）：設定解析、雙重選擇加入、`real` 拒絕仍成立、摘要算術、攔截與引用被套用。既有 Vertex 輸送層仍不探測 ADC。
- 三份 README（含 Windows：安裝 gcloud、ADC login、PowerShell 與 cmd 設環境變數、一條命令）與本 WORKLOG 已更新。

### 未驗證

- 以真實 ADC 對 Vertex 發出「生成一章」的呼叫本身，須由 Alex 在其 Windows 電腦上自行執行。本卡與 CI 均未發出該呼叫。

### 驗證（本機工作樹）

- `pytest -q`：920 passed（main 上 891，加上 29 項離線 live-chapter 測試）。
- `cd web && bun test`：236 pass / 0 fail。
- `bun run build`：通過。
- `bun run e2e`：33 passed；截圖差異 1440 0.71%、1280 0.94%、1024 1.54%（皆低於 2%）。
- 抽查腳本：10 passed, 0 failed。
- Mutation：去掉環境旗標閘門、把費用分母改為 1_000，對應測試均失敗後還原。

---

## 2026-11-27 12:25 CST — PT-24 補充：章節輸出檔與費用／大小上限（PR #19）

Alex 批准在同一 PR 上補充兩項，不合併。仍未對 Vertex 或 Gemini 發出即時呼叫，未尋找或使用任何 Google Cloud 憑證。

- 生成的章節文字（僅合成 A-001）寫入本機檔案，並列印絕對路徑。預設 `local-data/live-vertex/case-a001-history.txt`（已 gitignore）；可用 `--output` 或 `PSYCHTOOL_LIVE_VERTEX_OUTPUT` 覆寫。倉庫內未被忽略的路徑會被拒絕。
- 新增可設定的 `max_output_tokens`（預設 8192）與請求逾時（預設 120 秒），並傳入 google-genai。摘要列出呼叫前依上限估算的最壞費用，以及實際 usage 的費用。截斷或逾時為 FAIL，但仍對已收到的文字套用引用與攔截。SDK 重試次數設為 1，以免預設 5 次嘗試放大上限。
- 離線測試已覆蓋上限接線、輸出檔寫入、截斷與逾時。Mutation：拿掉 `sdk_generate_config` 的 `max_output_tokens`、把寫入改為空字串，對應測試均失敗後還原。
- 三份 README（Windows 步驟改為在已完成 ADC 登入後，從克隆或更新本分支開始）與 ADR 0024 已更新。
