# ADR 0014：R4 證據擷取（Extractor 介面、RuleExtractor、逐字 span 檢查）

日期：2026-11-24。狀態：已確認（PT-06 / Linear GROK-36）。

## 決策

R4 的證據是給她核對用的，不是結論，也**絕不自動寫入報告文字**。M1 的證據鏈路由四個部分組成：

1. **Extractor 介面**（`psychtool/core/extract.py`）：`name: str` 加 `extract(material) -> list[EvidenceCandidate]` 的 Protocol。`EvidenceCandidate` 含 id、quote、span（`Span`）與 1-based 段落位置。M1 只實作 `RuleExtractor`（Q4 決定：僅本地規則、無模型呼叫）；LLMExtractor 不在本期範圍（PT-16）。
2. **RuleExtractor**（原型 `buildCase` 啟發式移植）：逐段落切句——以 `. ! ? 。 ！ ？` 為句尾，但「`.`」在以下兩種情況**不**斷句：(a) 其後緊鄰非空白字元（涵蓋 `a.m`、`1.5`、`e.g`）；(b) 前一字（不分大小寫、允許內部點）是已知縮寫：`a.m, p.m, mr, mrs, ms, dr, e.g, i.e, etc, vs, approx`。`! ? 。 ！ ？` 一律斷句。每句修剪周圍空白、**剝除一個**句尾標點；少於 6 字元的句子捨棄，但含 CJK（U+4E00–U+9FFF）的句子以 4 字元為下限。span 以前一句結尾向前搜尋定位，重複句子得到各自不同的 span。id 確定性生成：`{material.id}-v{version}-{passage.id}-s{n}`（n 為該段落保留句的 1-based 序號）。
3. **Span 契約與逐字檢查**（`psychtool/core/spans.py`）：`Span` 為（material_id, material_version, passage_id, start, end），offset 是該段落文字的**Unicode 碼點**索引（`0 <= start < end <= len`），模型層拒絕 `start >= end` 與負值。`verify_quote` 僅在 `passage.text[start:end] == quote` 逐字成立時回 True；材料 id／版本不符、未知段落、邊界越界、空 quote 一律回 False（永不拋錯）。`extract_evidence` 只保留 verify 為 True 的候選，其餘靜默丟棄並計數（`dropped`）——**永不修正 quote**；候選也**永不合併、去重或折疊**：不同段落／材料中的相同或矛盾句子各自保留為獨立項目（R4-AC3）。前端 `highlightParts` 以 `Array.from` 做碼點切片，與 Python offset 對齊（含 astral 字元與 CJK）。
4. **Evidence API**（`GET /api/workspaces/{case_id}/evidence`）：個案隔離與其他路由一致；**唯讀**——不產生 claim、section、egress 列，也不寫稽核列；未知個案回固定 404。~~M1 不把證據落庫~~ **PT-07 起改為落庫（schema v5），含分類、理由與她的更正——見 ADR 0015**；本 ADR 的逐字 span 契約與不合併原則不變。

**既有段落級 claim 建議（intake claims）維持不變**：那是另一條「候選陳述 → 人工接受」的鏈路，本 ADR 不改其流程。

## 超出範圍

- 分類／理由／提供者角色提示 = PT-07；向度 = PT-08；R6；LLMExtractor = PT-16。
- 上傳前超大檔預檢、生成式 id、SQLCipher、HMAC。

## 理由

- **逐字是唯一可信的對照**：quote 一旦偏離原文，「點一下看原文」就會指向錯誤位置；寧可丟棄也不修正，因為修正後的句子不再是證據。
- **不合併是 R4 的核心**：同一事實的兩種說法（如照顧者說睡 8 小時、自陳凌晨 1 點才睡）都必須各自可見，任何合併都會隱藏衝突。
- **即時計算不落庫（PT-06 當時）**：證據是衍生檢視；材料版本不可變、重算成本低。PT-07（ADR 0015）為承載她的更正改為落庫，以位置決定的穩定 id 保住更正，逐字與不合併原則不變。
- **縮寫與小數點不斷句**：原型 regex 會把 `1 a.m. before...` 切成碎片，使自陳句無法作為一條完整證據被核對。

## 後果

- 測試：`tests/test_spans.py`、`tests/test_extract.py`、`tests/test_evidence_api.py`、`web/tests/evidence.test.ts`、`web/e2e/evidence.e2e.ts`。
- 證據清單可能很長（每句一項）；M1 無分頁，個案規模可控。
- EvidencePanel 只讀：無任何寫入報告或建立 claim 的按鈕。
