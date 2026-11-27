# ADR 0024：合成個案 A-001 的即時 Vertex 章節檢查（雙重選擇加入）

日期：2026-11-27。狀態：已確認（PT-24 / Linear GROK-56）。

## 決策

「用合成個案 A-001 對即時 Vertex AI Gemini 生成一章」是一條**獨立、僅供本機手動、須雙重選擇加入**的路徑，與產品預設輸送層分開：

- 必須同時具備環境旗標 `PSYCHTOOL_LIVE_VERTEX=1` 與命令列旗標 `--opt-in`。任一缺失，都在構造客戶端之前拒絕。
- 驗證方式是 Application Default Credentials（`gcloud auth application-default login`）。本路徑不使用、也不要求服務帳戶金鑰，也不讀取 `PSYCHTOOL_VERTEX_ACCESS_TOKEN`。
- 只接受合成夾具 `fixtures/case_a001`（`case_id=case-a001`，`data_tier=synthetic`）。夾具會複製到暫存工作區，倉庫內的正本永不寫入。
- 預設模型為官方 GA 型號 ID `gemini-4-hydrogen`（來源：[Gemini 4 Hydrogen 開發者指南](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-hydrogen)，2026-11-27 查閱）。可用環境變數或旗標覆寫。
- 預設專案 `fb-ailogic26vrt-3252`、預設區域 `global`，皆可由環境變數或旗標覆寫。設定裡不硬編碼任何機密。
- 產出仍走既有的逐句核引用（`citecheck_text`）與用語攔截（`check_draft_text`）。結束時列印 cited／uncited 句數、攔截結果、token 用量，以及費用估計。
- 費用估計採用官方 [Agent Platform / Model Garden 定價頁](https://cloud.google.com/model-garden/pricing)（2026-11-27 查閱）中 Gemini 4 Hydrogen 的 **Standard PayGo、Global** 標價：輸入每百萬 token 1.50 美元，輸出（含回應與推理）每百萬 token 7.50 美元。同一頁另有較高與較低的表（看起來像 Priority 與 Batch），本路徑不猜測那些費率；若模型或區域不是上述組合，估計標為 unknown。
- 生成的章節文字寫入本機檔案，並列印絕對路徑。預設路徑為已被 gitignore 的 `local-data/live-vertex/case-a001-history.txt`，可用 `--output` 或 `PSYCHTOOL_LIVE_VERTEX_OUTPUT` 覆寫。若目標在倉庫內且不被 gitignore，寫入會被拒絕，以免檔案進入 git。
- 呼叫一律帶上輸出上限與請求逾時：預設 `max_output_tokens=8192`、逾時 120 秒，可用旗標或環境變數覆寫（`--max-output-tokens`／`PSYCHTOOL_LIVE_VERTEX_MAX_OUTPUT_TOKENS`，`--timeout-seconds`／`PSYCHTOOL_LIVE_VERTEX_TIMEOUT_SECONDS`）。這兩個值會傳入 google-genai 的 `GenerateContentConfig.max_output_tokens` 與 `HttpOptions.timeout`（毫秒）。為避免 SDK 預設最多 5 次嘗試把上限與逾時放大，本路徑將 `HttpRetryOptions.attempts` 設為 1（官方說明：0 或 1 表示不重試）。
- 摘要同時列出呼叫前的最壞費用（輸入依 4 字元／token 估算，輸出按上限計）以及實際 usage 的費用。若模型因觸及 `max_output_tokens` 而截斷，或請求逾時，結果為 FAIL，但仍對已收到的文字（可能為空）套用引用與用語攔截。
- 此命令**不在 CI 執行**。`google-genai`（`>= 2.34.0`）是可選 extra `live`，預設測試與 CI 不安裝它。離線測試以注入的假生成函數覆蓋設定解析、雙重選擇加入、`real` 檔拒絕、摘要算術、上限接線、輸出檔寫入，以及引用／攔截被套用（含截斷與逾時）。

## 與 ADR 0022 的關係

**本決策不修改 ADR 0022。**

- 既有的 `vertex` 輸送層仍只使用 `PSYCHTOOL_VERTEX_ACCESS_TOKEN` 或測試注入的 `token_provider`，執行期仍不探測 Application Default Credentials。
- `profile=real` / `data_tier=real` 在正式路徑上仍拒絕非本機端點，且沒有 BAA 旗標可放行。本即時路徑在這兩個值為 `real` 時即使雙重選擇加入也一律拒絕。
- Google AI Studio / Gemini Developer API 仍不是支援路徑。

本機回環上、經人工批准的模型呼叫在 `real` 檔下仍依 ADR 0003 允許；本卡不改該規則。

## 後果

- 操作者（Alex）在自己的 Windows 電腦上、以暫時實驗室帳戶完成 `gcloud auth application-default login --project fb-ailogic26vrt-3252` 之後，可用一條命令手動跑這次檢查。本倉庫的代理與 CI **從不**發出這次即時呼叫，也不尋找或使用任何 Google Cloud 憑證。
- 這不是 HIPAA 合規證明，也不是已對真實來訪者資料開通雲端路徑。
- Linear GROK-56 早期文字提到「以遮罩表單收集憑證」；2026-11-27 的批准改為 ADC、不使用服務帳戶金鑰。以本 ADR 為準。

## 未驗證

- 以真實 ADC 對 Vertex 發出「生成一章」的呼叫本身，須由 Alex 在本機執行後才能算完成。本卡只提供選擇加入的命令與離線測試。
