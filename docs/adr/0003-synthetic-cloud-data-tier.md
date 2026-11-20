# ADR 0003：合成阶段允许云端模型 API，`data_tier` 硬开关

日期：2026-11-06。状态：已确认（用户 2026-11-06 答复 Q3）。

## 决策

合成材料（`data_tier: synthetic`）评测阶段允许调用云端模型 API。配置中设置硬开关 `data_tier: synthetic | real`：

- `synthetic`：仅在请求被明确标记为 `synthetic_auto`（并记录非空原因）或经人工审批后允许网络调用；不得把自动放行表示为人工审批。
- `real`：原有 local-only 限制继续有效，拒绝非本地端点；即使目标是本地端点，每次完整请求仍必须单独人工审批。任何真实资料接入前，必须重新确认 `docs/clinical-requirements.md` 的隐私边界并记录确认。

审批层叠加在端点网络策略之上，不替代或放宽原有 `real` 限制。发送前必须冻结完整 outbound envelope 及路由、用途、data tier、来源版本和标识符类别，并以规范 SHA-256 hash 绑定审批；任一审批相关内容变化都须重新准备和审批。可逆 token map 不进入该请求记录、hash 输入或普通日志，也不持久化。

## 理由

- 隐私边界针对真实个案资料；完全虚构的 fixture 不触碰该边界。
- 首轮评测要比较单步 vs 分步生成，云端模型质量稳定，避免把「本地小模型能力不足」误读为「流程不安全」。
- 硬开关使边界可执行而非靠自律。

## 后果

- 实现时网络访问必须收敛到严格出口：只有持久化且与 hash 匹配的 approved request 可触达 transport；测试须覆盖 `real` 档非本地网络调用被拒。
- 切换数据档与 `synthetic_auto` 都是显式操作，需写安全事件；事件只记录 allowlisted 元数据，不记录 prompt、响应正文、标识符原值、token map 或 API key。
- 完整脱敏请求预览保存在受控 workspace，用于逐请求审批；普通日志不得复制其 message content。
- 云端供应商、BAA、保留与训练政策及实际部署仍须另行审查，届时按 `references/privacy-research.md` 执行。
- 这些控制不是 HIPAA 合规证明，也不能替代机构、供应商或部署审查。
