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
