# ADR 0023：桌面啟動器，以及斷網／保存失敗／服務未起的文案

日期：2026-11-25。狀態：已確認（PT-14 / Linear GROK-44；Q5 已於 2026-11-24 定案）。

## 決策

M1 用兩個**無額外依賴**的腳本作為非技術使用者的啟動方式，不打包安裝程式、不引入 Electron 或 Frozen 二進位：

- `launchers/Start Psychtool.command`：在 macOS Finder 中雙擊（以 `sh` 撰寫；Linux 上可用同一腳本做自動化測試，但不作為交付承諾）。
- `launchers/Start Psychtool.cmd`：在 Windows 檔案總管中雙擊。

腳本把工作目錄設為倉庫根目錄（`launchers/` 的上一層），假設部署者（Q1：Alex）已安裝好含 `uv` 或 `.venv` 的副本。啟動器**不會**安裝 Python、uv 或套件。它啟動既有的 `psychtool-server`（綁定 127.0.0.1，埠為 `PSYCHTOOL_PORT` 或 8000），等到 `/api/health` 回應後用系統瀏覽器打開該位址。工作階段權杖由伺服器注入已提供的頁面，啟動器不會列印權杖。若該埠上服務已在執行，只打開瀏覽器。若找不到執行環境或服務未能就緒，則以普通語言提示她聯繫安裝者，不要求她設定工作目錄或環境變數。

本機回環上、經人工批准的模型呼叫在 `real` 檔下仍依 ADR 0003 允許；本卡不改該規則。即時 Vertex「生成一章」已改期至 PT-24，本卡不做。

## 文案（逐字）

以下兩條取自 tech-design.md 第 7 節（2026-11-24 定稿）與第 8.1 節 Q5，必須與原文位元組一致：

- 斷網："You're offline. Your saved work is safe on this computer. Sending to the AI assistant will work again when you're back online."
- 保存失敗："We couldn't save this section. Your text is still here. Copy it somewhere safe, then try Save again."

保存失敗時編輯區文字必須保留。4xx 且伺服器已回傳允許列出的草稿過濾說明（例如 Summary 拒絕）時，仍顯示該說明，以免掩蓋已有的拒絕原因。其他保存失敗（含網路中斷與 5xx）使用上面的保存失敗原文。

服務尚未啟動（R1-AC3）時顯示（本 ADR 定稿，§7 未指定句）：

- "The writing workspace isn't running on this computer. Double-click Start Psychtool, then reload this page. If that doesn't help, ask the person who installed it."

瀏覽器離線時優先顯示斷網文案，而不是服務未起文案。可見狀態文字不使用 API、JSON 或 token 等技術詞。空個案提示不再出現命令列或工作目錄設定說明。

## 未驗證範圍（誠實列出）

本卡以 Linux 上的腳本測試（含啟動假的健康檢查與記錄「打開瀏覽器」的 URL）以及字串／介面測試來驗證。**未**在真實的 macOS Finder 或 Windows 檔案總管中雙擊過；**未**驗證 macOS Gatekeeper 或隔離屬性（quarantine）；**未**驗證 Windows SmartScreen。未在 CI 增加 windows/macos 執行器矩陣（成本與完整安裝堆疊不成比例，且仍無法代替上述真實雙擊檢查）。

## 後果

- 部署者仍須先準備好本機副本；啟動器不是安裝程式。
- 本控制不是 HIPAA 合規證明；僅用合成資料。
