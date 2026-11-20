# psychtool Web 端到端工作台设计

日期：2026-11-08  
状态：已实现并完成合成数据浏览器验收（2026-11-09）；真实模型质量与部署合规尚未验证
范围：材料上传、claims 复核、staged 模型出口审批、生成结果进入章节编辑器

## 意图

让 psychtool 的核心工作流第一次可以完全通过浏览器完成：上传材料、复核脱敏类别、整理 claims、选择章节来源、预览模型实际请求、批准、发送、把模型输出放入章节编辑器，再由人修改和保存。

当前 Web 已能浏览 workspace、维护 known names、复核 intake claims、编辑和保存章节，但两个 Generate 按钮仍调用已废弃的 `/sections/{section_id}/generate`，因此固定收到 410。后端已经提供严格的 prepare/get/approve/send API；本设计把 Web 接到这些 API，并增加现有上传后端的浏览器入口。

该工作台不表示身份认证、HIPAA 合规、OCR 准确性或模型质量已经验证。

## 已选择方案

采用“端到端工作台”：

```text
上传材料
  ↓
复核标识符类别与 claims
  ↓
选择章节及来源 claims
  ↓
Prepare：冻结完整脱敏请求
  ↓
显示实际请求、hash、provider/model、来源版本
  ↓
人工批准或显式 synthetic auto
  ↓
Send：严格 gateway 发送一次
  ↓
把结果填入章节编辑器，但不自动保存
  ↓
人工修改、保存和审批章节
```

## 考虑过的方案

### 方案 A：只替换 Generate 按钮

仅把旧 `/generate` 改接 staged API。

优点：最快。  
缺点：用户仍需 CLI/API 上传材料，浏览器核心流程不完整。  
结论：不采用。

### 方案 B：端到端工作台

加入材料上传，同时接通 staged 模型审批与章节编辑。

优点：闭合浏览器核心流程；复用现有后端；不提前引入身份系统。  
代价：需要拆分当前大型 `App.tsx`，新增明确的前端状态机与错误恢复。  
结论：采用。

### 方案 C：同时实现登录、RBAC 与 reviewer 身份

优点：更接近部署产品。  
缺点：身份系统和机构权限是独立项目，会掩盖当前最关键的工作流验证。  
结论：后续单独设计。

## 目标

1. 浏览器可以向选定 workspace 上传 text/PDF/image 材料。
2. 上传结果只展示标识符类别、材料版本和人工复核提示，不展示识别出的原值。
3. 用户可以在现有 intake 面板中从新材料生成并接受 claims。
4. Generate 不再调用 410 endpoint，而是创建 staged egress request。
5. 用户在批准前看到模型将实际收到的完整脱敏 preview、hash、provider/model、tier 和 source refs。
6. `real` 请求需要 reviewer 与明确确认；`synthetic` 请求需要显式 auto reason。
7. Approve 与 Send 是两个独立动作；批准不自动发送。
8. Send 成功后只把文本填入当前章节编辑器，不自动保存或批准章节。
9. 页面能清楚显示 prepared、approved、sent、invalidated、blocked 和错误状态。
10. 刷新页面后，在同一浏览器标签页中可以根据保存的 request ID 恢复当前请求。

## 非目标

- 登录、SSO、身份认证、RBAC。
- 把 reviewer 文本描述为已验证身份或电子签名。
- 创建/删除 workspace 的 Web 管理界面。
- OCR 准确率、模型质量或临床有效性验证。
- send-lock 恢复工具。
- 报告导出和发布门禁。
- 远程 `real` 模型供应商、BAA 或部署审查。
- 改写后端审批状态机或降低现有门禁。

## 页面信息架构

保留当前三栏报告布局：

```text
┌─────────────────────────────────────────────────────────────┐
│ Topbar：Case / API status                                   │
├─────────────────────────────────────────────────────────────┤
│ Case strip：材料上传 / Intake claims / Identifying info     │
├────────────┬──────────────────────────┬──────────────────────┤
│ Sections   │ Section editor           │ Workflow summary     │
│ rail       │ Claims / Generate / Save │ Request state        │
└────────────┴──────────────────────────┴──────────────────────┘
```

### 材料上传面板

从 case strip 打开，位置与现有 names/intake 面板一致。

字段：

- File：`.txt`、`.pdf`、支持的图片类型；前端显示 10 MB 限制。
- Material ID：匿名短标识，不建议姓名。
- Title。
- Provider。
- Date。

上传成功后显示：

- 材料 ID 与 version。
- passages 数量。
- identifier categories 标签。
- “需要人工复核自动检测遗漏”的提示。
- “Review intake claims” 下一步按钮。

