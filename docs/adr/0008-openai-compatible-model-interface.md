# ADR 0008：模型接入仅经 OpenAI 兼容端点，提示词文件入库

日期：2026-11-06。状态：已确认（用户 2026-11-06 答复 Q8）。

## 决策

所有模型调用经单一 OpenAI 兼容 transport，但业务代码不能直接调用它。调用必须依次经过完整请求准备、审批和 `send_approved` 严格出口。配置三项：`base_url`、`api_key`（环境变量，不入库）、`model`。云端网关与本地运行时（llama.cpp / Ollama 的 OpenAI 兼容模式）共用此接口切换。提示词模板为仓库内文件，随版本管理。

准备阶段冻结实际 outbound envelope（完整 messages）、provider/model、用途、data tier、来源版本和标识符类别，并生成规范 SHA-256 hash。该脱敏后的完整 envelope 是 workspace 内的审批预览；审批绑定其 hash，任何相关内容或路由变化都会使旧审批不可复用。hash 排除 status、reviewer、approval reason 与 timestamps 等生命周期元数据。可逆 token map、API key 与响应正文不属于请求记录或 hash 输入，token map 不持久化。

## 理由

- 不绑定供应商；合成阶段云端、真实数据阶段本地，同一代码路径。
- `api_key` 只从环境变量读，配合 ADR 0003 的端点限制与逐请求审批控制网络出口。
- `real` 的 local-only 限制仍然有效，且每个请求都需人工审批；`synthetic_auto` 必须显式选择并记录原因，不能伪装成人工审批。
- 提示词入库使其变更可审计、可 diff——提示词是本系统的行为规格的一部分。

## 后果

- transport 只接受已持久化、已批准且 hash 匹配的请求；业务调用面只通过 `send_approved` 触达。`data_tier: real` 时严格出口继续拒绝非本地端点。
- 安全事件只序列化 request ID、hash、purpose、tier、provider/model、标识符类别、status、reviewer_fingerprint（批准记录 reviewer 的小写 SHA-256）、timestamps 和固定错误类别；不得记录 reviewer 原文、envelope message content、响应正文、标识符原值、token map 或 API key。
- 提示词文件变更视为行为变更，需在 WORKLOG 记录并跑 `eval`。
- 该出口门与安全事件约束不是 HIPAA 合规证明；供应商/BAA、保留训练政策和部署环境仍需独立审查。
