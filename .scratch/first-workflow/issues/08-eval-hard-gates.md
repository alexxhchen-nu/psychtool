# 08: eval + 硬门槛

**What to build:** `eval` 在冻结 fixture 上分别运行单步生成与「抽取→生成」两种方案，输出结构化报告（JSON + 可读摘要，含 fixture 版本指纹）。硬门槛纯代码判定、失败即阻断：跨个案泄漏、编造关键事实、矛盾静默消失、来源失效后沿用旧确认状态。

**Blocked by:** 04（候选陈述）、05（草稿）、06（失效）

**Status:** ready-for-agent

- [ ] 冻结 fixture 作为只读输入，报告含其版本指纹
- [ ] 单步 vs 分步两种方案同输入分别运行
- [ ] 四项硬门槛纯代码实现，任一触发即标记阻断
- [ ] 报告含逐项指标值、判定依据指针
- [ ] 遗漏、归属、跨区泄漏分别计数，不被「无幻觉」掩盖

## Comments

- 2026-11-06：实现完成，新增 6 测试、全套 52/52 通过。提交 `824a288`。四项硬门槛纯代码：`gate_forbidden`（forbidden_claims 子串）、`gate_leakage`（他案 case_id/claim 句）、`gate_conflict`（未决 topic 单值化解）、stale（复用 review 模块验证来源失效检测，`detected=True` 视为正确而非阻断）。`blocked` 仅由 forbidden/leakage/conflict 触发。报告含 SHA256 前 16 位指纹。单步/分步经 `run_case` 同输入分别运行，分步为朴素「抽取→生成」基线（抽取原文透传，不解析结构化 claim——结构化抽取留待后续）。`eval` CLI 命令已接线。
