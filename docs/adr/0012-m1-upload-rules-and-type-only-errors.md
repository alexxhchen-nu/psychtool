# ADR 0012：M1 上傳規則（僅 .txt/.md、分類拒絕、無 OCR）與僅記錄例外型別的錯誤處理

日期：2026-11-24。狀態：已確認（PT-04 / Linear GROK-34）。

## 決策

為伺服器端檔案上傳（`POST /api/workspaces/{case_id}/materials`）與未捕捉例外建立規則：

1. **M1 僅接受 .txt / .md**：伺服器路徑 `parse_server_upload` 只接受副檔名 `.txt`、`.md`（不分大小寫），上限 10 MiB（10,485,760 bytes；讀取 `MAX+1` bytes 即判定超標，不整檔讀入）。CLI 的 `parse_upload` 行為不變。
2. **分類拒絕、固定文案**：拒絕回應為 JSON `{detail, reason}`，`detail` 一律是白名單常數字串，永不引用檔名或內容——
   - `too_large`（413）："The file is too large. The limit is 10 MiB (10,485,760 bytes)."
   - `unsupported_type`（400）："Only .txt and .md files are supported. Upload a .txt or .md file."
   - `scan_not_supported`（400）："Scanned PDFs and images are not supported in this version. Upload a .txt or .md file."（R12：.pdf/.png/.jpg/.jpeg 一律走此固定說明；M1 伺服器端無 OCR）
   - `not_utf8`（400）："The file is not valid UTF-8 text. Save it as UTF-8 and try again."
   - `empty`（400）："The file contains no text."
   拒絕發生在寫入 store 之前：materials / passages / audit_log 筆數不變（無部分寫入）。
3. **每案一次的合成資料確認（R2-AC3）**：`cases` 表新增 nullable `synthetic_confirmed_at`（schema v3，v2 資料庫以 `ALTER TABLE` 遷移，既有列為 NULL＝未確認）。未確認的個案上傳回 409 `{reason: "confirmation_required"}`；`POST /api/workspaces/{case_id}/synthetic-confirmation` 為 set-once（`UPDATE ... WHERE synthetic_confirmed_at IS NULL`），只有第一次真的改變狀態時才在同一交易內寫一筆 `case.confirm_synthetic` 稽核列；貼上文字路徑帶 `synthetic_confirmed: true` 時亦視為確認（同一 set-once 模式）。前端在首次上傳前顯示告知、要求勾選並確認，確認前表單停用。
4. **捕捉全部例外的 500 處理器**：`@app.exception_handler(Exception)` 回固定 `{"detail": "internal error"}`，`psychtool` logger 只記 `unhandled error: <例外型別名>`——`str(exc)` 與 traceback 可能引用請求或材料文字，永不入日誌。
5. **uvicorn traceback 壓制**：Starlette 的 ServerErrorMiddleware 在呼叫 500 處理器後仍會 re-raise，uvicorn 的 `run_asgi` 於是對 `uvicorn.error` 記 `logger.error("Exception in ASGI application", exc_info=True)`——完整 traceback 會上 stderr。`main._uvicorn_log_config()` deep-copy 已安裝 uvicorn 的 `LOGGING_CONFIG`，沿 `uvicorn.error` → `uvicorn` 找到最近一層有 handler 的 logger，把 `UvicornErrorTraceFilter` 掛上其 handler；filter 把帶 `exc_info` 的 record 改寫為僅含型別名並清掉 `exc_info`/`exc_text`，再交給 formatter。
6. **錯誤回應也帶安全標頭**：ServerErrorMiddleware 送 500 時走原始 `send`，會繞過所有 `add_middleware` 的使用者中介軟體；因此 `create_app` 在建成中介軟體堆疊後再外包一層純 ASGI 的 `SecurityHeadersASGIMiddleware`（在 `http.response.start` 上注入標頭），使固定 500 同樣帶 PT-03 的 CSP/nosniff 等標頭。

## 理由

- **拒絕文案白名單化**：上傳路徑的錯誤最容易把檔名（可能含姓名）或內容片段回進回應或日誌；唯一可靠的防線是「回應與日誌只由常數組成」。
- **確認狀態放 DB 而非前端**：前端狀態可被重新整理或繞過；R2-AC3 的語義是「此個案曾有人確認」，必須由伺服器在寫入前檢查，並用稽核列留下不可竄改的時間點（沿用 ADR 0011 的同交易稽核模式）。
- **schema v3 用 `ALTER TABLE` 而非重建**：新增 nullable 欄位是 SQLite 原生支援的向後相容變更；既有 v2 資料庫開啟即遷移，既有列語義正確（NULL＝尚未確認，舊個案同樣受閘門保護）。
- **filter 掛在「實際存在的 handler」上**：uvicorn 0.54 的 `uvicorn.error` logger 本身沒有 handler（record 向上傳播到 `uvicorn` logger 的 `default` handler）；寫死 handler 名稱會 `KeyError`，且換版本就壞。沿 logger 樹往上找是對已安裝設定的唯讀推導，不複製 uvicorn 的內部結構假設。
- **500 不回 traceback 到 stderr**：本地開發者會把終端輸出貼進 issue；一旦 traceback 引用材料文字就是外洩。型別名（`RuntimeError`）足以定位問題類別，完整偵錯用測試環境重現。

## 後果

- e2e／子程序回歸測試（`tests/test_upload_api.py`）以真實 uvicorn 子程序驗證：觸發含標記字串的 `RuntimeError` 後，stderr 無標記、無 `Traceback`，有 `unhandled error: RuntimeError`，回應本體恰為 `{"detail":"internal error"}`。
- M1 之後若要支援掃描檔，OCR 與其隱私邊界需另開 ADR；R12 文案與 `scan_not_supported` reason code 已為此預留。