不显示 detector 命中的原始值。

### 模型请求审阅面板

使用页面内扩展面板，而不是 modal。原因：preview 可能很长，用户需要同时对照当前章节和 claims；页面内面板避免焦点陷阱，也适合窄屏顺序布局。

面板位于章节编辑器的 Generate 与 Save 之间，状态变化时展开：

```text
Model request
Prepared · real
local-model · 127.0.0.1
SHA-256: abcd…7890

Sources
claim-1 v2 · claim-4 v1

Identifiers replaced
name · telephone · date

Exact model input
┌──────────────────────────────┐
│ 完整脱敏 preview（可滚动）   │
└──────────────────────────────┘

[Reviewer / auto reason]
[确认已审阅完整请求]
[Approve request]

Approved 后：
[Send once]
```

## 前端状态机

定义独立状态，不以按钮布尔值拼接流程：

```text
idle
  → preparing
  → prepared
  → approving
  → approved
  → sending
  → sent

任意未完成状态可进入 error
prepared/approved 可因后端响应进入 invalidated
sending 可进入 output_blocked 或 uncertain_failure
```

状态含义：

- `idle`：尚无请求。
- `preparing`：正在调用 prepare；禁用重复 prepare。
- `prepared`：显示完整预览，尚未批准。
- `approving`：批准请求处理中。
- `approved`：允许单次 Send。
- `sending`：禁用所有重复发送动作。
- `sent`：返回文本已放入编辑器。
- `invalidated`：来源/hash/状态变化，需要重新 Prepare。
- `output_blocked`：模型已调用但输出含标识符；不显示正文，不允许原请求重发。
- `uncertain_failure`：模型可能已收到请求，保持 fail-closed；提示联系管理员，不显示“Retry Send”。
- `error`：准备或输入错误，可在修正后重新 Prepare。

## API 映射

### 上传

```http
POST /api/workspaces/{case_id}/materials
Content-Type: multipart/form-data
```

字段：`file`、`material_id`、`title`、`provider`、`date`。

### Prepare

```http
POST /api/workspaces/{case_id}/egress/prepare
```

```json
{
  "template_id": "ew-report",
  "template_version": 1,
  "section_id": "background_information",
  "claim_ids": ["claim-1"],
  "instructions": "...",
  "purpose": "section_generation"
}
```

前端不得发送 `redact`、provider、model 或 source refs。

### Approve

`real`：

```json
{
  "content_hash": "...",
  "reviewer": "[reviewer label]"
}
```

`synthetic`：

```json
{
  "content_hash": "...",
  "synthetic_auto_reason": "Synthetic development fixture"
}
```

### Send

```http
POST /api/workspaces/{case_id}/egress/{request_id}/send
```

成功结果只更新本地 section editor：

```ts
setForm(current => ({
  ...current,
  text: result.text,
  status: 'draft',
  reviewer: '',
}))
```

不会自动调用 `saveSection()`。

## Request 恢复

只在 `sessionStorage` 保存：

```text
psychtool.egress.[workspaceId,templateId,templateVersion,sectionId] = requestId
```

不保存 preview、模型输出、reviewer、reason 或任何标识符。页面加载 workspace/section 后，通过 GET request 恢复服务端状态。

若 request 不存在、已 invalidated 或 workspace 不匹配，清除该 sessionStorage 项。

实现约束补充：key 中的四元组使用 JSON 编码避免分隔符碰撞；发送前先删除并验证 request ID 已从 sessionStorage 清除，存储访问失败则阻止发送。这样刷新不会把可能已外发的 approved 请求重新恢复成可发送状态。成功后可保留 sent 请求 ID，但 GET 不返回生成正文，恢复页必须说明正文不可恢复、不可重发。恢复请求生成成功时，编辑器来源 claim IDs 使用该冻结请求的 source_refs，而不是页面原来的选择。

替换已批准章节的正文必须回到 draft 并清除 reviewer；来源或 known names 变化使当前未发送预览失效，需要重新 Prepare。

## 组件与文件边界

当前 `App.tsx` 已承担 workspace、intake、names、section editor 和 generation。新增功能前拆分：

- `web/src/types.ts`：API 和 UI 类型。
- `web/src/api.ts`：统一 fetch、固定安全错误解析、multipart upload、egress API。
- `web/src/egress-state.ts`：纯 reducer、状态转换和 sessionStorage key。
- `web/src/components/MaterialUploadPanel.tsx`：上传表单和上传结果。
- `web/src/components/EgressReviewPanel.tsx`：preview、批准、发送状态与操作。
- `web/src/App.tsx`：workspace/section 协调、结果进入编辑器、现有面板组合。
- `web/src/App.css`：沿用现有 paper/forest 视觉系统，新增上传和 egress 状态样式。

