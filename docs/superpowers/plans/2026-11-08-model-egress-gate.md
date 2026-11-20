# Model Egress Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一、可验证的模型出口门，使 `real` 请求必须人工批准，`synthetic` 评测只能通过显式自动放行，并保证批准预览与实际发送内容完全一致。

**Architecture:** 在 `core` 中新增不可变出口请求、规范 envelope hash、版本化持久化与审批状态机；在 `gateway` 中只接受已批准请求并在 transport 前重新验证。Web、CLI、judge 和 eval 逐一迁移到 prepare → approve → send，不再允许普通 prompt 字符串直接发送。

**Tech Stack:** Python 3.12、Pydantic 2、FastAPI、Typer、stdlib `hashlib/json/secrets/datetime`、pytest 8

**Spec:** `docs/superpowers/specs/2026-11-08-model-egress-gate-design.md`

## Global Constraints

- `data_tier="real"` 每次请求只允许 `approval_mode="human"`，reviewer 必填。
- `data_tier="synthetic"` 可显式使用 `approval_mode="synthetic_auto"`；不得静默自动批准。
- 未批准、失效、已发送、hash 不一致或残留阻断级标识符时，transport 调用次数必须为 0。
- hash 必须覆盖 transport 实际发送的规范 envelope、provider/base URL、model、purpose、source refs、data tier 和影响供应商处理的参数。
- prompt、模型响应正文、标识符原值、token map 和 API key 不进入普通日志。
- token map 不持久化。跨 HTTP 请求的第一版模型输出保留语义 token，不恢复原值。
- `psychtool/core` 保持无网络；真实网络只存在于 `psychtool/gateway/http.py`。
- 不新增第三方依赖，不声明 HIPAA 合规。
- 本计划不实现 Web 视觉审批界面、SSO、RBAC、Indra 质量评测或模型比较。

## Review Focus

- 同一 prompt 但 provider/model 或 message 参数变化时，旧批准必须失效。Task 1 与 Task 4 的 hash/config mismatch 测试覆盖。
- `instructions`、claim metadata 或 caller-supplied prompt 中出现标识符时，必须经过完整请求脱敏。Task 2 的参数化测试覆盖。
- 两个进程或服务重启之间读取批准请求时，不能依赖内存 token map。Task 1 的持久化 round-trip 和 Task 5 的 API 分步测试覆盖。
- 重复点击 send、请求已发送后重试或并发重放时，不能产生第二次 transport 调用。Task 4 的 single-use 与并发 exclusive-lock 测试覆盖。
- 旧 material/claim/draft 版本被更新后，批准请求必须失效。Task 3 的 freshness 测试覆盖。

---

## File Structure

### 新建

- `psychtool/core/egress.py`：出口请求模型、规范 hash、版本化存储、完整 prompt 脱敏、审批和失效检查；不访问网络。
- `tests/test_egress.py`：模型、hash、存储、准备、审批、来源新鲜度和日志安全测试。
- `tests/test_egress_api.py`：prepare/approve/send API 的分步行为与无网络失败测试。

### 修改

- `psychtool/core/workspace.py`：新 workspace 建立 `egress/` 子目录；兼容旧 workspace 的惰性创建。
- `psychtool/core/sections.py`：把“构建 section prompt”与“调用模型”拆开，提供出口门使用的纯构建函数。
- `psychtool/core/draft.py`：把 draft prompt 构建/结果落盘与模型发送解耦，供严格 gateway 调用。
- `psychtool/gateway/client.py`：删除普通字符串直发语义；验证批准状态、hash、配置和来源新鲜度后调用 transport。
- `psychtool/gateway/http.py`：接收已批准的确切 envelope，不在 transport 内重新组装 body。
- `psychtool/server/app.py`：新增 prepare/get/approve/send endpoints；移除 `/generate` 的直接发送能力。
- `psychtool/cli/app.py`：draft、judge、eval 迁移到统一出口；synthetic 自动放行必须显式调用。
- `psychtool/core/eval.py`：通过注入的严格发送函数运行，不再直接接收任意 prompt callback。
- `psychtool/core/judge.py`：拆出 judge prompt 准备与结果解析，发送交由出口门。
- `tests/test_gateway.py`、`tests/test_sections.py`、`tests/test_sections_api.py`、`tests/test_draft.py`、`tests/test_judge.py`：迁移旧接口断言并增加旁路回归测试。
- `references/redaction.md`、`docs/adr/0003-synthetic-cloud-data-tier.md`、`docs/adr/0008-openai-compatible-model-interface.md`：记录新出口门事实和旧 `real=local-only` 决策与新审批层的关系。
- `WORKLOG.md`：记录实际实现、测试结果、提交与未解决事项。

