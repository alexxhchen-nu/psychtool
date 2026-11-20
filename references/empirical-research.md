# 实证研究入口与覆盖范围

检索日期：2026-11-06。目标：用真实发表的研究与明确标记的预印本，支持 psychtool 首个写作流程与评测设计。不是系统综述或临床效能证明，也不是患者数据集。

## 检索实际结果

使用现有环境中的 OpenAlex key，通过 citation-management 的 OpenAlex 检索脚本执行四次有界查询。密钥只由脚本通过认证头发送给 OpenAlex，没有写入项目、命令参数或日志。

| 查询主题 | 年份过滤 | 取回条数 |
|---|---|---|
| 青少年多信息源及分歧 | 2010–2026 | 10 |
| 儿童神经心理评估与效度 | 2010–2026 | 10 |
| LLM 临床文书幻觉与遗漏 | 2023–2026 | 10 |
| 多信息源评估基础综述补充 | 2010–2026 | 5 |

共取回 35 条记录，按 DOI/OpenAlex ID 去重后 35 条，其中 32 条含 OpenAlex 摘要。没有将检索命中数或摘要存在数称为“全文已验证数”。规范化导出本身没有更正/撤稿字段；独立核对的范围见证据矩阵。

可复现记录：[检索台账](empirical-search-ledger.json)。原始候选导出为同目录的 `openalex-*.json`，它们保留发现时的作者、年份和摘要；例如候选中的在线年与正式卷期年、作者顺序差异，在矩阵中注明修正，不静默覆盖发现记录。

research-lookup 默认的 Parallel Search/Extract 在本环境没有发现 CLI 与 API key；用户明确允许 OpenAlex 或其他来源，本轮使用 OpenAlex 发现、出版商/PubMed/PMC/Europe PMC 核查。没有运行 Parallel Extract，不能套用该技能的 `verified_references` 计数。当前是产品研究，不以稿件默认 60 篇为目标。

## 已核读的两组证据

- [评估证据矩阵](assessment-evidence-matrix.md)：4 项研究，包含多信息源基础元分析；区分全文相关章节与摘要，保留局限和反证。
- [临床文书 AI 证据矩阵](documentation-evidence-matrix.md)：5 项直接文书生成研究取得公开正文；包含一项未同行评审预印本，不能与已发表研究混为同等证据。

两组共 9 项实质核读，不是 9 项都完成逐页全文、补充材料、勘误和撤稿清查。研究对象也并非都为青少年神经心理报告。

## 对方案产生的实际影响

1. De Los Reyes 等 2015（[10.1037/a0038498](https://doi.org/10.1037/a0038498)）的 341 项研究元分析支持保留提供者与情境，但不能由相关系数给某个来源评可信度。
2. Asgari 等 2025（[10.1038/s41746-025-01670-7](https://doi.org/10.1038/s41746-025-01670-7)）观察到某个事实抽取配置增加重大错误。事实清单作为人工审阅依据，生成方案仍须对比单步与分步，不预设多步更安全。
3. Williams 等 2025（[10.1001/jamainternmed.2025.0821](https://doi.org/10.1001/jamainternmed.2025.0821)）显示简洁性与完整性可能朝不同方向变化。遗漏与新增错误分开评分，不能被可读性总分抵消。
4. 人物归属、未知与明确否定、时间和来源版本分别检验。某段文字出现在来源中，不足以证明它描述的是受评者。

上述是研究启发的设计判断，不能声称此软件已减少临床错误或节省工作时间。

## 接入首个验证场景

- [首个工作流规格草案](../docs/first-workflow-spec.md)
- [原创虚构个案与参考事实](../fixtures/adolescent-background.json)
- [成对来源保真变体](../fixtures/source-fidelity-variants.json)

样例不来自论文患者记录，也不复制 DSM、商业测验条目或计分材料。它们用于后续验证，不是已经通过模型测试的案例。

## 方法来源

本轮采用 research-lookup 等 Scientific Agent Skills 的检索与证据记录方法。方法来源为 Kassis T, Agarwal V, He Y, Patel D, Brueckner AM. *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*. 2026. [arXiv:2609.00065](https://arxiv.org/abs/2609.00065)。题名、作者和年份已在文书证据研究中读取 arXiv 记录核对；该方法文献不计入上述九项领域证据，也不证明本产品有效。
