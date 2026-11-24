<!-- architect-team:readme-theme=mono -->

<div align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="psychtool — 來源可溯的臨床寫作工作區，右側為帶來源定位的證據索引卡">
</div>

[简体中文](README.zh-CN.md) | [English](README.en.md) | **繁體中文**

<div id="overview"></div>
<p align="center">
  <img src="./assets/readme/sec-01-what-this-is.svg" width="100%" alt="01 · 这是什么 / WHAT THIS IS">
</p>

psychtool 是一個幫助個人寫報告的臨床寫作工作區，目標使用者是沒有技術背景的臨床培訓生。它解決的核心問題：**如何在把分散資料整理成報告草稿的同時，保留誰在什麼場合、什麼時間、以什麼確定性說了什麼**——而不是先生成流暢文字再回頭補引用。

心理評估報告、臨床個案報告、進展紀錄與學術論文都在長期範圍內；目前優先臨床寫作，首個驗證情境刻意收窄為**整理合成的青少年背景資料**：不做診斷、不解釋量表、不做治療決策。青少年與神經心理側重是設計選擇；機構 AI 政策尚未確認。

<div id="current-state"></div>
<p align="center">
  <img src="./assets/readme/sec-02-current-state.svg" width="100%" alt="02 · 当前状态 / CURRENT STATE">
</p>

**核心應用程式已實作並可執行**：`psychtool` 命令列（`init` / `import` / `claims` / `draft` / `review` / `export` / `eval` / `judge` / `dash`）+ textual 儀表板 + 彩色啟動橫幅，**66 項自動化測試通過**。**真實模型已接入**（linksub `deepseek-v4-pro`，OpenAI 相容端點）並跑通真實 `eval`：單步生成乾淨（無編造、無跨案泄漏、無矛盾化解），樸素分步基線被硬門檻捕獲跨案引用；桌面/網頁介面與 PDF/OCR 匯入延後（見 ADR 0001、ticket 12）。

本儲存庫包含：需求與邊界、官方隱私來源研究、實證證據矩陣、開發規格與實現票、兩組原創合成訓練素材，以及上述可執行的 CLI 應用程式。詳細研究文件以簡體中文為主。

**瀏覽器應用程式（本地原型）。** 除 CLI 外，本儲存庫另含本機瀏覽器原型：建立合成個案、貼上合成文字（規則式擷取候選陳述）、人工核准後經閘道送出生成請求、把產出存為段落，重新整理後仍在。**預設使用離線 FakeTransport 模型，不連網、不需 API 金鑰**；只有明確設定 `PSYCHTOOL_TRANSPORT=http` 才會走真實端點。原型**尚未符合 HIPAA**，頁面常駐橫幅亦如此提示；僅用合成資料。

```bash
cd web && bun install && bun run build   # 建置前端（FastAPI 直接供應 web/dist）
cd .. && uv run psychtool-server         # 開啟 http://127.0.0.1:8000
```

測試：

```bash
uv run --extra dev pytest -q                          # 後端
cd web && bun test && bun run build                   # 前端單元測試 + 建置
cd web && bunx playwright install chromium && bun run e2e   # 端到端（需先建置 web/dist）
```

<div id="first-workflow"></div>
<p align="center">
  <img src="./assets/readme/sec-03-first-workflow.svg" width="100%" alt="03 · 首个工作流 / FIRST WORKFLOW">
</p>

已實作（CLI 命令面）：

<div align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="五個步驟的工作流程：材料、事實清單、帶來源草稿、人工審閱門禁、匯出；來源修改使草稿回到重新核對">
</div>

<div id="evidence"></div>
<p align="center">
  <img src="./assets/readme/sec-04-evidence.svg" width="100%" alt="04 · 现有证据 / EVIDENCE">
</p>

- **OpenAlex 檢索。** 四次查詢共回傳 **35 筆去重候選紀錄**，注意事項見 [references/empirical-research.md](references/empirical-research.md)。
- **已核讀研究。** **9 項研究**完成實質核讀（4 項兒童／青少年評估、5 項 AI 臨床文書）。其中一項研究觀察到「先抽取事實再生成」的組態反而增加重大錯誤——本專案因此**不預設多步驟流程更安全**，評測將比較單步與分步方案。細節與存取邊界見 [references/empirical-research.md](references/empirical-research.md)。
- **合成訓練個案。** [fixtures/adolescent-background.json](fixtures/adolescent-background.json) 含 **2 例原創合成個案**，附來源段落定位，用於溯源與個案隔離檢查。
- **來源保真變體。** [fixtures/source-fidelity-variants.json](fixtures/source-fidelity-variants.json) 保存 **3 組配對變體**（缺失 vs 否定、第三人歸屬、簡潔性–遺漏），附期望行為。

以上文獻啟發設計判斷，不能證明本專案已減少錯誤或提升效率；目前尚無任何模型輸出效能結論。

<div id="reading-order"></div>
<p align="center">
  <img src="./assets/readme/sec-05-reading-order.svg" width="100%" alt="05 · 阅读顺序 / READING ORDER">
</p>

| 步驟 | 文件 | 確立的內容 |
|---|---|---|
| 1 | [臨床需求與設計約束](docs/clinical-requirements.md) | 使用者、範圍、審核責任與隱私約束 |
| 3 | [實證研究入口](references/empirical-research.md) | 檢索覆蓋、已核讀證據與存取限制 |
| 4 | [工作流程規格草案](docs/first-workflow-spec.md) | 首個端到端行為與驗收條件 |

更多資料入口：[HHS 來源記錄](references/hhs-sources.md) · [技能與工具選型](docs/skills-and-tools.md) · [開發規格 SPEC 0001](docs/specs/0001-first-workflow-cli.md) · [架構決策 ADR](docs/adr/) · [實現票](.scratch/first-workflow/issues/)

<div id="privacy"></div>
<p align="center">
  <img src="./assets/readme/sec-06-privacy.svg" width="100%" alt="06 · 隐私边界 / PRIVACY">
</p>

- 目前素材皆為合成、公開來源或開發者筆記，不含真實患者資料。
- 個案隔離、日誌、暫存檔、備份、網路請求與匯出副本都是**待實作並待驗證**的邊界。
- 本地執行、加密或某項工具通過檢查，均不能單獨證明 HIPAA 合規性。來源核查見 [references/privacy-research.md](references/privacy-research.md)，不構成法律意見。
- DSM 優先經學校授權入口人工查閱；APA 與 Pearson 的條款對 AI 使用有限制，閱讀權限不等於應用程式入庫權限。

<div id="next-steps"></div>
<p align="center">
  <img src="./assets/readme/sec-07-next-steps.svg" width="100%" alt="07 · 下一步 / NEXT STEPS">
</p>

1. 在真實模型上跑 `judge`（逐陳述語義支持率，獨立 judge 槽位）。
2. 為學生做圖形介面（桌面/網頁，ADR 0001 延後項）。
3. PDF/掃描件匯入（本地 Indra OCR，見 [references/ocr-tooling.md](references/ocr-tooling.md)、ticket 12）。
4. 通過評測後再評估是否導入 Harness² 最佳化工作流程，以及是否接入經許可的文獻資源。

<div id="limitations"></div>
<p align="center">
  <img src="./assets/readme/sec-08-limitations.svg" width="100%" alt="08 · 局限 / LIMITATIONS">
</p>

機構內部 AI 政策、使用者設備與偏好仍為未知；證據核讀受存取條件限制，未完成全面的勘誤清查；未附帶開源授權，**保留所有權利**。本文件結構以本地渲染為驗證依據。