---

### Task 1: 出口请求模型、规范 hash 与持久化

**Files:**
- Create: `psychtool/core/egress.py`
- Modify: `psychtool/core/workspace.py:15-55`
- Test: `tests/test_egress.py`

**Interfaces:**
- Produces: `EgressPurpose`, `EgressStatus`, `ApprovalMode`, `SourceRef`, `OutboundEnvelope`, `EgressRequest`。
- Produces: `canonical_hash(request: EgressRequest | dict) -> str`。
- Produces: `save_egress_request(workspace: Path, request: EgressRequest) -> Path`、`get_egress_request(workspace: Path, request_id: str) -> EgressRequest`。
- Consumes: existing workspace directory and `Config` values copied by callers; no network objects.

- [ ] **Step 1: 写失败测试，固定模型、hash 和 round-trip**

```python
def test_hash_changes_when_actual_envelope_or_routing_changes():
    base = make_request()
    assert canonical_hash(base) == canonical_hash(base.model_copy(deep=True))
    assert canonical_hash(base) != canonical_hash(with_prompt(base, "changed"))
    assert canonical_hash(base) != canonical_hash(with_model(base, "m2"))
    assert canonical_hash(base) != canonical_hash(with_base_url(base, "https://other.invalid/v1"))


def test_request_roundtrip_does_not_persist_token_map(tmp_path):
    request = make_request()
    save_egress_request(tmp_path, request)
    loaded = get_egress_request(tmp_path, request.request_id)
    assert loaded == request
    assert "token_map" not in loaded.model_dump()
```

同时断言 `request_id`、`workspace_id`、`purpose`、`data_tier`、`provider_base_url`、`envelope.messages`、`source_refs`、`status`、`approval_mode` 和时间字段可序列化；普通 model dump 不包含 API key。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_egress.py -q`  
Expected: FAIL，模块或模型尚不存在。

- [ ] **Step 3: 实现最小模型和规范 hash**

在 `psychtool/core/egress.py` 定义：

```python
class SourceRef(BaseModel):
    kind: Literal["claim", "material", "draft"]
    id: str
    version: int

class OutboundEnvelope(BaseModel):
    model: str
    messages: list[dict[str, str]]

class EgressRequest(BaseModel):
    request_id: str
    workspace_id: str
    purpose: EgressPurpose
    data_tier: DataTier
    provider_base_url: str
    envelope: OutboundEnvelope
    source_refs: list[SourceRef]
    identifier_categories: list[str]
    content_hash: str
    status: EgressStatus
    approval_mode: ApprovalMode | None = None
    reviewer: str | None = None
    prepared_at: str
    approved_at: str | None = None
    sent_at: str | None = None
```

`canonical_hash()` 使用 `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 和 SHA-256。hash 输入排除 `content_hash` 自身、状态、时间和 reviewer，包含实际 envelope、routing、purpose、sources、identifier categories 和 data tier。

- [ ] **Step 4: 实现版本化存储和旧 workspace 兼容**

`workspace.SUBDIRS` 增加 `egress`；读写函数调用 `(workspace / "egress").mkdir(exist_ok=True)`，避免旧 workspace 缺目录时报错。文件名固定为 `<request_id>.json`；状态更新采用临时文件后原子替换。

- [ ] **Step 5: 运行聚焦测试**

