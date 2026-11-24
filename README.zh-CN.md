<!-- architect-team:readme-theme=mono -->

<div align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="psychtool — 来源可溯的临床写作工作区，右侧为带来源定位的证据索引卡">
</div>

**简体中文** | [English](README.en.md) | [繁體中文](README.md)

<div id="overview"></div>
<p align="center">
  <img src="./assets/readme/sec-01-what-this-is.svg" width="100%" alt="01 · 这是什么 / WHAT THIS IS">
</p>

psychtool 是一个帮助个人写报告的临床写作工作区，目标用户是没有技术背景的临床培训生。它解决的核心问题：**如何在把分散材料整理成报告草稿的同时，保留谁在什么场合、什么时间、以什么确定性说了什么**——而不是先生成流畅文本再回头补引用。

心理评估报告、临床个案报告、进展记录与学术论文都在长期范围内；当前优先临床写作，首个验证场景刻意收窄为**整理合成的青少年背景资料**：不做诊断、不解释量表、不做治疗决策。青少年与神经心理侧重是设计选择；机构 AI 政策尚未确认。

<div id="current-state"></div>
<p align="center">
  <img src="./assets/readme/sec-02-current-state.svg" width="100%" alt="02 · 当前状态 / CURRENT STATE">
</p>

**核心应用已实现并可运行**：`psychtool` 命令行（`init` / `import` / `claims` / `draft` / `review` / `export` / `eval` / `judge` / `dash`）+ textual 仪表盘 + 彩色启动横幅，**66 项自动化测试通过**。**真实模型已接入**（linksub `deepseek-v4-pro`，OpenAI 兼容端点）并跑通真实 `eval`：单步生成干净（无编造、无跨案泄漏、无矛盾化解），朴素分步基线被硬门槛捕获跨案引用；桌面/网页界面与 PDF/OCR 导入推迟（见 ADR 0001、ticket 12）。

本仓库包含：需求与边界、官方隐私来源研究、实证证据矩阵、开发规格与实现票、两组原创合成训练材料，以及上述可运行的 CLI 应用。详细研究文档以简体中文为主。

**浏览器应用（本地原型）。** 除 CLI 外，本仓库另含本机浏览器原型：创建合成个案、粘贴合成文字（规则式抽取候选陈述）、人工批准后经由网关送出生成请求、把产出存为段落，刷新后仍在。**默认使用离线 FakeTransport 模型，不联网、不需要 API 密钥**；只有明确设置 `PSYCHTOOL_TRANSPORT=http` 才会走真实端点。原型**尚未符合 HIPAA**，页面常驻横幅亦如此提示；仅用合成数据。

材料上传（ADR 0012）：M1 仅接受 `.txt`／`.md`（UTF-8，上限 10 MiB）；扫描件与图片会得到固定说明（服务器端无 OCR）；首次上传前每个个案需勾选确认一次“仅用合成或已另行核准的材料”。保护性测验内容阻挡（ADR 0013）：疑似测验原题、常模或计分规则的段落在任何写入前被扣留（永不入库、永不送入模型；审计只记计数与哈希；检查器失败时整笔拒绝），M1 无释放通道。

服务器／浏览器路径的个案存储为**单一 SQLite 数据库**（默认 `local-data/psychtool.db`，可用 `PSYCHTOOL_DB_PATH` 覆盖；ADR 0010），以复合主键与外键在数据库层强制个案隔离；ADR 0005 的 JSON 工作区仍是 CLI／评测链路的格式。把既有 JSON 工作区导入数据库：

```bash
uv run psychtool import-json fixtures/case_a001   # 导入合成示例个案（--db 可指定数据库路径）
```

```bash
cd web && bun install && bun run build   # 构建前端（FastAPI 直接提供 web/dist）
cd .. && uv run psychtool-server         # 打开 http://127.0.0.1:8000
```

**本地安全基线（ADR 0011）。** 服务器仅绑定 loopback（非 loopback 的 `PSYCHTOOL_HOST` 拒绝启动）；每次启动产生一组会话令牌，所有 `/api/*`（除 `GET /api/health`）需带 `X-Psychtool-Token`；每个响应带严格 CSP 与安全标头；启动自检拒绝把数据库放进云同步文件夹（磁盘加密仅警告）。审计日志为 SQLite 内仅追加、哈希链保护的 `audit_log` 表，与状态变更同一事务写入。**开发提示**：直接打开服务器提供的页面即自动带令牌；用 Vite dev server 时，须把同一组 `PSYCHTOOL_SESSION_TOKEN`（≥32 字符）设给后端与前端 proxy，否则 API 返回 401。

测试：

