# ADR 0018：R6 更正連鎖失效（單一交易、提示語、絕不改寫已存文字）

日期：2026-11-25。狀態：已確認（PT-09 chunk 1 / Linear GROK-39）。

## 決策

R6 要求：她更正一筆證據的分類或向度時，所有建立在舊更正上的東西必須在同一次動作裡回到「需要重新核對」——不能出現「證據改了、陳述還是 verified、段落還是 approved」的中間態。本 ADR 把連鎖失效做成**儲存層單一 SQLite 交易**裡的三個步驟，並規定兩條不可讓步的邊界：**絕不改寫她已存的文字**（陳述、段落一字不動），**絕不動未送出的文字以外的任何東西**（已送出的 egress 請求永遠保持 sent）。

1. **觸發條件：有效值真的改變**。只有「有效分類鍵」（她的選擇，未選時為建議）或「有效向度 id」（含「無向度」）**實際改變**才觸發連鎖。只改角色（role-only）、重複寫入相同值、以及確認一個已顯示的建議向度（有效 id 不變）都**不觸發**。向度的有效 id 與 `list_evidence` 的顯示規則一致：她的 confirmed/changed 選擇為準，已不在最新清單的選擇視同無向度，rejected 為無向度，否則取建議。
2. **三個步驟，全部在同一交易**（與證據列更新、`evidence.categorize`/`evidence.set_dimension` 稽核列同一交易；`transaction()` 巢狀加入外層交易）：
   - **陳述**：最新版本引用此證據、且 `verification_status` 為 `verified` 或 `conflict-viewed` 的每條陳述，經 `mark_claim_status` 寫入新版本 `pending`——文字與 `evidence_ids` 逐字保留，只動狀態。
   - **段落**：最新版本為 `approved` 且其 `claim_ids` 含任一被失效陳述的段落，經 `save_section` 寫入新版本 `needs_review`——text、claim_ids、reviewer 完全相同；draft/empty 段落不動。
   - **egress**：`prepared` 或 `approved`（未送出）且引用此證據的請求——任一 `source_ref.evidence_ids` 含此 id，或 `kind=claim` 的 ref 指向的陳述引用了此證據——經既有 `save_egress_request` 存為 `invalidated`，因此 `egress.invalidate` 稽核列落在同一交易。`sent` 永遠不動；不相干的請求不動。
3. **回傳與提示語（toast）**。兩個 setter 回傳證據列加上 `invalidation`：`{"claims": [...], "sections": [...], "egress": [...], "toast": "<固定英文>"}`，id 皆穩定排序。提示語逐字固定：以 "Your change was saved." 開頭；非空的清單各附一句（單數/複數分別為 "1 citing statement is no longer marked verified." / "N citing statements are no longer marked verified."；"1 section was returned to Needs review." / "N sections were returned to Needs review."；"1 prepared request was invalidated and must be prepared again." / "N prepared requests were invalidated and must be prepared again."）；三個清單皆空時附 "Nothing else needed to be updated."；一律以 "Unsaved text was not changed." 結尾。
4. **原子性測試鉤**。`CaseStore.cascade_hook` 是可設定的實例鉤（正式程式永不設定）：每完成一個步驟（`claims`、`sections`、`egress`）就以步驟名呼叫一次；鉤拋出例外時整個交易回滾——證據、陳述、段落、egress 與稽核鏈全部回到動作前，**絕不半失效**。

## 超出範圍

- HTTP 回應形狀（SPA 消費 `invalidation`）＝PT-09 chunk 2。
- UI toast 顯示、bun 前端測試、e2e＝PT-09 chunk 3。
- PT-10 不開始。
- Schema 維持 v7：連鎖全部重用既有表與既有稽核動作（`claim` 無新動作——陳述狀態版本列本身就是事實；段落用 `section.save`；egress 用 `egress.invalidate`），不新增稽核動作。

## 理由

- **同一交易是唯一誠實的做法**：若連鎖在證據更新之後才跑，中途當機會留下「分類已改、陳述仍 verified」的假象——這正是 R6 要消滅的狀態。巢狀 `transaction()` 讓 `mark_claim_status`、`save_section`、`save_egress_request` 直接加入 setter 的交易，不需新機制。
- **只動狀態、不動文字**：她是唯一的作者。把陳述或段落文字改寫成「系統版本」會摧毀可追溯性；新版本列只翻轉狀態，原文逐字保留，稽核鏈與版本史都誠實。
- **有效值而非儲存值**：連鎖的語義是「她看到的東西變了」。確認一個已顯示的建議向度沒有改變她看到的任何東西，因此不該把已核對的陳述打回 pending——否則每次確認都要重核一遍，連鎖就變成噪音。
- **toast 逐字固定**：提示語是產品契約的一部分（chunk 3 的 UI 會逐字顯示），在儲存層定死並用測試鎖住單複數與空清單措辞，UI 就不會各自發明措辭。

## 後果

- 測試：`tests/test_evidence_cascade.py`（R6-AC1 分類連鎖、R7-AC4 向度連鎖、文字不變、egress 三態、role-only 與 no-op 不連鎖、確認建議不連鎖、toast 0/1/2+ 計數、`cascade_hook` 注入失敗的完全回滾、`list_egress_requests` 個案隔離）。
- `CaseStore` 新增 `list_egress_requests()`（唯讀、request_id 排序、個案限定）。
- 兩個 setter 的回傳值多一個 `invalidation` 鍵；既有欄位不變，HTTP 路由目前忽略該鍵（chunk 2 才消費），既有 API 測試不受影響。
- Schema 維持 v7；無新稽核動作、無新表。
