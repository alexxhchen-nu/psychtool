# ADR 0002：技术栈 Python 3.12 + typer + pydantic + pytest

日期：2026-11-06。状态：已确认（用户 2026-11-06 答复 Q2）。

## 决策

主语言 Python 3.12；CLI 用 `typer`；数据校验用 `pydantic`；测试用 `pytest`。

## 理由

- 现有 fixtures 为 JSON；评测本质是文本与结构对比，Python 最合适。
- 未来 PDF 解析、OCR、本地模型（llama.cpp 绑定）、以及可选界面（streamlit/gradio）都在同一生态内。
- 最终用户不接触代码，运行时的用户友好性不构成选型约束。

## 后果

- 版本固定记录于项目配置；CI 暂不需要（私有研究阶段）。
- 若日后桌面化，评估 Tauri/Electron 包装或纯 Python 打包（如 PyInstaller）的成本。