```bash
uv run --extra dev pytest -q                          # 后端（含 test_security / test_selfcheck / test_audit_log / test_send_lock_recovery）
cd web && bun test && bun run build                   # 前端单元测试（含 api.ts 令牌、send_interrupted 状态）+ 构建
cd web && bunx playwright install chromium && bun run e2e   # 端到端（含 security.e2e：CSP 标头、无 CSP console 错误、无令牌 401）
```

<div id="first-workflow"></div>
<p align="center">
  <img src="./assets/readme/sec-03-first-workflow.svg" width="100%" alt="03 · 首个工作流 / FIRST WORKFLOW">
</p>

已实现（CLI 命令面）：

<div align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="五个步骤的工作流：材料、事实清单、带来源草稿、人工审阅门禁、导出；来源修改使草稿回到重新核对">
</div>

<div id="evidence"></div>
<p align="center">
  <img src="./assets/readme/sec-04-evidence.svg" width="100%" alt="04 · 现有证据 / EVIDENCE">
</p>

- **OpenAlex 检索。** 四次查询共返回 **35 条去重候选记录**，注意事项见 [references/empirical-research.md](references/empirical-research.md)。
- **已核读研究。** **9 项研究**完成实质核读（4 项儿童／青少年评估、5 项 AI 临床文书）。其中一项研究观察到“先抽取事实再生成”的配置反而增加重大错误——本项目因此**不预设多步流程更安全**，评测将对比单步与分步方案。细节与访问边界见 [references/empirical-research.md](references/empirical-research.md)。
- **合成训练个案。** [fixtures/adolescent-background.json](fixtures/adolescent-background.json) 含 **2 例原创合成个案**，附来源段落定位，用于溯源与个案隔离检查。
- **来源保真变体。** [fixtures/source-fidelity-variants.json](fixtures/source-fidelity-variants.json) 保存 **3 组配对变体**（缺失 vs 否定、第三人归属、简洁性–遗漏），附期望行为。

以上文献启发设计判断，不能证明本项目已减少错误或提升效率；尚无任何模型输出性能结论。

<div id="reading-order"></div>
<p align="center">
  <img src="./assets/readme/sec-05-reading-order.svg" width="100%" alt="05 · 阅读顺序 / READING ORDER">
</p>

| 步骤 | 文档 | 确立的内容 |
|---|---|---|
| 1 | [临床需求与设计约束](docs/clinical-requirements.md) | 使用者、范围、审核责任与隐私约束 |
| 3 | [实证研究入口](references/empirical-research.md) | 检索覆盖、已核读证据与访问限制 |
| 4 | [工作流规格草案](docs/first-workflow-spec.md) | 首个端到端行为与验收条件 |

更多资料入口：[HHS 来源记录](references/hhs-sources.md) · [技能与工具选型](docs/skills-and-tools.md) · [开发规格 SPEC 0001](docs/specs/0001-first-workflow-cli.md) · [架构决策 ADR](docs/adr/) · [实现票](.scratch/first-workflow/issues/)

<div id="privacy"></div>
<p align="center">
  <img src="./assets/readme/sec-06-privacy.svg" width="100%" alt="06 · 隐私边界 / PRIVACY">
</p>

- 当前材料均为合成、公开来源或开发者笔记，不含真实患者资料。
- 个案隔离、日志、临时文件、备份、网络请求与导出副本都是**待实现并待验证**的边界。
- 本地运行、加密或某项工具的通过结果，均不能单独证明 HIPAA 合规性。来源核查见 [references/privacy-research.md](references/privacy-research.md)，不构成法律意见。
- DSM 优先经学校授权入口人工查阅；APA 与 Pearson 的条款对 AI 使用有限制，阅读权限不等于应用入库权限。

<div id="next-steps"></div>
<p align="center">
  <img src="./assets/readme/sec-07-next-steps.svg" width="100%" alt="07 · 下一步 / NEXT STEPS">
</p>

1. 在真实模型上跑 `judge`（逐陈述语义支持率，独立 judge 槽位）。
2. 为学生做图形界面（桌面/网页，ADR 0001 推迟项）。
3. PDF/扫描件导入（本地 Indra OCR，见 [references/ocr-tooling.md](references/ocr-tooling.md)、ticket 12）。
4. 通过评测后再评估是否引入 Harness² 优化工作流，以及是否接入受许可的文献资源。

<div id="limitations"></div>
<p align="center">
  <img src="./assets/readme/sec-08-limitations.svg" width="100%" alt="08 · 局限 / LIMITATIONS">
</p>

机构内部 AI 政策、使用者设备与偏好仍为未知；证据核读受访问条件限制，未完成全面的勘误清查；未附带开源许可证，**保留所有权利**。本文档结构以本地渲染为验证依据。
