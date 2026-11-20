# 12: PDF/扫描件导入（Indra OCR 本地集成）

**What to build:** 在 `import` 前增加一步：PDF 或图片 → 本地 Indra OCR → markdown/text，产物进入现有 `import_material` 的段落切分。对应 SPEC 0001 Out of Scope 中的「PDF/OCR 导入」。

**Blocked by:** 03（`import_material` 段落切分）、11（CLI import 命令）

**Status:** ready-for-agent

- [ ] 封装 Indra OCR 为 `psychtool/core/ocr.py`（或 gateway 同级的本地处理模块），输入 PDF/图片路径，输出 `(page_index, Page)` 或规范化文本 + 坐标框
- [ ] 输出 `Line(box, text, conf)` 映射为段落定位（页码 + 空间坐标），进入 `import_material`
- [ ] 模型目录走 `INDRA_OCR_MODEL_DIR` 环境变量，支持离线（无网络下载）
- [ ] CLI `import --file x.pdf` 自动识别 PDF/图片并走 OCR 路径（文本文件仍走原路径）
- [ ] `data_tier: real` 下 OCR 全程本地，不触发网络（测试断言无 egress）
- [ ] 测试：合成 PDF/图片中文+英文样例，断言识别结果与定位
- [ ] 依赖 `indra-ocr` 加入可选依赖组（`[project.optional-dependencies] ocr`），默认不装

## Comments
