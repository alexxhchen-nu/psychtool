# ADR 0017：句子證據作為陳述唯一來源（claim_evidence、schema v7、v6→v7 遷移）

日期：2026-11-24。狀態：已確認（PT-20 chunk 1 / Linear GROK-51）。

## 決策

ADR 0014/0015 讓證據成為逐字句子並落庫；本 ADR 把「陳述（claim）引用了哪些證據」也變成資料庫裡的事實，而不是藏在段落定位裡的隱含關係。句子證據是陳述**唯一**的來源：一條陳述不再只指向「某材料某版本的某段落」，而是明確列出它引用的證據列。分三部分：

1. **`claim_evidence` 連結表（schema v6→v7）**。欄位：case_id、claim_id、version、evidence_id；主鍵 `(case_id, claim_id, version, evidence_id)`。外鍵 `(case_id, claim_id, version)` 指向 `claims` 並 `ON DELETE CASCADE`；外鍵 `(case_id, evidence_id)` 指向 `evidence`——因為兩條外鍵都帶 case_id，**跨案引用在資料庫層結構性不可能**，即使繞過應用層直接寫 SQL 也會被 FK 拒絕。`claims` 表本身的 `source_document_id`/`source_version`/`source_passage_id` 保留：那是段落分組的定位器（哪個段落產生了這條陳述），本 chunk 不刪除、也不動 passages 的外鍵。
2. **模型與儲存層**。`Claim` 新增 `evidence_ids: list[str]`（預設空清單，讓遷移前的歷史列與從未記錄 id 的檔案工作區照常載入）；`ClaimSuggestion` 同樣攜帶 `evidence_ids`，`accept_suggestion` 原樣傳遞。SQLite 的 `add_claim`/`list`/`get` 經由 `claim_evidence` 寫入與水合：傳入的每個 id 必須已存在於**本案**的 `evidence` 表，否則在寫入前拋 `ValueError`（整筆交易回滾，絕不靜默丟棄引用）；空清單在本 chunk 的儲存層仍合法（建議／路由層之後才決定何時必須引用）。
3. **v6→v7 遷移規則**。純加表：先 `CREATE TABLE IF NOT EXISTS claim_evidence`，再對每條既有 claims 列，按 `(source_document_id, source_version, source_passage_id)` 對上**同案**、**active** 的 evidence 列（比對 material_id、material_version、passage_id），每對應一列插一筆 junction。規則的邊界：superseded 的證據列**不連結**；他案的證據 id **不連結**；段落沒有任何 active 證據時該陳述留零筆 junction——**不憑空造證據、不改寫陳述**。稽核列完全不重寫，`verify_audit_chain` 在遷移後照常通過。對更早的 v1–v5 資料庫，遷移鏈在到達 v7 前可能根本沒有 claims/evidence 表，回填步驟對「無表」視為「無可回填」。

## 超出範圍

- `suggest_claims` 改寫（讓建議直接從句子證據產生）＝PT-20 chunk 2（已完成，見下節）。
- HTTP 路由、egress 的 SourceRef/lineage、UI 顯示＝PT-20 chunk 3（UI 部分）。
- R6（更正作廢引用該證據的句子／段落／egress 的連鎖失效）＝PT-09，本卡不做。
- 任何模型呼叫、分頁、跨案彙總。

## 建議與 lineage（chunk 2 補記）

- **建議即證據**：`suggest_claims` 只為「該材料版本有至少一筆 stored active 證據」的段落產生建議，`evidence_ids` 即那些 stored id（排序穩定）；沒有證據的段落不產生建議，建議永遠不會帶空清單。CaseStore 路徑讀取已落庫的列（上傳時已自動擷取），絕不以重新擷取冒充已存列；檔案工作區路徑若尚未落庫，先用既有 RuleExtractor 擷取、以同一個位置決定的 `ev_` id 寫入 `evidence/` 後再引用——段落級的平行證據路徑就此移除。`source_document_id`/`source_version`/`source_passage_id` 保留為段落分組定位器，但陳述的來源真相是 `evidence_ids`。
- **接受即驗證**：`accept_suggestion` 與 `POST /claims` 要求至少一個 id，且每個 id 必須能對到**本案**的 stored 證據；未知 id 與他案 id 一律以固定訊息拒絕（不透露 id 是否存在於他案），HTTP 回 400。
- **egress lineage**：`SourceRef` 新增 `evidence_ids`（kind=claim 時由 `build_section_request_input` 從所選陳述帶入；material/draft 為空），隨既有 `source_refs` JSON 落庫，重新載入請求仍看得見。R13 保護內容檢查在 prepare 時除陳述文字外，也篩被引用證據的 quote。
- **UI（chunk 3）**：建議卡以 `data-testid="cited-evidence-ids"` 顯示伺服器回傳的引用 id（UI 從不自造 id）；接受時原樣 POST 含 `evidence_ids` 的建議物件；walking-skeleton e2e 斷言首張卡至少含一個 `ev_` id 後才接受。

## 理由

- **來源必須是句子，不是段落**：段落定位只說「這條陳述來自哪一段」，無法回答「它引用哪幾句」；把引用落成 junction 列，之後的失效連鎖（PT-09）、citecheck 與 egress lineage 才有可查詢的事實基礎。
- **跨案引用要結構性擋下**：與 ADR 0010 的個案隔離一致——不是「程式小心不要查錯」，而是 FK 讓錯誤的列根本插不進去。
- **遷移只連結、不創造**：v6 的陳述只有段落定位；若段落已無 active 證據，如實留空比假造一列誠實，也讓「零引用」成為可測試的遷移結果。
- **空清單暫時合法**：本 chunk 只落地 schema 與儲存管道；何時強制引用由建議與路由層在後續 chunk 決定，避免在儲存層過早鎖死規則。

## 後果

- 測試：`tests/test_claim_evidence_migrate.py`（真實 v6 夾具的遷移測試：active 連結、superseded 不連結、跨案不連結、無證據留零、稽核鏈驗證、陳述原文與來源定位不變；store 層 add_claim 的合法／未知／跨案／空清單與 mark_status 攜帶）。
- Schema 現為 v7；遷移純加表，既有列不變，舊稽核雜湊仍可驗證。
- `Claim`/`ClaimSuggestion` 的 JSON 表示多一個 `evidence_ids` 欄位；檔案工作區的既有 claim JSON 無此欄位時以預設空清單載入，向後相容。