Run: `python -m pytest tests/test_egress.py -q`  
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add psychtool/core/egress.py psychtool/core/workspace.py tests/test_egress.py
git commit -m "Add immutable model egress requests"
```

---

### Task 2: 完整请求准备、统一脱敏和残留阻断

**Files:**
- Modify: `psychtool/core/egress.py`
- Modify: `psychtool/core/sections.py:173-217`
- Modify: `psychtool/core/draft.py:59-145`
- Test: `tests/test_egress.py`
- Test: `tests/test_sections.py`
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: Task 1 `OutboundEnvelope`、`EgressRequest`、`SourceRef`、持久化接口。
- Produces: `prepare_egress_request(workspace: Path, *, prompt: str, purpose: EgressPurpose, config: Config, source_refs: list[SourceRef]) -> EgressRequest`。
- Produces: `build_section_request_input(...) -> tuple[str, list[SourceRef]]`；只构建完整原始 prompt 与来源，不调用模型。
- Produces: `build_draft_request_input(...) -> tuple[str, list[SourceRef]]`；只构建完整原始 prompt 与来源，不调用模型。

- [ ] **Step 1: 写失败测试，证明扫描的是最终完整 prompt**

参数化三种位置：claim text、`instructions`、`observation_setting/record_time/source_document_id`。每例断言：

```python
request = prepare_egress_request(...)
wire_text = request.envelope.messages[0]["content"]
assert secret not in wire_text
assert request.status == "prepared"
assert request.content_hash == canonical_hash(request)
```

再加入无法自动移除的残留命中测试，断言抛出 `EgressBlockedError`、错误对象只含类别、不含原值、请求文件未写入。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_egress.py tests/test_sections.py tests/test_draft.py -q`  
Expected: FAIL，prepare/build 接口不存在。

- [ ] **Step 3: 拆出 section 与 draft 的纯 prompt 构建函数**

复用现有 `select_claims()` 与 `build_prompt()`；`SourceRef(kind="claim", id=claim.id, version=claim.version)` 来自实际选中 claim。禁止 caller 自行伪造 claim refs。

- [ ] **Step 4: 实现 `prepare_egress_request`**

执行顺序固定为：完整 prompt → `redact_text(prompt, known_names=get_known_names(workspace))` → `find_identifiers(redacted_prompt)` → residual 阻断 → 构建 exact `OutboundEnvelope(model=config.model, messages=[...])` → hash → 保存。

只把 `sorted(set(category))` 写入请求；异常和日志不得拼接命中 `value`。第一版不持久化 token map，返回内容使用语义 token。

- [ ] **Step 5: 删除可由 Web caller 关闭真实请求脱敏的设计依赖**

保留底层纯函数测试需要的 synthetic 参数时，也不得让 `real` 路径接收 `redact=False`。更新旧测试，使其验证完整 prompt，而不是仅验证 claim text。

- [ ] **Step 6: 运行聚焦测试**

Run: `python -m pytest tests/test_egress.py tests/test_sections.py tests/test_draft.py -q`  
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add psychtool/core/egress.py psychtool/core/sections.py psychtool/core/draft.py tests/test_egress.py tests/test_sections.py tests/test_draft.py
git commit -m "Prepare fully redacted model requests"
```

---

### Task 3: 人工批准、synthetic 自动放行与来源失效

**Files:**
- Modify: `psychtool/core/egress.py`
- Modify: `psychtool/core/review.py`
- Test: `tests/test_egress.py`

**Interfaces:**
- Consumes: Task 2 prepared request and actual workspace sources.
- Produces: `approve_human(workspace: Path, request_id: str, *, reviewer: str, content_hash: str) -> EgressRequest`。
- Produces: `approve_synthetic(workspace: Path, request_id: str, *, reason: str) -> EgressRequest`。
- Produces: `validate_source_refs(workspace: Path, refs: list[SourceRef]) -> None`、`invalidate_request(...) -> EgressRequest`。

- [ ] **Step 1: 写失败测试，固定审批矩阵**

覆盖：

```text
real + human + reviewer + matching hash → approved
real + synthetic_auto → rejected
real + blank reviewer → rejected
synthetic + explicit synthetic_auto reason → approved
synthetic + implicit/empty reason → rejected
prepared + wrong hash → invalidated/rejected
approved + second approval → rejected
```

- [ ] **Step 2: 写失败测试，固定来源版本失效**

准备并批准 claim 请求后，分别新增 claim version、重新导入 material version、更新 draft version；`validate_source_refs()` 必须失败并把请求标记为 `invalidated`。eval 在构建临时 workspace 后使用实际 material/claim refs，不引入不可验证的 fixture 虚拟版本。

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/test_egress.py -q`  
Expected: FAIL，审批和 freshness 接口不存在。

