# 03: 工作区 init + import（版本不可变）

**What to build:** `init` 创建工作区目录并显式标记虚构训练状态；`import` 导入文本材料，产出标题、提供者、日期、段落定位与版本号。修改材料写新版本，旧版本保留，不覆盖。

**Blocked by:** 01（需包骨架与配置）

**Status:** ready-for-agent

- [ ] `init` 生成工作区目录与 `data_tier: synthetic` 标记
- [ ] `import` 解析材料为带 `id`/`version`/`case_id`/来源定位/状态字段的 JSON 文件
- [ ] 段落定位为文档版本 + 段落 ID
- [ ] 更新材料产生新版本文件，旧文件与旧定位仍可读
- [ ] 工作区目录结构与字段通过 schema 校验测试

## Comments

- 2026-11-06：实现完成，新增 7 测试、全套 17/17 通过。提交 `4acf78c`。`import_material` 的 case_id 一律取自工作区 meta，杜绝外部注入跨个案绑定；段落按空行切分，定位=版本+段落 ID。
