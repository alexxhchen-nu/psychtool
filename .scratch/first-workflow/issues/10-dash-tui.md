# 10: dash TUI 仪表盘

**What to build:** 基于 `textual` 的 ASCII TUI 仪表盘，是第一阶段主要交互界面：工作区列表、候选陈述核对、冲突标注、草稿与来源跳转、评测结果一览。与启动横幅同一配色。命令行子命令与 dash 功能对等。

**Blocked by:** 03、04、05、07（需核心功能与导出）

**Status:** ready-for-agent

- [ ] 能启动并渲染工作区列表、陈述、冲突、草稿/来源、评测结果面板
- [ ] 核对与标注操作可在 TUI 内完成，与命令行对等
- [ ] 配色与启动横幅一致
- [ ] 快照/冒烟测试：能启动、主要面板可渲染；不重复测核心逻辑
- [ ] TUI 崩溃不影响命令行子命令可用

## Comments

- 2026-11-06：实现完成，新增 2 冒烟测试、全套 66/66 通过。提交 `e1e4111`。`DashApp`（textual）三标签页：候选陈述 DataTable（v/c/p 键核对状态）、审阅（review_summary）、草稿（list_drafts）；靛蓝主题与横幅一致。`dash <工作区>` CLI 命令；裸跑横幅提示 `psychtool dash <路径>`。TUI 仅在 `dash_cmd` 内惰性导入 textual，不影响其他命令冷启动。冒烟测试用 `run_test`，只验挂载渲染不重测核心逻辑。