- [ ] **Step 4: 实现状态转换和来源解析**

所有状态更新重新读取磁盘记录并原子写回。`approve_human()` 比较 caller 看到的 hash 与服务端当前 hash；`approve_synthetic()` 硬检查 `data_tier == "synthetic"`。新增明确异常类：`EgressApprovalError`、`EgressStaleError`、`EgressStateError`。

- [ ] **Step 5: 运行聚焦测试**

Run: `python -m pytest tests/test_egress.py -q`  
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add psychtool/core/egress.py psychtool/core/review.py tests/test_egress.py
git commit -m "Add model request approval state machine"
```

---

### Task 4: 严格 gateway 与 exact envelope transport

**Files:**
- Modify: `psychtool/gateway/client.py`
- Modify: `psychtool/gateway/http.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_egress.py`

**Interfaces:**
- Consumes: approved `EgressRequest` and Task 3 freshness/state validators.
- Produces: `send_approved(workspace: Path, request_id: str, *, config: Config, transport: Callable[[Config, dict], str]) -> str`；输出含标识符时抛出 `EgressOutputBlockedError`，不返回正文。
- Produces: `http_transport(config: Config, envelope: dict) -> str`；原样发送已批准 envelope。
- Removes: `complete(prompt: str, *, config, transport)` 的普通字符串直发能力。

- [ ] **Step 1: 改写 gateway 失败测试**

加入 transport spy，覆盖：未批准、invalidated、already sent、config model mismatch、base URL mismatch、hash mismatch、stale source 时调用次数均为 0；批准请求恰好调用一次，transport 收到的 dict 与批准的 `request.envelope.model_dump()` 完全相等。另让 transport 返回新生成的电话/邮箱，断言正文不返回、请求仍标记为 `sent`、异常只暴露标识符类别。

- [ ] **Step 2: 加入重复与并发发送测试**

第一次成功后状态为 `sent`；第二次调用抛出 `EgressStateError`，transport 总调用次数仍为 1。再用两个线程和 barrier 同时发送同一 approved request，断言只有一个线程取得 `<request_id>.send.lock` 并调用 transport，另一个在网络调用前失败；transport 总调用次数仍为 1。

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/test_gateway.py tests/test_egress.py -q`  
Expected: FAIL，旧 gateway 仍接受字符串。

- [ ] **Step 4: 实现 `send_approved` 和 exact envelope transport**

发送顺序：使用 `os.open(..., O_CREAT | O_EXCL)` 独占创建 `<request_id>.send.lock` → 读取记录 → 状态/审批模式检查 → source freshness → config 与记录匹配 → 重算 hash → 现有 real/local endpoint 策略 → transport → 原子标记 sent → 对输出执行 `gate_pii()`。transport 明确失败时删除 lock 且不得标记 sent；发送成功后状态阻止重发。进程若在 transport 返回前后崩溃，保留 lock 并默认阻断后续发送，留待人工恢复，避免不确定状态下重复外发。输出阻断发生在网络调用之后，因此保持 `sent` 并抛出只含类别的 `EgressOutputBlockedError`；任何错误消息均不附带 prompt 或响应正文。

- [ ] **Step 5: 移除旧字符串接口并全仓搜索**

Run: `rg -n "complete\(|http_transport\(" psychtool tests -g "*.py"`  
Expected: 只剩严格 gateway、transport 定义和下一任务尚待迁移的编译失败调用点；不得保留兼容性静默放行。

- [ ] **Step 6: 运行聚焦测试**

