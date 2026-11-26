# ADR 0021：逐句核引用、Unverified／My judgment，以及 Summary 用語攔截

日期：2026-11-25。狀態：已確認（PT-12 / Linear GROK-42）。

## 決策

草稿裡每一句事實性陳述都必須指向它用過的本案證據；對不上的句子標為 Unverified，不得看起來像已有根據。Findings 與 Summary 可以由模型起草，再由心理師批准。為避免經 Summary 繞過 R9-AC3，Summary 草稿不得含診斷或建議用語。攔截方式是**拒絕**，絕不默默刪改或重寫正文——草稿從來不會被自動改寫（Alex，2026-11-25）。

1. **句子級引用（補完 R9-AC1，R10-AC1）。** `citecheck` 把草稿拆成句子（沿用抽取器的分句規則），用證據原文的字面重疊判斷引用：一句可指向多條本案 active 證據。有出處的句子預設為 Needs review；無出處且不是「我的判斷」的句子為 Unverified。狀態由伺服器重算，呼叫端不能把無出處的事實句標成 Verified。

2. **schema v8。** 新增 `section_sentences` 與 `sentence_evidence` 兩張表，外鍵都帶 `case_id`，因此跨案引用在資料庫層結構性不可能。遷移只加表，不為既有章節回填句子（不憑空造引用）；舊列的正文不變，遷移前的稽核鏈仍可驗證。檔案工作區的章節 JSON 增加可選 `sentences`，缺省為空清單。

3. **標記在保存後仍在（R10-AC2）。** Unverified／Needs review／Verified／My judgment 隨章節版本一起落庫。本卡不實作 Export（M2／Q7）；M1 以保存為準。

4. **My judgment（R10-AC3）。** 她把一句尚未核對的文字標為自己的專業判斷後，該句按判斷處理，不再偽裝成材料裡已經寫明的事實。無出處的判斷句保持 `my_judgment`，不得被翻成 Unverified。

5. **用語攔截：拒絕，不改寫。**
   - Summary：含診斷用語或建議用語（字面短語表，不是語義分類器）時，citecheck 回 `blocked`，保存回固定 400：「a Summary draft must not contain diagnostic or recommendation wording」。
   - 其他可由模型起草的章節：含診斷用語，或含她未上傳材料中的標準編號／手冊式片段（R7-AC6／AC8）時，拒絕並回固定 400：「draft text must not contain diagnostic wording or un-uploaded manual text」。若該片段是已上傳原文的子字串，則不因此攔截。
   - 臨床者專屬章節（Clinical Impressions、Recommendations）仍由她撰寫，本過濾不套用；它們也仍不會被模型自動填寫（ADR 0020）。
   - 維度頁上的固定聲明「This is not a diagnosis. The diagnosis is yours.」不是草稿違規。
   - 被拒絕時正文原樣留下，不剝除、不替換、不自動重寫。

## 超出範圍

- PT-22 為來源卡補上段落／字元範圍。
- PT-21／GROK-53 的 claim-verify HTTP 路由。
- PT-13 的 Vertex 適配器。
- 導出（Export，M2／Q7）。
