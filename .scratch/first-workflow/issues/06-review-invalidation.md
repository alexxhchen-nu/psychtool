# 06: 来源失效 + review

**What to build:** 修改来源产生新版本后，依赖该来源的候选陈述与草稿被标记为需重新核对，旧确认状态失效。`review` 命令列出冲突、缺口与失效引用，供导出前审阅。

**Blocked by:** 04（候选陈述）、05（草稿）

**Status:** ready-for-agent

- [ ] 来源升级为新版本后，关联陈述与草稿的已核对状态失效
- [ ] 旧来源定位仍可查看，但不再被当作当前确认依据
- [ ] `review` 汇总冲突、证据缺口、失效引用
- [ ] 失效状态变更持久化为版本化文件

## Comments

- 2026-11-06：实现完成，新增 7 测试、全套 38/38 通过。提交 `db4ae43`。`find_stale_claims` 按「陈述 source_version != 材料当前版本」判定失效；`reopen_stale_claims` 将已核对失效陈述打回 `pending` 并写新版本，旧定位保留；`review_summary` 汇总 stale_claims/conflicts/pending/stale_drafts。
