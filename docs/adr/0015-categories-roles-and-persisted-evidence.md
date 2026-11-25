# ADR 0015：R5 分類、來源角色與證據落庫（規則建議、理由格式、穩定 id、更正永不覆蓋）

日期：2026-11-24。狀態：已確認（PT-07 / Linear GROK-37）。

## 決策

R5 要求每條證據有一個建議分類與簡短理由，供她判斷——永遠不是結論。ADR 0014 的證據是即時計算、不落庫的檢視；本 ADR 把證據改為**落庫**（schema v5），因為 R5 的更正（她的分類／角色選擇）必須在規則重跑後存活，而即時計算無法承載「她的選擇」。四個部分：

1. **分類與角色規則**（`psychtool/core/categorize.py`，純函式、無 I/O）：
   - **CAT_KW / ROLE_KW 表逐字移植自原型**（cur.html ~870-880）：純 alternation、**先中先得**、不分大小寫，直接對已入庫的 quote 比對，因此每個關鍵字都是來源文字的逐位子字串。唯一例外：裸「I」保留原型的**區分大小寫**（小寫 i 不算來源），以 `(?-i:\bI\b)` 內嵌旗標實作。
   - **分類 8 鍵**（`CATEGORY_KEYS`）：`family_history`、`medical_history`、`test_results`、`behavioral_observations`、`development_school`、`daily_living`、`other`、`uncategorized`。**角色 6 鍵**（`ROLE_KEYS`，與分類**分開記錄**）：`school`、`caregiver`、`medical_record`、`clinician`、`client`、`to_confirm`。
   - **理由格式**：分類為 `The text mentions “{keyword}”, which relates to “{Label}”.`，角色為 `The text says “{keyword}”.`；keyword 為命中的逐位子字串、上限 40 字元，整條理由上限 **140 字元**（約兩行），因此理由永遠指向看得見的來源文字（R5-AC1）。
   - **無命中 → `uncategorized`**，固定理由「No words in the text indicate a category, so the system does not choose for you.」；**規則永不產出 `other`**——`other` 只留給她選（R5-AC2）。角色無命中 → `to_confirm` 加固定確認理由。
   - `CategorizeRules` 攜帶兩張表加版本字串（`RULES_VERSION = "rule-1"`），測試與日後的規則更新可換表，用以證明落庫 id 與她的更正存活（見下）。
2. **落庫（schema v4→v5，`evidence` 表）**：欄位含 `(case_id, evidence_id)` 主鍵、material/passage 定位、quote、suggested_category / category_reason / suggested_role / role_reason、可空的 `category`/`role`（**僅她的選擇**）、status（`active`/`superseded`）、rules_version；CHECK 約束強制分類／角色白名單、`0 <= start < end`、status 白名單；FK 指向 passages。既有資料庫以單步遷移建立新表（既有資料不變）。
   - **穩定 id**：`ev_` + sha256(`case_id ␟ material_id ␟ material_version ␟ passage_id ␟ start ␟ end`) 前 24 個 hex——由**位置**決定，與規則版本無關，故換規則表重跑後同一 span 仍是同一列，她的更正自然保留。
   - **`CaseStore.refresh_evidence`**：單一交易、冪等。新候選 INSERT；既有列只更新建議／理由／rules_version，**永不覆蓋 `category`/`role`**；本輪未再產出的列（含**舊材料版本**留下的列）標記 `superseded`——**只標記、永不刪除**，帶更正的 superseded 列仍會出現在清單並標 `kept_because_corrected`。每份有變更的材料在同一交易寫一筆 `evidence.extract` 稽核列（`item_count` = 該材料 active 數；只記 id 與計數，不記文字）。
   - **`set_evidence_choice`**：白名單驗證（非白名單鍵 → ValueError；未知 id → KeyError）；值有變才寫 `evidence.categorize` / `evidence.set_role` 稽核列（object_type `evidence`，僅 id）。明確傳 null 表示**還原為建議**。
