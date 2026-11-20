# Issue tracker: Local Markdown

本仓库的 issue 与 spec 以 markdown 文件形式存放在 `.scratch/`。

## 约定

- 每个 feature 一个目录：`.scratch/<feature-slug>/`
- spec 为 `.scratch/<feature-slug>/spec.md`
- 实现票一文件一票：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 编号，禁止合并为单文件 tickets
- triage 状态记录为文件顶部附近的 `Status:` 行（角色字符串见 `triage-labels.md`）
- 评论与会话历史追加到文件底部 `## Comments` 标题下

## 当技能说「发布到 issue tracker」时

在 `.scratch/<feature-slug>/` 下创建新文件（目录不存在则创建）。

## 当技能说「取相关票」时

读取所引用路径的文件。用户通常会直接给出路径或票号。

## Wayfinding 操作（供 `/wayfinder` 使用）

- **Map**：`.scratch/<effort>/map.md`（Notes / Decisions-so-far / Fog 正文）。
- **子票**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 编号，问题写在正文。`Type:` 行记录票类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 行记录 `claimed`/`resolved`。
- **阻塞**：文件顶部附近 `Blocked by: NN, NN` 行。当所列文件全部 `resolved` 时该票解阻塞。
- **Frontier**：扫描 `.scratch/<effort>/issues/` 中 open、未阻塞、未认领的文件；按编号取第一个。
- **认领**：开始工作前设 `Status: claimed` 并保存。
- **解决**：在 `## Answer` 标题下追加答案，设 `Status: resolved`，然后把上下文指针（gist + 链接）追加到 `map.md` 的 Decisions-so-far。
