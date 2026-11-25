# ADR 0011：本地安全基線（loopback、工作階段權杖、CSP、啟動自檢）與僅附加稽核日誌

日期：2026-11-24。狀態：已確認（PT-03 / Linear GROK-33）。

## 決策

為 `psychtool-server` 建立本地安全基線，並把稽核日誌做進 SQLite 個案庫（schema v2）：

1. **僅綁定 loopback**：`main` 只允許 `127.0.0.1` / `localhost` / `::1`；`PSYCHTOOL_HOST` 指向非 loopback 時以 exit 2 拒絕啟動。
2. **每次啟動一組工作階段權杖**：`create_app(session_token=None)` → 顯式參數 → `PSYCHTOOL_SESSION_TOKEN`（≥32 字元，供 Vite dev proxy 使用）→ `secrets.token_urlsafe(32)`。所有 `/api/*`（除 `GET /api/health`）要求 `X-Psychtool-Token`（`compare_digest`）；SPA index.html 由伺服器注入 `<meta name="psychtool-session">` 並帶 `Cache-Control: no-store`；前端 `api.ts` 讀一次後快取，附在每個 API 請求上。權杖值永不進日誌（只記錄來源）。
3. **Host 檢查**：所有請求（API 與 SPA）的 Host hostname 部分必須是 loopback，否則 400——擋 DNS-rebinding。
4. **嚴格 CSP 與安全標頭**：每個回應都帶 `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`，以及 `nosniff` / `no-referrer` / `X-Frame-Options: DENY`。`web/dist/index.html` 無內聯 script/style，與此 CSP 相容（e2e 斷言頁面載入無 CSP 違規）。
5. **啟動自檢（`run_self_checks`）**：逐項記錄 `self-check <name> <status>: <detail>`——bind、token 來源、host-check、csp、data-dir（位於雲端同步資料夾即拒絕啟動；整段路徑元件比對，`Dropboxed-notes` 不誤判）、disk-encryption（FileVault / dm-crypt / BitLocker，僅警告不阻擋）、audit-chain（驗鏈，斷鏈大聲警告但不阻擋）、send-lock-recovery（回報回收筆數）。
6. **錯誤回應固定文案**：HTTPException 的 `detail` 不再回傳 `str(exc)`（例外訊息可能引用使用者文字），一律用固定字串（`"invalid section"`、`"unauthorized"` 等）。
7. **僅附加稽核日誌（S6）**：`audit_log` 表與狀態變更同一交易寫入（`claim.accept` 在 claim insert 的 store 方法內；`egress.prepare`／`approve`／`invalidate`／`send` 在 `save_egress_request` 偵測 status 變更時、於保存狀態的同一交易內）；`BEFORE UPDATE/DELETE` trigger 阻擋修改；`entry_hash = sha256(canonical JSON of case_id,ts,action,object_type,object_id,content_hash,destination,prev_hash)` 形成創世向前的鏈，`verify_audit_chain` 偵測繞過 trigger 的竄改。writer 結構性拒絕自由文字：action/object_type/destination 白名單、object_id 僅限識別符形狀（允許 token_urlsafe 可能產生的 `-`/`_` 開頭）、content_hash 僅限 64 hex。

## 理由

- **SQLite 表而非 JSONL sidecar**：狀態變更與稽核列必須同生共死——一個交易提交兩者，crash 不可能留下只有其中一邊的狀態。JSONL sidecar 做不到這一點（兩個檔案、兩次 fsync，順序永遠有窗口）。
- **Trigger + 雜湊鏈雙層**：trigger 擋應用路徑的 UPDATE/DELETE；雜湊鏈讓「有檔案存取權的人 drop trigger 後改列」可被偵測——鏈讓竄改*可被發現*，不是*不可能*。這正是 S6 對防護範圍的誠實聲明。
- **權杖走 meta tag 而非 cookie**：同源 SPA 不需要跨站攜帶；沒有 cookie 就沒有 CSRF 面；CSP `connect-src 'self'` 把外洩通道壓到最小。
- **雲端同步資料夾拒絕啟動**：Dropbox/iCloud 等會把資料庫複製到第三方伺服器，且同步衝突會弄壞 SQLite 檔案；這是資料邊界問題，不是設定偏好。磁碟加密只警告，因為偵測是 best-effort（遠端磁碟、加密容器會誤判），不該擋開發。
- **`send_interrupted` 而非「清鎖重送」**：crash 後無法知道 transport 是否已送出；fail-closed 的唯一誠實選項是終態 `send_interrupted`（永不可再送），使用者以新 request_id 重新 prepare。

## 出閘鎖的 crash 復原（fail-closed）

鎖 owner 格式為 `boot_id:pid:random`（`BOOT_ID` 每進程隨機）。啟動時 `recover_stale_send_locks` 對每個外來 boot id 的鎖：

