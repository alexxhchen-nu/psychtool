# 01: 脚手架 + 配置 + data_tier 网络门

**What to build:** 建立 `psychtool` Python 包骨架与单一模型网关出口。配置项 `base_url` / `api_key`（仅环境变量）/ `model` / `data_tier`。`data_tier: real` 时任何非本地网络调用被拒绝，`synthetic` 时放行。网关用假传输桩测试，不碰真 API。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `pyproject.toml` 定义包、依赖（pydantic、typer、rich、textual、pytest），核心库不 import rich/textual
- [ ] 配置从环境变量 + 配置文件读取，`api_key` 只允许来自环境变量
- [ ] 单一网关出口函数；`data_tier: real` 下网络调用抛错、`synthetic` 下经假传输返回
- [ ] 假传输测试覆盖放行/拒绝两态
- [ ] 核心库无网络、无 rich/textual 导入（导入级断言测试）

## Comments

- 2026-11-06：实现完成，10/10 测试通过（`tests/test_config.py`、`test_gateway.py`、`test_imports.py`）。提交 `394af47`。核心库导入洁净性测试改用快照前后 diff，避免环境预加载 `rich` 的误报。
