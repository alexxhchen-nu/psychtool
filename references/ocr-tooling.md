# OCR 工具选型：Indra OCR vs MinerU

核对日期：2026-11-06。对象：psychtool 的文档/扫描件导入管线选型。本文仅记录公开事实与本地实测，不含真实个案数据。

## 结论

对「真实个案材料本地 OCR」这一用途，**Indra OCR（`datalab-to/indra`）优先于本环境提供的 MinerU**。决定性理由是隐私边界：本环境的 MinerU 以**远程 MCP 服务**暴露（`mineru_parse_documents`），文档会发送到托管端处理；而 Indra OCR 是纯本地 CPU 模型，数据不出机器，符合 ADR 0003/0008 的本地处理边界与 `data_tier: real` 要求。

## Indra OCR 事实

- 项目：`datalab-to/indra`（GitHub，Python）。
- 模型：1M 参数 OCR，ONNX Runtime，纯 CPU，无 PyTorch/GPU 依赖。
- 许可证：**代码 Apache 2.0**；**模型权重 modified OpenRAIL-M**（研究/个人/初创 <$20M 免费，不得与 Datalab 官方 API 竞争）。本项目（学生非商用、非竞争）适用。
- 速度：约 44 页/s（32 核）、约 210ms/页（4 核），约 15× Tesseract。
- 语言：80+，含简体/繁体中文、日韩、RTL（阿拉伯/希伯来）等。
- 输出：markdown / text / JSON；每行 `Line(box, text, conf)` 带坐标框与置信度；另有 layout blocks、reading order。
- 安装：`pip install indra-ocr`（依赖 onnxruntime、opencv-python-headless、pypdfium2）。
- 本地模型：首次运行从 HuggingFace 下载约 76MB，可用 `INDRA_OCR_MODEL_DIR` 或 `--model-dir` 指定本地目录实现离线。

### 本地实测（2026-11-06）

- 合成测试图（PIL 生成，微软雅黑渲染）含简体中文与英文各两行。
- 结果：简体中文置信度 0.98–0.99，英文准确；`page.markdown` 与 `page.text` 均正常，`Line` 含坐标框。
- Python API：`indra_ocr.load(threads=4)` 返回 `Converter`；`converter.convert(path)` 返回 `(page_index, Page)` 元组生成器，`Page` 含 `.markdown`/`.text`/`.lines`。

### 已知短板（README 明写）

- 复杂表格效果差。
- 手写识别弱（约 25%）。
- 低清/退化扫描件差。
- 数学需 `--math` 选项。

对临床场景（多为打印的评估报告、访谈记录）可接受；手写表格多的场景需另行评估。

## 与 MinerU 对比

| 维度 | Indra OCR | MinerU（本环境 MCP） |
|---|---|---|
| 运行位置 | 本地 CPU | 远程托管服务 |
| 数据是否出机器 | 否 | 是 |
| 符合本地隐私边界 | 是 | 否（真实数据不可用） |
| 中文支持 | 80+ 语言 | 支持 |
| 复杂度 | 轻量 76MB | 较重（本地开源版 Magic-PDF 需 PyTorch/GPU 友好环境） |

## 接入位置

对应 SPEC 0001 的 Out of Scope「PDF/OCR 导入」。未来在 `import` 前加一步「PDF/图片 → Indra OCR → markdown/text」，产物进入 `import_material` 的段落切分。Indra 的 `Line(box, ...)` 坐标框可映射为规格预留的「页码 + 空间坐标」段落定位扩展。

## 来源

- GitHub：https://github.com/datalab-to/indra
- HuggingFace 模型卡：https://huggingface.co/datalab-to/indra-ocr
- Datalab 博客（Indra OCR 介绍）：https://www.datalab.to/blog/indra-ocr
- 实测：本地 Python 脚本（2026-11-06），合成测试图，无真实数据。
