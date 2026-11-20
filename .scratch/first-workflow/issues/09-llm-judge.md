# 09: LLM judge 语义支持率

**What to build:** 独立的 judge 模型槽位对逐条陈述的语义支持打分；judge 提示词与每条原始判定存档可复查。judge 判定不作为唯一真值，配合人工抽检。

**Blocked by:** 05（草稿）、08（eval 骨架）

**Status:** ready-for-agent

- [ ] judge 与生成模型为两个独立配置槽位
- [ ] 逐陈述支持率打分，判定原文存档到报告
- [ ] 存档含 fixture 版本、陈述 ID、判定与依据指针
- [ ] judge 提示词为版本化文件
- [ ] 报告标注「judge 非唯一真值，需人工抽检」

## Comments

- 2026-11-06：实现完成，新增 6 测试、全套 59/59 通过。提交 `6a89237`。`judge_draft` 对草稿每条 citation 经独立 judge 模型判定支持/不支持/不明，判定 + 解释 + 支持率写入 `judgements/<draft_id>.vN.json`（含 context 里可带 fixture 指纹），并标注「judge 非唯一真值，需人工抽检」。judge 与生成模型为独立槽位（`judge_model`，`PSYCHTOOL_JUDGE_MODEL`，缺省回退 model）。`parse_verdict` 先试 JSON 再关键字回退。`judge` CLI 命令已接线。
