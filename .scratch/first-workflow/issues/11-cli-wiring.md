# 11: CLI 接线（typer 命令面）

**What to build:** 用 typer 把 core 库函数接到 `psychtool` 入口，使 ADR 0006 定义的命令面可演示：`init` / `import` / `claims` / `draft` / `review` / `export`（`eval` 由 08 号票接、`dash` 由 10 号票接、启动横幅由 02 号票接）。生成类操作带 `--max-steps` / `--max-cost`。

**Blocked by:** 03、04、05、06、07（需对应 core 模块）

**Status:** ready-for-agent

- [ ] `psychtool init <path> --case-id` 调用 `init_workspace`
- [ ] `psychtool import <path> --material-id --title --provider --date --file` 调用 `import_material`
- [ ] `psychtool claims <path> [list|add|status]` 调用 claims 模块
- [ ] `psychtool draft <path> --claim-ids --instructions --max-steps --max-cost` 经网关调用 `generate_draft`
- [ ] `psychtool review <path>` 输出 `review_summary`
- [ ] `psychtool export <path> --draft-id --out`（预览后确认）调用 `export_draft`
- [ ] 端到端测试：子进程跑真实命令，断言退出码与产物
- [ ] `--help` 对每个命令可用

## Comments

- 2026-11-06：实现完成，新增 4 个 e2e 测试、全套 46/46 通过。提交 `9ff82c2`。typer 命令全部接 core；draft 经 `gateway/http.py`（stdlib urllib、no-proxy、OpenAI 兼容）真实调用，测试用本地 mock 服务器验证。注意：e2e 子进程冷启动约 6s/次，全套 183s（无 CI，可接受）。console_script 入口 `psychtool` 需 `pip install -e .` 注册。