Run: `python -m pytest tests/test_gateway.py tests/test_egress.py -q`  
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add psychtool/gateway/client.py psychtool/gateway/http.py tests/test_gateway.py tests/test_egress.py
git commit -m "Require approved requests at model gateway"
```

---

### Task 5: Web prepare、get、approve、send API

**Files:**
- Modify: `psychtool/server/app.py`
- Modify: `tests/test_sections_api.py`
- Create: `tests/test_egress_api.py`

**Interfaces:**
- Consumes: Tasks 2-4 prepare/approve/send interfaces.
- Produces: `POST /api/workspaces/{case_id}/egress/prepare`。
- Produces: `GET /api/workspaces/{case_id}/egress/{request_id}`。
- Produces: `POST /api/workspaces/{case_id}/egress/{request_id}/approve`。
- Produces: `POST /api/workspaces/{case_id}/egress/{request_id}/send`。
- Changes: `/api/workspaces/{case_id}/sections/{section_id}/generate` 不再直接调用模型；返回 410 和迁移说明，直到 Web UI 切换。

- [ ] **Step 1: 写 prepare API 失败测试**

断言响应包含 request ID、status=`prepared`、完整脱敏 preview、hash、provider/model、source refs、identifier categories 和人工检查提示；注入 transport spy 并断言调用次数为 0。

- [ ] **Step 2: 写 human approval/send API 失败测试**

以 `real` 本地 endpoint 配置运行：prepare → 未批准 send 返回 409/403 且无网络 → approve 提交 reviewer+hash → send 成功且只调用一次。GET 在应用重建后仍可读取相同请求，证明不依赖进程内 token map。

- [ ] **Step 3: 写安全错误测试**

错误响应只包含代码/类别；断言姓名、电话、完整 prompt、API key 不出现在 JSON。`real` 请求尝试 synthetic auto 返回 400/403。

- [ ] **Step 4: 运行测试并确认失败**

Run: `python -m pytest tests/test_egress_api.py tests/test_sections_api.py -q`  
Expected: FAIL，endpoints 不存在且旧 generate 仍直发。

- [ ] **Step 5: 实现 Pydantic payload 与四个 endpoints**

Prepare payload 只接受 section/template/claim IDs/instructions/purpose，不接受 `redact` 开关。Approve payload 接受 `reviewer`、`content_hash`、可选 synthetic auto reason；服务端从 workspace/config 决定允许模式。Send payload 只接受 request ID 路径参数。

- [ ] **Step 6: 禁用旧直接 generate 路径**

返回明确 `410 Gone`，detail 指向 prepare/approve/send；不得内部自动批准 real 请求。

- [ ] **Step 7: 运行聚焦测试**

Run: `python -m pytest tests/test_egress_api.py tests/test_sections_api.py -q`  
Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add psychtool/server/app.py tests/test_egress_api.py tests/test_sections_api.py
git commit -m "Expose staged model egress API"
```

---

### Task 6: 迁移 CLI draft、judge 与 eval

**Files:**
- Modify: `psychtool/cli/app.py:140-225`
- Modify: `psychtool/core/draft.py`
- Modify: `psychtool/core/judge.py`
- Modify: `psychtool/core/eval.py`
- Modify: `tests/test_cli_fields.py` or create `tests/test_cli_egress.py`
- Modify: `tests/test_draft.py`
- Modify: `tests/test_judge.py`
- Modify: eval-related tests under `tests/`

**Interfaces:**
- Consumes: strict prepare/approve/send pipeline.
- Produces: CLI `draft --reviewer <id>` for real; explicit `--synthetic-auto` plus nonempty `--approval-reason` for synthetic automation.
- Produces: judge/eval internal helper that always creates an `EgressRequest`; no arbitrary prompt callback reaches transport.

- [ ] **Step 1: 写 CLI 失败测试**

覆盖：real draft 缺 reviewer 在准备后停止且不发送；synthetic 缺 `--synthetic-auto` 不会隐式发送；synthetic auto 带 reason 可运行；命令输出显示 request ID/status，不打印完整 prompt。

- [ ] **Step 2: 写 judge/eval 旁路失败测试**

