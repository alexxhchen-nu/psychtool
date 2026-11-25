# ADR 0016：R7 向度對照（清單上傳、四條硬規則、Needs review、稽核 value 欄）

日期：2026-11-24。狀態：已確認（PT-08 / Linear GROK-38）。

## 決策

R7 要求向度名稱**只來自她上傳的內容**——產品任何地方都沒有內建的官方向度或診斷準則清單。不確定時標「Needs review」，從不猜一個向度。畫面用語固定為 "dimension"、"Needs review"、"This is not a diagnosis"。本 ADR 把對照做成可測試的程式規則（不是提示詞），並讓她的確認／更改在清單改版後仍能對上同一個名稱。四個部分：

1. **向度清單是一種材料（`kind='dims'`）**。Schema v5→v6：`materials.kind` 為 `'case'` 或 `'dims'`（預設 `'case'`）。上傳與貼上接受可選的 `kind`。每個案最多一份 dims 材料：同一 `material_id` 再傳是新版本（最新版本即清單）；另傳一個 id 而清單已存在 → 409 固定本文 `{"detail":"dimension list exists"}`。Dims 材料**永不**進入證據擷取。清單在匯入時以**每條非空列為一段落**切開（與原型一致），讓「Source: your list, paragraph n」能指到那一行。
2. **`dimensions` 表與穩定 id**。欄位：case_id、dimension_id、list_material_id、list_version、passage_id、start、end、name。名稱解析移植自原型 `buildCase`：去掉開頭 `Dimension N:`／`维度N：`（含中文數字）、去掉一組括號、去掉一個句尾句號，再修剪。名稱必須是該段文字的逐位子字串（以 spans 工具驗證），否則略過；過不了規則 4 過濾的列計入 `held_back`，不成向度。開頭介紹句（解析後仍是 ≥12 個詞的完整句子，或不足 2／超過 80 字元）不成向度。`dimension_id = "dim_" + sha256(case_id, list_material_id, 大小寫摺疊後的名稱)[:24]`，因此同一名稱在新版本清單裡仍是同一個 id，她的選擇得以保留。
3. **比對器（`psychtool/core/dimensions.py`，`DIM_RULES_VERSION = "dim-1"`）** 移植自原型 `dimHit` + `DIM_SYN` + `STOP`：對她的每個名稱，依序用 CJK 雙字（名稱含漢字時只走這條、不命中即結束）、≥4 字母的字首比對、再才用同義表（同義表只幫她的名稱對上原文，**絕不創造名稱**）。結果：恰好一個命中 → `needs_review` 加該向度與固定理由（命中必須是 quote 的子字串，理由 ≤140 字元）；兩個或以上 → `needs_review`、沒有向度；沒有命中 → `none`；沒有清單 → `none`。然後在程式裡套用四條硬規則（不信任比對器）：
   1. 只有 `dimensions` 表裡的名稱可被引用；表外名稱／id 一律丟棄。
   2. 每條理由必須引用該證據看得見的文字（子字串檢查）；否則降為 `needs_review` 且沒有向度。
   3. 沒有清單就完全不對照。
   4. 輸出過濾擋住診斷語氣與準則編號（如 "meets criteria"、"Criterion A1"、"F90.0"）：清單列含這些內容會被扣留並計數，不成向度；理由含這些內容則改為固定安全理由並標 needs_review。每個向度畫面都顯示固定聲明「This is not a diagnosis. The diagnosis is yours.」
4. **她的選擇與稽核 `value` 欄**（Alex 對 PT-07 第三問的決定）。證據列新增建議／選擇欄（`suggested_dimension_id`、`dim_state_suggested`、`dim_reason`、`dimension_choice`、`dimension_id`）。有效狀態以她的選擇為準：confirmed/changed 顯示她的向度；rejected 為「No dimension」；否則為建議。她的選擇**永不**被 refresh 覆蓋。若她選的向度已不在最新清單，該項改為 `needs_review` 並附固定理由「The dimension you chose is no longer in your list; please check.」（列保留）。`PUT /evidence/{id}/dimension` 的動作是 confirm／改到表內 id／none／reset。稽核列對她的分類、角色與向度更改必須記錄她選的**值**——僅白名單：`evidence.categorize` 為分類鍵或 `reset`；`evidence.set_role` 為角色鍵或 `reset`；`evidence.set_dimension` 為 `confirm`｜`none`｜`reset`｜`dim_[0-9a-f]{24}`（記 id、永不記名稱）。其餘一律在稽核層拒絕。新列的 `value` 在非空時才納入雜湊，因此遷移前的列仍可驗證。另允許 `dimension_list.build`（object_type material，item_count = 向度數）。

對照在 `refresh_evidence`（同一交易）以及 dims 清單上傳／貼上時重算建議；`GET /dimensions` 與 `GET /evidence` 都是唯讀。

## 超出範圍

- R6（更正作廢引用該證據的句子／段落／egress）= PT-09，本卡不做失效連鎖。
- citecheck／草稿過濾 = PT-12。
- GROK-51（句子證據作為唯一來源）在 PT-08 之後、PT-09 之前，須等 Alex 核准才開始。
- 分頁、任何模型呼叫、內建 DSM／ICD 準則文本。

## 理由

- **名稱必須是她上傳的**：R7-AC1／AC2／AC8 禁止產品自帶官方向度或準則；把清單做成材料、把名稱寫進表、再在程式裡丟棄表外建議，比「請模型不要發明名稱」可靠。
- **不確定就不賦值**：兩個名稱都命中時若隨便挑一個，等於把猜測寫成對照；標 Needs review 且不附向度，才符合「從未猜一個向度」。
- **四條硬規則寫在程式裡**：比對器可以被測試替換成會傳回未知名稱或不良理由的假物件；規則仍要擋下。這樣規則不會因提示詞或模型而鬆掉。
- **選擇記 id、稽核記白名單值**：名稱是她的文字，不能進稽核。穩定 id 讓清單改版但名稱不變時，她的確認還在。

## 後果

- 測試：`tests/test_dimensions.py`、`tests/test_dimensions_store.py`、`tests/test_dimensions_api.py`（`test_r7_ac1`…`test_r7_ac9`）、`tests/test_evidence_store.py` 的 v5→v6 遷移（含既有資料與稽核鏈）、`web/tests/dimensions.test.ts`、`web/tests/dimensions-api.test.ts`、`web/e2e/dimensions.e2e.ts`。
- Schema 現為 v6；遷移純加欄／加表，既有列的新欄為 NULL，舊稽核雜湊仍可驗證。
- 前端 Dimensions 面板對齊原型文案與結構（現有 design tokens，不加新字體）；Evidence 列加「Dimension:」chip。
- 對照資料不得進入診斷／印象章節、草稿或 egress 內容（R7-AC7 守護測試）。
