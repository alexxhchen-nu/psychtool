# 模型出口门设计

日期：2026-11-08  
状态：已批准（用户于 2026-11-08 确认）  
范围：psychtool 的模型请求准备、预览、审批、发送和最小审计记录

## 意图

psychtool 已有上传时脱敏、claim 级脱敏和单一模型网络出口，但 Web 生成接口仍会在一次请求中直接组装 prompt 并调用模型。当前实现无法证明人工看到的内容与实际发送内容完全一致，也无法保证 `instructions`、claim metadata、CLI、judge 或未来调用点不会形成旁路。

本设计把模型调用改为可验证的两阶段流程：先构建并冻结最终模型请求，再按数据档决定人工批准或显式自动放行，最后由唯一 gateway 验证批准记录与内容 hash 后发送。

目标是建立工程门禁，不把自动脱敏或该门禁描述为 HIPAA 合规证明。

## 为什么现在做

上传入口已经先解析、脱敏再持久化，但模型出口仍缺少完整请求检查。继续扩展正则或修改单个 endpoint 不能解决系统级旁路。当前优先事项是先固定 harness，再增加模型、OCR 和更多数据评测。

## 已确认的策略

- `data_tier="real"`：每个模型请求都必须由人工 reviewer 明确批准。
- `data_tier="synthetic"`：允许显式配置的自动放行，用于冻结评测和开发测试；自动放行必须在记录中可区分，不得伪装成人工批准。
- 未批准、批准失效、完整请求仍含阻断级标识符或 hash 不一致时，网络调用次数必须为零。
- token map 保持本地，不进入模型请求、审批记录或日志。

## 目标

1. 所有模型调用经过同一个可执行出口门。
2. 扫描和批准对象是最终完整 prompt，而非其中某个字段。
3. 发送内容与批准预览逐字一致。
4. 请求输入、来源版本、provider、model 或 prompt 变化后，旧批准自动失效。
5. 日志只记录最少必要 metadata，不记录 prompt、标识符原值或 token map。
6. 保留合成评测的批量运行能力。
7. 先提供后端闭环和测试，再实现 Web 审批界面。

## 非目标

- 本阶段不实现身份提供商、组织级 RBAC、SSO 或完整授权系统。
- 本阶段不接入新的模型供应商。
- 本阶段不提高 OCR 准确率。
- 本阶段不声称自动去标识化满足 Safe Harbor、Expert Determination 或 HIPAA 合规要求。
- 本阶段不建立通用规则 DSL、复杂策略引擎或完整事件溯源平台。
- 本阶段不把原始上传文件、完整解析文本或 token map 交给模型。

## 反目标

即使功能表面可用，出现下列任一情况也视为失败：

- 某个 CLI、Web、judge、eval 或新调用点可以直接向 transport 传递任意字符串。
- reviewer 批准后，请求内容可以变化但继续发送。
- 日志、异常消息或审批记录包含敏感原文。
- `synthetic` 自动放行被记录为人工批准。
- 客户端可以通过 `redact=false` 关闭真实资料的出口检查。
- 失败路径发生网络调用。

## 当前实现与约束

### 当前调用链

```text
Web / CLI / eval / judge
  → prompt builder
  → gateway.client.complete(prompt, config, transport)
  → http_transport(config, prompt)
  → provider
```

### 已存在的能力

- `psychtool/gateway/client.py` 是模型网络单一出口，并按 `data_tier` 限制 endpoint。
- `psychtool/core/redact.py` 提供标识符检测、token 化和本地恢复。
- `generate_section()` 与 `generate_draft()` 可以脱敏 claim 正文。
- 配置与模型调用可注入，现有测试不会访问真实网络。

### 已确认缺口

- `complete()` 接收普通字符串，不携带审批或 hash 证据。
- Web `GeneratePayload.redact` 可由客户端关闭。
- `instructions` 未被现有 claim 脱敏流程覆盖。
- claim metadata 会进入 prompt，但没有对最终 prompt 做统一扫描。
- `/generate` 当前在一次请求中直接调用模型。
- CLI `draft`、`eval` 和 `judge` 同样可以调用 `complete()`。

## 考虑过的方案

### 方案 A：只修改 Web `/generate`

在 endpoint 内增加脱敏、预览和批准参数。

优点：改动最少。  
缺点：CLI、eval、judge 和未来调用点仍可绕过；无法形成全局不变量。  
结论：不采用。

### 方案 B：两阶段统一出口门

所有调用先产生不可变 `EgressRequest`，再由 gateway 验证状态和 hash 后发送。

优点：旁路最少；预览与发送内容可验证一致；符合现有单一 gateway 设计。  
代价：需要调整现有调用签名，并为 Web 增加准备、批准、发送三个动作。  
结论：采用。

### 方案 C：通用策略引擎与事件溯源

建立规则 DSL、角色策略、多级审批和完整事件总线。