transport spy 断言每次调用都有可读取的批准 request；冻结 eval 使用 `approval_mode="synthetic_auto"`；把 eval 配置改为 real 时硬拒绝自动放行。

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/test_cli_egress.py tests/test_draft.py tests/test_judge.py tests/test_eval.py -q`  
Expected: FAIL；若仓库实际 eval 测试文件名不同，先用 `rg -l "run_eval|run_case" tests` 替换命令中的文件名。

- [ ] **Step 4: 迁移 draft 与 judge**

把 prompt 构建、准备、批准、发送、结果解析/落盘按现有职责拆开。CLI 负责选择批准模式，不得把布尔值直接传到 gateway 绕过状态机。

- [ ] **Step 5: 迁移 eval**

`run_eval` 接收能够创建严格 synthetic 请求的 orchestrator，而不是 `Callable[[str], str]`。每个 single/staged/judge 请求记录 `purpose="eval"` 或对应 purpose；fixture 导入临时 workspace 后使用实际 material/claim versions 作为 source refs。

- [ ] **Step 6: 全仓旁路搜索**

Run:

```bash
rg -n "complete\(|http_transport\(" psychtool -g "*.py"
rg -n "transport\(config, prompt\)|transport\(cfg, prompt\)" psychtool tests -g "*.py"
```

Expected: 业务代码只通过 `send_approved()` 到达 transport；不存在普通 prompt 直发。

- [ ] **Step 7: 运行聚焦测试**

Run: `python -m pytest tests/test_cli_egress.py tests/test_draft.py tests/test_judge.py tests/test_eval.py -q`  
Expected: PASS；按 Step 3 的实际 eval 文件名调整。

- [ ] **Step 8: 提交**

```bash
git add psychtool/cli/app.py psychtool/core/draft.py psychtool/core/judge.py psychtool/core/eval.py tests
git commit -m "Route all model workflows through egress approval"
```

---

### Task 7: 文档、日志安全和全量验证

**Files:**
- Modify: `references/redaction.md`
- Modify: `docs/adr/0003-synthetic-cloud-data-tier.md`
- Modify: `docs/adr/0008-openai-compatible-model-interface.md`
- Modify: `WORKLOG.md`
- Test: `tests/test_egress.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented operational contract and final verification evidence.

- [ ] **Step 1: 增加日志序列化安全测试**

对 prepared、approved、invalidated、sent 和 transport error 事件序列化，断言不包含 prompt、response body、known name、phone、token map、API key；只允许 request ID、hash、purpose、tier、provider/model、类别、状态、reviewer 和时间。

- [ ] **Step 2: 运行安全测试并确认结果**

Run: `python -m pytest tests/test_egress.py -q`  
Expected: PASS；若缺日志事件函数，先看到针对该函数的 FAIL，再做最小实现。

- [ ] **Step 3: 更新 ADR 和 redaction 文档**

记录：旧 `real` local-only 网络限制仍保留；新审批层叠加其上；synthetic auto 必须显式；完整请求预览与 hash 语义；token map 不持久化；该机制不是 HIPAA 合规证明。

- [ ] **Step 4: 运行全量 Python 测试**

Run: `python -m pytest -q`  
Expected: 全部 PASS；记录准确数量和 warning，不沿用历史数字。

- [ ] **Step 5: 运行 Web build 回归**

Run: `cd web && bun run build`  
Expected: exit 0。旧 Generate 按钮若仍调用 410 endpoint，本计划必须在 WORKLOG 明确标为待下一阶段 UI 迁移，不能宣称 Web 生成可用。

- [ ] **Step 6: 运行静态旁路和 diff 检查**

```bash
rg -n "complete\(|http_transport\(" psychtool -g "*.py"
git diff --check
git status --short
```

Expected: 无普通字符串直发路径；diff check 无输出；status 只含本计划相关文件。

- [ ] **Step 7: 更新 WORKLOG**

写入完整时间戳、实际模型名、逐项变更、Python/Web 实际核验、已知限制和未解决事项。明确 Web 审批 UI、身份认证/RBAC、OCR 质量评测，以及崩溃后 send lock 的人工恢复工具仍未完成。

- [ ] **Step 8: 提交并推送**

```bash
git add references/redaction.md docs/adr/0003-synthetic-cloud-data-tier.md docs/adr/0008-openai-compatible-model-interface.md WORKLOG.md tests/test_egress.py
git commit -m "Document model egress approval controls"
git push origin main
```

- [ ] **Step 9: 核对最终状态**

Run: `git status --short && git log -1 --oneline --decorate`  
Expected: 工作区干净，`HEAD` 与 `origin/main` 指向同一最终提交。