3. **API**：
   - `GET /evidence`：**唯讀**——回傳最近一次 refresh 落庫的列（latest 版本優先、個案隔離），effective category/role = 她的選擇優先、否則建議，附 label、`category_set_by`/`role_set_by`（`clinician`/`suggestion`）與 `needs_extraction`。GET 不寫任何列；**`dropped` 不由 GET 回傳**（每請求新建的 CaseStore 上沒有可信任的上一輪計數）。
   - `POST /evidence/refresh`：重算（冪等），回 `{materials, dropped, needs_extraction}`；`dropped`（span 檢查丟棄數）只由這條路由回傳。
   - `PUT /evidence/{evidence_id}`：body 白名單鍵 `category`/`role`（可含 null 還原）；非白名單 → 400 固定 "invalid evidence choice"；未知 id → 404 固定 "evidence not found"。
   - **上傳／貼上成功後自動 refresh**（best-effort）：失敗不影響材料入庫，GET 以 `needs_extraction` 提示前端補跑一次。
4. **前端**（EvidencePanel）：每項顯示分類 chip（`uncategorized` 用虛線框區分）、獨立角色 chip「From: {label}」、完整理由行「Why: {reason}」（不截斷）；「Change category」（8 選項）與「Change source role」（6 選項）下拉在項目按鈕**之外**，選擇即 PUT 後重載清單；她的選擇標「Set by you」；`needs_extraction` 為真時前端先 POST refresh 一次再載入，`dropped` 提示只在這次 refresh 後顯示。

**既有段落級 claim 建議（intake claims）維持不變**：那是另一條「候選陳述 → 人工接受」的鏈路，本 ADR 不動。Alex 的第二問（claim 建議引用 evidence id）延後——claims 流程本期不改。

## 超出範圍

- R6（更正作廢句子／段落／egress 的連鎖失效）= PT-09；向度 = PT-08；LLMExtractor = PT-16。
- 分頁、權重、跨案彙總、任何模型呼叫。

## 理由

- **更正必須落庫才有意義**：R5 的核心互動是「她改掉系統的建議」；若證據只即時計算，任何重算都會抹掉她的判斷。落庫 + 位置決定的穩定 id 讓「規則怎麼換、她的選擇都在」成為可測試的不變式（store 測試以 rule-2 換表驗證）。
- **只標記、不刪除**：superseded 列是「這條證據曾經存在且被更正過」的證明；刪除會讓更正無聲消失，也破壞稽核的可追溯性。
- **理由指向逐字關鍵字**：R5-AC1 要求理由引用看得見的來源文字；關鍵字即命中子字串、雙引號包裹、長度上限，使「based on context」一類空話無法出現。
- **`other` 只留給人**：規則猜不出類別時若給 `other`，等同把「不知道」包裝成「已知」；`uncategorized` 加固定理由誠實標示系統不選邊（R5-AC2）。
- **GET 唯讀**：讀取不得有副作用；`dropped` 屬於一次 refresh 的執行結果，由執行它的路由回報才不會出現永遠是 0 的假訊息。

## 後果

- 測試：`tests/test_categorize.py`、`tests/test_evidence_store.py`（含兩個 Alex 測試：換規則表更正存活、更正過的 superseded 列仍標記）、`tests/test_evidence_categories_api.py`、`tests/test_evidence_api.py`（更新）、`tests/test_audit_log.py`（全流程序列加入 `evidence.extract`）、`web/tests/evidence.test.ts`、`web/e2e/categories.e2e.ts`。
- 上傳流程多一次落庫寫入與一筆稽核列；稽核鏈跨 v4/v5 列仍可驗證。
- 關鍵字規則有已知誤判／漏判（如「medical record lists/shows」會先被識別子脫敏改寫）；文件與 UI 文案不得把建議描述為判定。
- 前端 select 在 item 按鈕之外，避免觸發高亮點擊；PT-06 的高亮／捲動行為不變。
