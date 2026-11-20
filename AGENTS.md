# psychtool — 仓库内代理须知

面向在本仓库工作的 AI 代理与开发者。产品名 **psychtool**；私有仓库 `alexxhchen-nu/psych-tools`；本地目录路径 `dev/projects/eugenia` 沿用旧名，不代表产品名。

## 仓库性质

核心应用已实现并可运行（`psychtool` CLI + textual 仪表盘 + 启动横幅，66 测试通过）；尚未接入真实模型、未跑真实评测。任何文档不得把设计目标写成已实现能力，不得声称 HIPAA 合规、临床有效性或模型性能结论。

## README 维护规则

三份 README 必须同步修改，保持结构、事实与数字一致：

| 文件 | 语言 | 角色 |
|---|---|---|
| `README.md` | 繁體中文 | **默认页**（GitHub 首页） |
| `README.zh-CN.md` | 简体中文 | 简体版 |
| `README.en.md` | English | 英文版 |

改任何一份的内容（状态、数字、章节、链接），必须同步另两份，并在 `WORKLOG.md` 追加记录。

### 视觉资产（`assets/readme/`）

- `hero.svg`：首屏标题卡 + 来源索引卡；`workflow.svg`：五步工作流与人工审阅门禁；`sec-01…sec-08-*.svg`：章节横幅（1200×56，三语共享）。
- 所有 SVG 纯静态：禁止 `<script>`、`foreignObject`、外部字体与网络资源；必须含 `viewBox`、`rx` 圆角、`<title>`。
- 改文案时改 SVG 内文字并保持字号约束：标题 ≥40、关键文字 ≥20、辅助 ≥18（1200 宽 viewBox）。
- 调色板：纸面 `#FAF8F2`、墨色 `#1F2430`、灰 `#6E7681`、强调靛蓝 `#4C6EF5`。

### 事实红线

- 数字必须与文件核对一致：OpenAlex 检索 **4 次查询 / 35 条去重**；核读 **9 项研究（4 评估 + 5 文书）**；合成个案 **2 例**；保真变体 **3 组**。数字变化必须先改对应源文件再改 README。
- 禁止未验证声明：不写徽章、安装命令、测试结果、覆盖率，除非仓库中存在对应可运行证据。
- 每个语言切换链接、文档相对链接与 `img src` 必须在提交前实际存在。

### 提交前检查

```bash
python <home>/… README.md
# 同样对 README.en.md、README.zh-CN.md 执行；并检查全仓库相对链接与 img src 无缺失
```

## 日志

每次实质进展追加到 `WORKLOG.md`：完整时间戳（含时区）、执行模型名、变更、实际核验结果、未解决事项。日志不含真实患者资料、密钥或敏感原文。

每次重大变更，以及用户要求或代理主动建议提交时：先更新 `WORKLOG.md`，再核对 diff 和测试，提交相关文件并推送当前分支。记录实际提交号与推送结果；失败时如实记录，不能预写成功。不要把无关改动纳入提交。

## 数据边界

仓库仅含合成、公开来源或开发者材料。DSM、商业测验条目/常模/计分规则、真实个案资料不得入库；APA 与 Pearson 对 AI 使用的限制见 `references/assessment-materials-boundaries.md`。

## HIPAA 与上传边界

HIPAA 相关要求是产品架构的核心约束，须在文件上传、OCR、存储、模型请求、日志、导出和供应商链路逐项核对。上传文件的解析与标识符处理必须先于持久化和任何模型调用；生成前仍要检查完整模型请求。自动识别、token 替换、加密或本地运行均不能单独证明符合 HIPAA。当前仓库仅用于合成/公开资料开发；不得把未验证的门禁写成已获合规批准。依据与未决事项见 `references/privacy-research.md`、`references/hhs-sources.md` 和 `references/redaction.md`。

## Agent skills

工程技能（triage / to-spec / to-tickets / implement / code-review 等）按以下约定运作：

- **Issue tracker**：本地 Markdown，见 `docs/agents/issue-tracker.md`。
- **Triage 标签**：默认五态，见 `docs/agents/triage-labels.md`。
- **域文档**：单上下文 `GLOSSARY.md` + `docs/adr/`，消费规则见 `docs/agents/domain.md`。
