# ADR 0019：R8 三欄工作區、GitBook 主題、來源卡只顯示真實位置

日期：2026-11-25。狀態：已確認（PT-10 / Linear GROK-40）。

## 決策

把工作區做成與原型一致的三欄（左：報告段落／材料，中：草稿編輯，右：來源卡），並把 GitBook 文件主題與狀態形狀（✓ / ? / !）移植到 SPA。右欄來源卡**只顯示材料真正有的位置**，絕不編造頁碼或座標。原型的「Export saved draft」按鈕不移植（Q7：匯出留到 M2）。PT-09 的更正提示語中段改為**永遠說出有幾個段落回到 Needs review**（含 0）。

1. **三欄與主題。** 桌面 1440 的欄寬與原型相同：`256px minmax(0,1fr) minmax(340px,0.66fr)`；1280／1024 依原型既有規則收合。色彩與字體 token 直接取自原型（`theme-gitbook/tokens.md` 與 `poppins/variants/cur.html` 的 `:root`）：`--paper #FFFFFF`、`--ink #1D1D1D`、`--accent #E8460F`、`--accent-ink #C42A00`，以及 ok／chk／un。隱私橫幅為 ink 底白字，與原型 `.banner` 一致。OFL 的 Proto Sans／Proto Mono 以 `'self'` 字體檔嵌入（CSP 不連外網）。不另造一套調色盤。
2. **來源卡（R8-AC1、R8-AC2）。** 段落開啟時，點證據或點該段已引用的陳述，右側顯示原文範圍、材料名稱／版本（若有）、來源角色、以及是否仍未確認；中欄編輯器保持可見，不用蓋住草稿的小彈窗。位置列只由實際存在的欄位組成，原型格式為 `name · version · paragraph N · characters a–b`。儲存層偏移是 0-based 半開的 Unicode 碼位區間 `[start, end)`（ADR 0014），畫面上改為 1-based 閉區間 `a+1–b`。缺的欄位就省略。**系統沒有頁碼欄，也絕不顯示編造的頁碼。**
3. **不移植匯出（Q7）。** UI 任何入口都沒有 Export／「Export saved draft」。測試在原始碼與畫面上都會因重新加入而失敗。
4. **更正提示語（修訂 ADR 0018 的中段）。** 開頭仍是 “Your change was saved.”，結尾仍是 “Unsaved text was not changed.” 中段**永遠**包含段落句，包括零：「0 sections were returned to Needs review.」／「1 section was returned to Needs review.」／「N sections were returned to Needs review.」陳述與 egress 句仍只在數量非零時出現。不再使用 “Nothing else needed to be updated.” 草稿文字仍絕不自動改寫，只動狀態。
5. **對比與截圖。** 對 SPA 跑與原型相同的 WCAG 2.x 對比檢查（普通文字 ≥4.5:1，大字與非文字／1.4.11 ≥3:1），必須 0 筆失敗。視覺回歸在 1440×900、1280×800、1024×768 對原型截圖比較；遮罩原型的匯出控制與雙方會變的內文，比的是外殼／版面／主題。約定閾值為每視窗 **2%** 差異像素（`maxDiffPixelRatio` 0.02；Alex 於 2026-11-25 定案，不是暫定工作值）。

## 超出範圍

- PT-11 的句子級草稿編輯。本 PT 的中欄仍是既有的 textarea；「點選有來源的草稿句子」以點選該段已引用的陳述為準。
- GROK-53／PT-21 的 claim-verify HTTP 路由。
- 匯出（Q7／M2）。

## 理由

R8 要她在寫草稿的同時看見來源，而不是被彈窗擋住。位置只顯示真實欄位，是為了不把沒有的頁碼寫進報告習慣裡。主題與原型對齊，是為了讓截圖回歸有一個可檢查的標準。提示語永遠報段落數，是為了讓她不必猜「這次有沒有段落下來」。
