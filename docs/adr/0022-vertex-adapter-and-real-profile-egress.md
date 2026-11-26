# ADR 0022：Vertex AI Gemini 適配器，以及 `real` 檔出網拒絕

日期：2026-11-25。狀態：已確認（PT-13 / Linear GROK-43；Q2 已於 2026-11-24 定案）。

## 決策

M1 的雲端模型路徑只走 **Vertex AI Gemini**，經既有 OpenAI 相容信封（ADR 0008）發送。**Google AI Studio / Gemini Developer API 不是支援路徑**，即使在合成檔也一律拒絕，日後簽署 BAA 不必換介面（tech-design Q2）。

命名設定檔（`PSYCHTOOL_PROFILE`）為 `fake`（預設，離線 FakeTransport）、`vertex`（合成檔、Vertex 端點）與 `real`（`data_tier=real`）。Vertex 的存取權杖只來自 `PSYCHTOOL_VERTEX_ACCESS_TOKEN`，或由測試注入的 `token_provider`。執行期**不會探測** Application Default Credentials，也不從設定檔或磁碟讀取金鑰。

## `real` 檔出網測試的解讀（最嚴）

完成標準要求「`real` 檔出網測試被拒」。本 ADR 採用最嚴、且與 ADR 0003 一致的讀法：

- 在正式執行與 CI／測試中，`profile=real` / `data_tier=real` **一律拒絕非本機端點**（Vertex、AI Studio、任何雲端 URL）。在輸送層被呼叫之前就失敗，並以 socket egress guard 證明沒有建立連線。
- M1 **沒有 BAA 旗標或設定項**可以把 `real` 檔的雲端外發送開。切換資料檔不能偽裝成已簽約。
- 本機回環（`127.0.0.1` / `localhost`）在 `real` 檔下仍可依 ADR 0003 經逐筆人工批准後使用；本卡不取消這條既有規則。

若 Alex 的原意是「連本機 socket 也不允許」，那是一個比 ADR 0003 更嚴的範圍，列為待確認問題，本卡不自行加嚴。

## 其他重申

- 準備階段凍結並預覽**去標識後**的完整模型輸入；批准綁定內容雜湊，批准後任何相關變更都使舊批准不可用。
- 投遞結果不確定或輸出被攔截時，同一請求不得重發；被攔截的不完整正文不得當作可用草稿。
- 測試只針對假的／被 mock 的 Vertex 用戶端，並安裝 egress guard。用 A-001「真生成一章」的即時 Vertex 呼叫超出本卡範圍，直到 Alex 提供專案、區域、型號與驗證方式。

## 後果

- `PSYCHTOOL_TRANSPORT=http` 若指向 AI Studio 主機，輸送層會拒絕，不會發出請求。
- 本控制不是 HIPAA 合規證明；供應商／BAA、保留與訓練政策及部署環境仍須獨立審查。