- status `sent`：送達已完成、只丟了 unlock——清鎖、保狀態；
- 其他 status：標記 `send_interrupted`（終態；send 路徑檢查的是狀態而非鎖是否存在，因此**永不可能二次送出**）；
- 陳舊 transition lock 同樣清除；**本 boot 的 transition lock 絕不動**。

每筆復原在同一交易寫一列稽核（`egress.send_lock_recovered`；僅清 transition lock 時 `egress.transition_lock_recovered`）。每列的 UPDATE 以掃描時觀察到的 owner 為條件（`WHERE ... AND send_lock_owner IS ? AND transition_lock_owner IS ?`），掃描與交易之間被其他寫入者改動的列直接跳過、不寫稽核。復原冪等。

**單一寫入者假設**：server 是 SQLite 個案庫的唯一寫入者，因此外來 boot id 必然意味著前一個 server 進程已死，沒有需要保護的活 peer。若未來出現多寫入者部署，此假設必須重新審視。

## Schema v2 遷移

`user_version` 1 → 2：新增 `audit_log` 表與兩個 trigger，並**重建 `egress_requests`**——SQLite 無法修改 CHECK 約束，而 v2 的 status 集合新增 `send_interrupted`。重建採 SQLite 官方「修改表結構」程序：交易內 `PRAGMA defer_foreign_keys=ON`，建新表（含新 CHECK）→ 複製列 → drop 舊表 → rename，提交前 `PRAGMA foreign_key_check` 驗證無斷裂（有測試：PT-02 真實 v1 庫帶外來 boot 鎖，遷移後 recovery 能寫入 `send_interrupted`，`integrity_check` ok）。

## 稽核鏈格式

每列：`seq`（AUTOINCREMENT）、`case_id`、`ts`（UTC ISO8601）、`action`、`object_type`、`object_id`、`content_hash`（可空，64 hex）、`destination`（可空，白名單 `fake`/`http`）、`prev_hash`、`entry_hash`。

`entry_hash = sha256(json.dumps({case_id, ts, action, object_type, object_id, content_hash, destination, prev_hash}, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8"))`；創世列 `prev_hash = "0"*64`。

記錄的事件：`case.create`、`case.import_json`、`material.import`（sha256 of text）、`claim.accept`、`section.save`、`egress.prepare`、`egress.approve`、`egress.invalidate`、`egress.send`、`egress.output_blocked`、`egress.send_lock_recovered`、`egress.transition_lock_recovered`。

**事件與狀態同一交易**：`claim.accept` 由插入 claim 的 store 方法（`CaseStore.add_claim`）在同一交易寫入；`egress.prepare`／`egress.approve`／`egress.invalidate`／`egress.send` 由 `CaseStore.save_egress_request` 在偵測到 status 變更時、於保存狀態的同一交易寫入（同一狀態不重複寫）。`egress.send` 的 destination 由 server 在呼叫 `send_approved` 前設到 `case.audit_destination`（值即 `fake` 或 `http`，寫入時再過白名單）。因稽核寫入失敗而 rollback 時，狀態變更一併撤銷：**不可能留下沒有稽核列的狀態變更**。`sent` 的稽核寫入失敗會讓整個 `sent` 交易回滾、送出鎖保持持有（fail-closed），新 boot 的復原再把它轉成 `send_interrupted` 並補一列復原稽核。唯一仍在路由層的是 `egress.output_blocked`——它是事件而非狀態變更，稽核失敗只記固定字串日誌，不外洩例外文字。

## 防護範圍與限制

- 防：同機其他使用者的瀏覽器網頁呼叫本地 API（權杖）、DNS rebinding（Host 檢查）、惡意網頁讀取回應（CSP/SOP）、應用路徑竄改稽核（trigger）、有檔案權限的竄改被*發現*（雜湊鏈）、誤把資料庫放進雲端同步夾（啟動拒絕）。
- 不防：能讀取 SQLite 檔案本身的人（資料未加密）；擁有本機 shell 的人（可讀權杖、可 drop trigger 後重算整條鏈）；惡意網頁在同機瀏覽器內攜帶正確權杖（權杖只發給本機伺服器頁面，但同機惡意程式本就在威脅模型外）。本專案**尚未符合 HIPAA**；此基線是本地開發原型的一部分，不構成合規證明。

## 後果

- 開發模式：瀏覽器經 `psychtool-server` 供應的頁面自動帶權杖；Vite dev server 需要 `PSYCHTOOL_SESSION_TOKEN`（≥32 字元）同時設給後端與 `web/vite.config.ts` 的 proxy，否則 API 401。
- 測試以 `tests/conftest.py` 的 `build_client(app)`（loopback base_url + 預設權杖標頭）發請求。
- Playwright e2e 新增 `web/e2e/security.e2e.ts`：斷言頁面 CSP 標頭、載入與建案全程無 CSP console 違規、無權杖的 `page.request` 得 401。
- `send_interrupted` 貫穿前後端：`EgressStatus`、`egress-state` 的 terminal phase、UI 標籤「Send interrupted — prepare a new request」；前端永不允許對其 send。
