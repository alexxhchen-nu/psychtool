# ADR 0013：R13 保護性測驗內容阻擋（關鍵字篩查、fail-closed、稽核計數）與開發用 traceback 開關

日期：2026-11-24。狀態：已確認（PT-05 / Linear GROK-35）。

## 決策

在上傳與匯入鏈路的每一個寫入點之前，以關鍵字篩查阻擋疑似受保護的測驗內容（原題、常模、計分規則），被阻擋的段落永不入庫、永不進入模型請求；阻擋行為本身以「計數 + 雜湊」稽核，不記任何文字。

1. **關鍵字清單與比對規則**（`psychtool/core/protected.py`，自原型逐字移植）：英文用字界（`\b`）比對——`test item(s)`、`test question(s)`、`norm`/`norms`、`norm table(s)`/`normative table(s)`、`scoring rule(s)`/`scoring key(s)`/`scoring criteria`、`conversion table(s)`、`raw-score table(s)`/`raw score table(s)`；中文以純子字串比對（中文無字界）——`原题`、`常模`、`计分规则`、`评分标准`、`换算表`。比對不分大小寫。因此 `normal`、`normally`、`abnormal`、`enormous`、`normalize`、`normative data` 不會命中。
2. **套用位置**：
   - **伺服器上傳與貼上**（`import_upload`）：切分段落後先篩查再寫入。命中段落被丟棄，保留段落以 `p001` 起重新連續編號（新上傳版本尚無 claim 引用，重新編號安全）；識別子檢查（identifier findings）只對保留段落的文字計算，被阻擋文字的一切資訊不進回應。
   - **CLI 上傳**：同一路徑（`import_upload` 的 JSON workspace 分支）。
   - **JSON workspace 匯入**（`SqliteStore.import_workspace`）：開交易前完成全部篩查。保留段落**保留原段落 id**（claim 以段落 id 引用來源，重新編號會使 claim 靜默指向別的段落；`position` 仍連續）。任一 claim 文字命中篩查、或引用到被阻擋的段落 → 整筆匯入拒絕（固定 `ValueError`，不寫任何列）。
   - **egress 防禦縱深**（`prepare_egress_request`）：SQLite 路徑重新篩查 `source_refs` 背後的 claim 文字與 material 段落文字（涵蓋 PT-05 之前已入庫的資料）；JSON workspace 路徑無法經 egress store 協定取回 claim/material，改為篩查整份 prompt——較嚴格（使用者親自輸入的 instructions 也會被篩），屬可接受的保守方向。命中或檢查器錯誤皆拒絕 prepare，不持久化任何 egress 列。臨床人員親自輸入的 instructions/section 文字在 SQLite 路徑**不**篩查：那是她自己的書寫，不是上傳的測驗內容。
3. **fail-closed（R13-AC2）**：檢查器本身拋出任何例外 → 整筆上傳/匯入/prepare 拒絕（`protected_check_failed` / egress 拒絕），不寫任何資料列。沒有「略過檢查繼續」的路徑。
4. **HTTP 介面**：成功回應加 `blocked_paragraphs`（int）與（>0 時）`blocked_reason`（固定文案，說明段落已被扣留、永不送入模型、M1 無釋放管道）。全部段落被阻擋 → 400 `{detail, reason: "protected_content"}`；檢查器失敗 → 503 `{detail, reason: "protected_check_failed"}`；egress prepare 命中 → 400 `{reason: "protected_content"}`。detail 一律是白名單常數（沿用 ADR 0012）。
5. **稽核**：新動作 `material.protected_blocked`（object_type `material`），`content_hash` 為被阻擋段落文字以 `\n\n` 連接後的 SHA-256，`item_count` 為被阻擋段落數；**永不記文字**。部分阻擋時該列與材料匯入在**同一交易**（沿用 ADR 0011）；全阻擋時無材料列，阻擋稽核列自成交易。`audit_log` 新增 nullable `item_count INTEGER`（schema v3→v4，`ALTER TABLE`）；鏈雜湊只在 `item_count` 非 NULL 時涵蓋它，故 v4 之前的列雜湊值不變、鏈在遷移後仍可驗證。
6. **M1 無釋放機制**：被阻擋內容沒有 override/release 按鈕或 API；前端只顯示固定的 held-back 告知（`role="status"`）。
7. **開發用 traceback 開關**：環境變數 `PSYCHTOOL_DEBUG_TRACEBACKS=1`（僅接受字面值 `1`；`true`/`yes` 等一律視為關）僅在合成層級生效。`main()` 在 real 層級 + 開關開啟時印一行純文字拒絕並以 exit 2 結束（先於建立 app 與開啟資料庫）；合成層級 + 開關開啟時不安裝 `UvicornErrorTraceFilter`（uvicorn 以 `log_config=None` 執行）、catch-all 以 `exc_info` 記完整 traceback，並在啟動時記一筆 WARNING `self-check warn: debug tracebacks ON (dev only; never with real data)`。`create_app` 內的 catch-all 經 `debug_tracebacks_enabled(config)` 判定（同時重讀環境變數並檢查層級），real 層級無論環境變數為何都保持型別名記錄；`load_config` 對 real+env=1 不拋錯（只回傳 `debug_tracebacks=False`），拒絕啟動是 `main` 的職責。

## 理由

- **關鍵字篩查是「最便宜的第一道牆」**：APA/Pearson 對測驗原題與常模的使用限制（`references/assessment-materials-boundaries.md`）要求預設阻擋；字界與子字串的區分讓英文誤判（normal/enormous）接近零，而中文無字界可用，只能接受子字串比對。
- **fail-closed 而非 fail-open**：檢查器壞掉時若放行，等於在最需要防線的時刻（依賴異常、資料異常）失去防線；拒絕整筆上傳的代價遠低於一次受保護內容入庫。
- **稽核只記計數與雜湊**：阻擋事件的證明力來自「發生過、擋了幾段、內容指紋為何」，記文字反而把受保護內容複製進稽核表。
- **JSON 匯入保留原段落 id**：claim 的 `source_passage_id` 是引用錨點；重新編號會讓既有 claim 靜默指向錯誤段落，比拒絕匯入更糟。
- **traceback 開關限定合成層級且 main 拒絕啟動**：traceback 可能引用請求或材料文字；real 層級下「靜默忽略開關」會讓操作者誤以為沒有 traceback 其實有，明確拒絕啟動才能消除這個誤解。

## 後果

- 已入庫（PT-05 之前）的受保護資料無法經 egress 離開；需由後續版本提供清理工具。
- 關鍵字篩查有已知誤判：`no norm data provided` 一類句子會被擋（fixture `adolescent-background.json` 的 A-S2 段已改寫為「标准化比较资料」）；也有已知漏判（改寫措辭即可繞過）。文件與 UI 文案不得把此篩查描述為完整防護。
- schema v4 遷移對既有資料庫是單一 `ALTER TABLE`；`verify_audit_chain` 跨 v3/v4 列皆可驗證。
- 測試：`tests/test_protected.py`、`tests/test_r13_upload.py`、`tests/test_debug_tracebacks.py`、`web/tests/upload.test.ts`、`web/e2e/protected.e2e.ts`。
