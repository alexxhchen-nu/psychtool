# ADR 0009：本地 Web UI 采用 FastAPI 后端 + React (Vite + TypeScript) 前端

日期：2026-11-07。状态：已确认（用户 2026-11-07 答复：React + Vite + TypeScript，先搭 UI 骨架）。

## 决策

本地 Web UI 采用 **FastAPI 后端 + React（Vite + TypeScript）单页应用**：

- 后端 `psychtool/server`：FastAPI 提供 JSON API（`/api/*`），复用 `psychtool/core` 库。
- 前端 `web/`：React + Vite + TypeScript。
- 开发期：Vite dev server（`localhost:5173`）把 `/api` 代理到 FastAPI（`127.0.0.1:8000`）。
- 演示/生产期：FastAPI 直接服务 `web/dist` 构建产物，含 SPA 前端路由回退。

## 理由

- FastAPI 是 Python 生态，直接调用 `psychtool/core`（claims → review → draft → source index），无需重写核心逻辑，延续 ADR 0002 的 Python 3.12 栈。
- React + Vite + TypeScript 是「现代、快」的 SPA 栈中生态最成熟者：Vite HMR 即时热更，组件生态对「逐节来源高亮 / 声明→来源段落」这类交互支持最好。
- 备选 Svelte 5 更轻量但注解/表格类组件生态较小；Streamlit/Gradio 适合演示仪表盘，不适合多步工作流 UI。

## 后果

- 引入 Node 工具链（bun 或 npm）与前端独立依赖/构建，`web/` 自成工程。
- 核心逻辑保持库形式，CLI 与 Web UI 共享同一实现，界面需求由 CLI 稳定行为作为规格输入（延续 ADR 0001）。
- 首次交付仅骨架（health 接口 + 三步占位 UI），报告模板与分节模型、上传/导入、生成动作均在后续落地。