优点：长期扩展性高。  
缺点：当前需求不足以支撑复杂度，扩大攻击面和维护成本。  
结论：本阶段不采用。

## 核心模型

### `EgressRequest`

建议放在 `psychtool/gateway/egress.py`，由 Pydantic 模型表达：

```text
request_id
workspace_id
purpose
provider
model
data_tier
redacted_prompt
identifier_categories
source_refs
content_hash
status
approval_mode
reviewer
prepared_at
approved_at
sent_at
```

字段约束：

- `request_id`：随机、不含 case 或患者信息。
- `workspace_id`：使用内部匿名 workspace 标识；不得写入标题或姓名。
- `purpose`：有限枚举，例如 `section_generation`、`draft_generation`、`judge`、`eval`。
- `source_refs`：只保存 claim ID、claim version、material ID/version 等版本引用，不保存正文。
- `redacted_prompt`：仅保存在受控请求存储中，用于预览和发送；不得进入普通日志。
- `identifier_categories`：只记录类别，不保存命中原值。
- `content_hash`：对 transport 将实际发送的规范化 envelope 计算 SHA-256，至少覆盖 system/user messages、prompt、provider、model、purpose、source refs、数据档及会影响供应商处理的参数；不能只对预览字符串计算近似 hash。
- `approval_mode`：`human` 或 `synthetic_auto`。

### 状态机

```text
prepared → approved → sent
    │          │
    └──────────┴→ invalidated
```

规则：

- `prepared`：请求已完成最终组装、脱敏和扫描，尚未发生网络调用。
- `approved`：批准绑定当前 `content_hash`。
- `sent`：gateway 已验证 hash、状态和数据档，并完成一次 transport 调用。
- `invalidated`：来源版本、prompt、provider、model、数据档或审批上下文变化。
- 不允许从 `sent` 回退或重复发送同一个请求；重试必须创建新的 attempt 或明确的幂等发送记录。

## 完整请求准备

请求准备必须先组装最终 prompt，再统一处理：

1. 读取已选择并满足现有来源门禁的 claims。
2. 组装完整 prompt，包括 instructions、claim metadata 和模板文本。
3. 使用 workspace `known_names` 对完整 prompt 执行 `redact_text()`。
4. 对脱敏后的完整 prompt 再执行 `find_identifiers()`。
5. 如仍存在阻断级命中，返回阻断结果且不创建可发送批准。
6. 生成预览、来源引用、标识符类别和 `content_hash`。
7. token map 只在本地调用链中用于模型输出恢复；不得写入 `EgressRequest` 持久化文件。

第一版不尝试自动判断所有独特叙事能否重识别。预览必须明确提示人工 reviewer 检查自动检测覆盖不到的姓名、地点和独特事件。

## 批准策略

### `real`

- 只接受 `approval_mode="human"`。
- reviewer 必填，且不能为空白字符串。
- 批准动作记录 reviewer、时间和批准时的 `content_hash`。
- 客户端不能通过请求参数关闭脱敏、扫描或批准。
- 当前阶段 reviewer 是明确填写的审阅者标识；身份验证和 RBAC 留到后续阶段，因此 UI 不得把该字段描述为经过身份验证的电子签名。

### `synthetic`

- 默认仍产生可检查预览。
- 冻结 eval 或开发测试可显式选择 `approval_mode="synthetic_auto"`。
- 自动放行记录必须包含调用目的和自动放行原因。
- 自动放行不得用于 `real`，gateway 必须硬拒绝。

## Gateway 不变量

`complete()` 不再接收可直接发送的普通 prompt 字符串。最终目标接口只接受已经批准的请求对象或不可伪造的已批准请求引用。

发送前必须：

1. 重新读取请求记录。
2. 验证状态为 `approved`。
3. 重新计算实际发送 envelope 的 hash。
4. 验证批准 hash 与当前 hash 一致。
5. 验证 `real` 只能使用人工批准。
6. 继续执行现有 endpoint/data-tier 限制。
7. 只在全部检查通过后调用 transport。
8. 记录最小发送结果，不记录 prompt 或响应正文。

为减少迁移风险，可先新增严格接口并迁移所有调用点，确认代码库中没有旧接口调用后再删除旧签名。过渡期的旧接口必须默认拒绝，不能静默放行。

## API 形态

后端第一版建议拆为：

```text
POST /api/workspaces/{case_id}/egress/prepare
GET  /api/workspaces/{case_id}/egress/{request_id}
POST /api/workspaces/{case_id}/egress/{request_id}/approve
POST /api/workspaces/{case_id}/egress/{request_id}/send
```

### Prepare

输入：template、section、claim IDs、instructions、purpose。  
输出：request ID、完整脱敏预览、identifier categories、source refs、provider、model、hash、状态和人工复核提示。  
行为：不调用模型。

### Approve

输入：reviewer 和客户端看到的 `content_hash`。  
行为：只有服务端当前 hash 与客户端 hash 一致时批准。

### Send

