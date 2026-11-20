# 02: 启动横幅

**What to build:** 裸运行 `psychtool` 显示彩色 ASCII logo 横幅 + 版本 + 当前 `data_tier` 状态 + 命令列表。`synthetic` 绿色、`real` 红色并在顶部追加网络禁用警示行。终端无颜色时降级纯文本。

**Blocked by:** 01（需配置与 data_tier）

**Status:** ready-for-agent

- [ ] ASCII logo 字形存为仓库内文本文件，随版本管理
- [ ] 横幅含版本号、data_tier 状态、命令列表
- [ ] `real` 档显示红色 + 网络禁用警示行；`synthetic` 显示绿色
- [ ] `NO_COLOR` / 非 TTY 环境下降级为纯文本，无 ANSI 转义
- [ ] `--no-dash` 标志存在（本票只验证横幅，dash 由 10 号票实现）

## Comments

- 2026-11-06：实现完成，新增 5 测试、全套 64/64 通过。提交 `c3e49c3`。`render_banner`：synthetic 绿 / real 红 + 网络禁用警示；`NO_COLOR` 或非 TTY 降级纯文本无 ANSI；logo 字形存 `banner/logo.txt` 随版本管理。裸跑 `psychtool` 经 typer `invoke_without_command` 回调显示横幅 + `--no-dash` 跳过（dash 占位提示，ticket 10 接入）。