不新增大型组件库或状态管理依赖。

## 安全与隐私边界

1. 前端永远不获得 detector 命中的标识符原值。
2. Preview 来自持久化 egress request，而不是浏览器重新组装。
3. Approve 始终提交服务端返回的 exact `content_hash`。
4. 前端不能指定 provider、model、source refs 或关闭 redaction。
5. Reviewer 字段只是用户声明标签，不描述为已验证身份。
6. Send 按钮在 approved 前不存在或禁用。
7. Send 开始后立即禁用，避免重复点击。
8. `502 model request failed` 按不确定外发处理，不提供 Retry Send。
9. `422 model output blocked` 不显示响应正文，只说明类别检查阻断。
10. 浏览器存储只保留匿名 request ID。
11. 上传面板提醒：文件仍会到达 psychtool Web 服务；模型不会直接读取原文件。

## 错误与恢复

| HTTP/场景 | Web 行为 |
|---|---|
| 400 prepare/upload | 保留表单，显示固定错误，可修改后重试 |
| 400 approval | 保持 prepared；提示 reviewer/reason/hash 被拒绝 |
| 403 model network forbidden | 保持 approved；说明当前 tier/endpoint 策略不允许发送，不自动重试 |
| 409 stale/state conflict | 标记 invalidated；要求重新 Prepare |
| 410 legacy generate | 新 UI 不再调用；测试保证调用点消失 |
| 422 output blocked | 标记 output_blocked；不显示正文，不允许重发 |
| 502 model request failed | 标记 uncertain_failure；不显示 Retry Send |
| 网络中断（prepare 前） | 显示连接错误，可重新 Prepare |
| 网络中断（send 后） | 先 GET request；若 sent 则保持 sent，否则显示 uncertain_failure |

## 可访问性与响应式

- 所有输入都有可见 label。
- 错误和状态更新使用 `role="alert"` 或 `aria-live`。
- Preview 使用可聚焦的 `<pre>` 区域，保留换行，不依赖颜色表达状态。
- 按钮 busy 状态包含文字变化和 `aria-busy`。
- 原生 file input 可键盘操作。
- 720px 以下面板改为纵向顺序：上传/claims → section → egress review。
- 保留 `prefers-reduced-motion`。
- 不通过 hover 才展示关键安全信息。

## 测试与验收

### 前端纯逻辑测试

使用 Bun 内置 test runner，不新增测试框架：

- egress reducer 的合法状态转换。
- prepared 之前不能 approve。
- approved 之前不能 send。
- `502` 进入 uncertain_failure 且无 retry。
- `422` 进入 output_blocked。
- sessionStorage 只保存 request ID。
- API payload 不含 redact/provider/model/source refs。

### 后端回归

保留并扩展 FastAPI 测试，确认 Web 使用的 payload 契约：

- upload 只返回类别，不返回标识符原值。
- prepare 零 transport。
- human/synthetic approval 参数矩阵。
- send 单次调用。
- stale、blocked、uncertain failure 的固定状态码与安全 detail。

### 构建与浏览器验收

- `bun test`
- `bun run build`
- `python -m pytest -q`
- 浏览器完成 synthetic 端到端路径。
- 浏览器完成 real prepare + human approval；使用 injected/local test transport 验证发送。
- 验证刷新后 request ID 恢复。
- 验证窄屏 390px、桌面 1440px。
- 验证键盘可以完成上传、claims、prepare、approve、send 和 save。

## 验收标准

1. Web 中不存在对旧 `/generate` endpoint 的调用。
2. 用户可以上传材料并看到仅类别级脱敏结果。
3. 新材料可进入现有 intake claim 流程。
4. Generate 首先只 Prepare，不发生模型调用。
5. 页面显示 exact preview、hash、provider/model、tier 和 source refs。
6. Real 与 synthetic 使用各自正确批准表单。
7. 错误 hash、stale request、未批准请求均不能发送。
8. Send 成功只填入编辑器，不自动持久化。
9. Output blocked 和 uncertain delivery 均不提供重发按钮。
10. 页面刷新后可从 request ID 恢复状态。
11. Python 测试、Bun 测试、Web build 和浏览器验收全部通过。
12. 文档继续明确：当前没有认证/RBAC，且该工作流不证明 HIPAA 合规。

## 后续阶段

1. 登录、机构账户和 RBAC。
2. Reviewer 身份绑定及不可抵赖审计。
3. Web workspace 创建与管理。
4. send-lock 人工恢复管理界面。
5. Indra OCR 质量门禁和页码/坐标展示。
6. 报告导出、发布审批和留存策略。
