# ADR 0020：R9 章節編輯與保存、臨床者專屬章節、一個主按鈕

日期：2026-11-25。狀態：已確認（PT-11 / Linear GROK-41）。

## 決策

章節草稿生成後進入未保存狀態，由她編輯並保存；刷新或再打開該章節時看到的是保存後的文字。診斷、印象與建議類章節只由她本人撰寫，系統不得把模型輸出填進去，也不得把這些章節送去模型。草稿視圖同一時間只有一個主按鈕。視覺回歸的約定閾值改為每視窗 2%（見 ADR 0019 第 5 點，Alex 於 2026-11-25 定案）。

1. **未保存與保存（R9-AC1、R9-AC2）。** 普通章節走既有的 prepare → approve → send。成功後正文出現在該章編輯區，狀態為未保存（不自動保存、不繼承先前的 Approved）。她勾選的來源陳述保持勾選，可點開右側來源卡（不在本 PT 做句子級引用篩選，那是 PT-12）。保存列顯示 “Unsaved changes” / “Saved”。切換到其他章節再回來，未保存文字仍在；保存成功後，再打開或整頁刷新都顯示保存後的文字。

2. **臨床者專屬章節（R9-AC3）。** 以內容類型判定，而非審查門檻：`content_types` 含 `diagnostic_conclusion` 或 `recommendation` 的章節（本案模板為 Clinical Impressions 與 Recommendations）永不送出、永不自動填入模型文字。這些章節可以空白，或只顯示她選入的證據提示，等她親自寫。`licensed_clinician` 審查門檻仍只管批准是否需要審閱者姓名，不擴大「她親自寫」的範圍。準備請求在組 prompt 之前即拒絕（固定 400：「this section is written by the clinician and is not sent to the model」），介面上也不再畫出模型請求面板。

3. **一個主按鈕。** 與原型相同：同一視圖只有一個實心主操作。建立個案永遠是次按鈕。草稿保存列的主按鈕是：若送出面板正有可執行步驟（Approve request / Send once），保存列退為次按鈕；否則在可批准時為 Approve section，有未保存修改時為 Save section。M1 不提供 Export（Q7）。

## 超出範圍

- PT-12 的 citecheck／句子級引用與篩選。
- PT-22 為來源卡補上段落／字元範圍。
- GROK-53／PT-21 的 claim-verify HTTP 路由。
- 把 `tech-design.md` 加入本倉庫（Alex：不加入；2% 寫入 `web/e2e/visual.e2e.ts` 與 ADR 0019）。
