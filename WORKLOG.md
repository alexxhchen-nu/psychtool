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

## 2026-11-24 16:20 CST — PT-03 review answers from Alex, and PT-04 supervisor verification

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