输入：request ID。  
行为：重新验证状态和 hash 后调用 gateway；返回模型输出。模型输出恢复 token 后仍需执行输出侧标识符检查，发现异常时阻断返回并保留最小错误记录。

现有 `/sections/{section_id}/generate` 在迁移后不再直接调用模型。可暂时返回明确的迁移错误或内部改为仅 prepare，但不得保留隐式直接发送行为。

## 存储与日志

建议 workspace 内新增受控目录，例如 `egress/`，保存请求状态。第一版可用版本化 JSON，保持与现有 workspace 文件模式一致。即使经过自动脱敏，完整叙事仍可能具有重识别风险，因此该目录必须沿用受控 workspace 的访问、保留和删除边界，不能作为普通调试产物复制或记录。

普通日志允许记录：

- request ID
- purpose
- data tier
- provider/model 标识
- content hash
- identifier categories
-状态变化
- reviewer 标识及时间
- 错误类别

普通日志禁止记录：

- prompt
- 模型响应正文
- 标识符原值
- token map
- API key
- 上传文件内容

错误消息必须使用错误代码和类别，不拼接 prompt 或 provider 返回的敏感正文。

## 输出处理

模型输出可能复制 token、生成新标识符或产生未经支持的内容。发送完成后：

1. 对原始模型输出执行标识符扫描。
2. 仅用当前本地 token map 恢复已知 token。
3. 对恢复后文本执行第二次扫描和现有来源/评测门禁。
4. 高风险命中时不直接返回可保存正文，而是返回阻断状态供人工检查。

第一版的重点是防止未经批准的输入外发；输出门禁保持最小、明确，不在本阶段扩展成完整临床质量审核系统。

## 兼容与迁移顺序

1. 新增纯数据模型、hash 计算和状态转换，不接网络。
2. 新增 prepare 流程，复用现有 prompt builder 和 redaction。
3. 新增 human approval 与 synthetic auto approval。
4. 让 gateway 只发送批准请求。
5. 迁移 Web section generation。
6. 迁移 CLI draft。
7. 迁移 judge 和 eval；冻结 synthetic eval 使用显式自动放行。
8. 全仓搜索并删除普通字符串直达 transport 的调用方式。
9. 最后实现 Web 预览和批准界面。

## 测试设计

### 单元测试

- 同一规范化 envelope 产生稳定 hash。
- prompt、provider、model、purpose 或 source version 任一变化都会改变 hash。
- `real + synthetic_auto` 被拒绝。
- reviewer 为空时人工批准被拒绝。
- 未批准、失效或已发送请求不能发送。
- 失败状态下 transport 调用次数为零。
- 日志序列化不包含 prompt、token map 或命中原值。

### 完整请求测试

- 标识符位于 claim text、instructions、metadata 时均被统一处理。
- `redact=false` 无法关闭 `real` 的出口处理。
- 自动扫描后仍有阻断级命中时不能批准。
- 批准后修改一字即失效。
- 预览 prompt 与 transport 收到的 prompt 完全相等。

### 调用面测试

- Web、CLI draft、judge 和 eval 均经过严格 gateway。
- 代码库不存在直接调用 `http_transport()` 的业务路径。
- synthetic eval 只能通过明确的 `synthetic_auto` 路径批量运行。

### 回归测试

- 现有本地 endpoint 限制继续生效。
- 已有 claim 来源/version 检查继续生效。
- 现有冻结 synthetic fixtures 可重复运行。
- 模型未配置时错误不泄露 prompt 或 key。

## 验收标准

1. 所有模型 transport 调用都能追溯到一个批准的 `EgressRequest`。
2. `real` 请求没有人工批准时，transport 调用次数恒为零。
3. synthetic 自动放行被明确标记，且无法用于 real。
4. 批准预览与实际发送 envelope 的 hash 一致。
5. 任一受保护输入或模型配置变化都会使批准失效。
6. prompt、响应正文、标识符原值和 token map 不进入普通日志。
7. Web、CLI、judge、eval 的旁路测试全部通过。
8. 文档和 UI 继续明确：该机制降低外发风险，但不等于 HIPAA 合规证明。

## 实施后的下一阶段

出口门后端和测试稳定后，再依次完成：

1. Web 预览与人工审批界面。
2. 身份验证、访问控制和 reviewer 身份绑定。
3. Indra PDF/图片 OCR 质量评测。
4. 基于公开讨论的一般叙事模式编写原创合成案例。
5. 使用冻结案例开展模型比较与改进。

## 留给实施者的具体判断

以下属于实现细节，可在不改变设计的前提下决定：

- 版本化 JSON 的具体文件名和目录辅助函数。
- Pydantic 模型拆分方式。
- hash envelope 的规范 JSON 序列化实现。
- 具体错误类和 HTTP 状态码。
- token map 在 prepare 到 send 之间的短生命周期承载方式；如果跨请求无法安全保留，第一版可以让模型输出保留语义 token，不自动恢复原值，而不是持久化 token map。
