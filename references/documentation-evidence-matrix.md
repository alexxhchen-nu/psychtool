# 临床文书生成证据矩阵

检索与核读日期：2026-11-06。起点为本目录 `openalex-clinical-documentation.json` 的 10 条候选记录；本次选择其中 5 项直接研究临床记录或出院叙事生成的实证研究。以下区分论文观察、解释边界与项目测试建议，不能把文献数值当成本项目已达到的性能。

本次只读取公开论文、摘要、版本页面和文献索引中的研究方法与汇总结果；没有下载原始患者记录、音频、逐例评估数据或受限测试内容。除明确标注的短引文，描述均为中文归纳。未开展代码测试、模型复现或患者层面的分析。

## 1. 来源身份、获取层级与版本审查

| ID | 已核对来源身份 | 实际获取层级 | 版本、勘误与撤稿检查 |
| --- | --- | --- | --- |
| D1 | Asgari E, Montaña-Brown N, Dubois M, Khalil S, Balloch J, Au Yeung J, Pimenta D. **A framework to assess clinical safety and hallucination rates of LLMs for medical text summarisation**. *npj Digital Medicine*. 2025;8:274. DOI [10.1038/s41746-025-01670-7](https://doi.org/10.1038/s41746-025-01670-7). PMID 40360677; PMCID PMC12075489. | **已发表期刊论文；正文可读并核读相关 Methods、Results、Discussion**：[出版商正文](https://www.nature.com/articles/s41746-025-01670-7)。没有核读全部独立补充材料。 | 出版商页显示 2025-05-13 发表；[Europe PMC core 记录](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1038/s41746-025-01670-7&format=json&resultType=core) 的 `commentCorrectionList` 仅有 “Preprint in”，未出现勘误或撤稿关系。所读正文未见相关公告。此结论仅限这些记录，不是完整 Crossmark/Retraction Watch 清查。 |
| D2 | Seo J, Choi D, Kim T, Cha WC, Kim M, Yoo H, Oh N, Yi Y, Lee KH, Choi E. **Evaluation Framework of Large Language Models in Medical Documentation: Development and Usability Study**. *Journal of Medical Internet Research*. 2024;26:e58329. DOI [10.2196/58329](https://doi.org/10.2196/58329). PMID 39566044; PMCID PMC11618017. | **已发表期刊论文；出版商正文可读并核读方法、结果、表 1–6、局限**：[JMIR 正文](https://www.jmir.org/2024/1/e58329)。 | [Europe PMC core 记录](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.2196/58329&format=json&resultType=core) 没有返回 `commentCorrectionList`；所读正文未见勘误/撤稿公告。不能把字段缺失当作无勘误保证。 |
| D3 | Williams CYK, Subramanian CR, Ali SS, et al. **Physician- and Large Language Model–Generated Hospital Discharge Summaries**. *JAMA Internal Medicine*. 2025;185(7):818–825. DOI [10.1001/jamainternmed.2025.0821](https://doi.org/10.1001/jamainternmed.2025.0821). PMID 40323616; PMCID PMC12053800. | **已发表期刊论文；最终取得 PMC 正文并核读**：[PMC 正文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12053800/)。DOI 首次读取只返回 Crossref 摘要；JAMA 页返回 403，但随后从索引找到公开 PMC 副本，因此最终不是“仅摘要”。补充 PDF 未核读。 | [Europe PMC core 记录](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1001/jamainternmed.2025.0821&format=json&resultType=core) 有 “Comment in”：PMID 40323624，DOI 10.1001/jamainternmed.2025.0827；这是评论关系，不能误标为勘误。未返回 Erratum/Retraction 关系。正文存在 P 值不一致，见 D3 详情，尚未找到解释它的正式勘误。 |
| D4 | Osborne T, Abbasi S, Hong S, Sexton R, Ambut J, Patel NJ, Rosenthal RN, Ung L, Wang F, Wong R. **Towards Inpatient Discharge Summary Automation via Large Language Models: A Multidimensional Evaluation with a HIPAA-Compliant Instance of GPT-4o and Clinical Expert Assessment**. 原候选为 medRxiv DOI [10.1101/2025.04.03.25325204](https://doi.org/10.1101/2025.04.03.25325204)；另找到同题同作者 AMIA proceedings 正文，PMID 41726458、PMCID PMC12919585。 | **候选是预印本，但已找到后续会议论文正文**：[medRxiv v1 正文](https://www.medrxiv.org/content/10.1101/2025.04.03.25325204v1.full)、[AMIA/PMC 正文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12919585/)。结果优先依据 PMC 表 4–7；两版本是同一研究，不能算两项独立重复验证。 | [medRxiv history](https://www.medrxiv.org/content/10.1101/2025.04.03.25325204v1.article-info) 显示 2025-04-04。PMC 页显示 *AMIA Annu Symp Proc*, 2026-02-14;2025:959–968；[Europe PMC core](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:41726458&format=json&resultType=core) 却给出卷/年 2024、电子日期记录与之不一。**保留书目日期冲突，不擅自统一**；该记录以题名/首作者匹配建立 “Preprint in” 关系，未出现勘误/撤稿关系。PMC 未提供新的论文 DOI，不把 medRxiv DOI 当作会议论文 DOI。 |
| D5 | Vishwanath K, Ye B, Alyakin A, Markert JE, Hsieh A, Mańkowski M, Oermann EK. **Large language models are vulnerable to incidental information in clinical documentation and reasoning**. arXiv:2610.08585. DOI [10.48550/arXiv.2610.08585](https://doi.org/10.48550/arXiv.2610.08585). | **未见期刊出版信息的预印本；已读 v2 HTML 的文书生成与音频实验、方法、局限**：[v2 正文](https://arxiv.org/html/2610.08585v2)。仅采用直接文书实验，不以其医学问答/注意力头干预结果替代文书证据。 | [arXiv 记录及提交历史](https://arxiv.org/abs/2610.08585) 显示 v1 为 2026-10-06，v2 为 2026-10-07；读取的是 v2。未显示 journal reference 或独立勘误。**版本更新不等于通过同行评审，也不等于正式勘误；本次没有比较 v1/v2 的全部差异**。 |

获取失败记录：TinyFish 的一次批量全文获取及两次搜索在 MCP 传输层 30 秒超时，没有返回可用证据；后续用 `read`、网页搜索和 Europe PMC 补全公开来源。两次 DOI+correction/erratum/retraction 网页搜索主要返回通用政策，无目标论文公告，故不将搜索未命中作为“勘误已排除”的证据。

候选筛除：Singhal et al. *Large language models encode clinical knowledge* 以医疗问答为核心，不作为临床文书生成效果证据；两篇 narrative/critical review 不是原始实证；认知架构会议论文的候选摘要未建立直接临床文书任务；影像生成论文任务跨图像/文本且与当前文书来源归属问题的贴合度较低。本次没有用这些文献补足数量。

## 2. 实证矩阵与可定位证据

### D1：按源文本逐句评审，可直接指导幻觉/遗漏分开计数

**方法。** 采用 GPT-4-32k-0613，报告 temperature=0、seed=210、top-p=0.95；18 个迭代配置比较结构化提示、模板/风格、“unknown”、JSON/function calling、先抽取事实再生成、二次修订等方案。Results/Dataset 报告每配置 25 条咨询转录、450 对转录—记录、12,999 条记录句子及 49,590 条转录句子。50 名医生参与，每对至少两名医生审阅，不一致由资深医生整合。幻觉从“记录→转录”查证；遗漏从“转录→记录”检查临床相关事实。Major 指不纠正可能改变诊断或管理。

**观察结果。**

- 汇总报告 191/12,999 条记录句子含幻觉（1.47%），其中 84 条为 major；1,712/49,590 条转录句子被标为遗漏（3.45%），其中 286 条为 major。**两个百分比的分母不同**，不能解释成同一文书中“遗漏是幻觉的若干倍”，更不能作为患者受害率。
- 结构/风格与 unknown 组合（实验 3→8）中 major 幻觉 4→1，major 遗漏 24→10；不能把组合变化归因于 unknown 单独的因果效应。
- 先把转录抽成 atomic facts 的配置（实验 5）相比结构化实验 3，major 幻觉 4→25、major 遗漏 24→47。**中间事实抽取未自动带来保真收益**。
- JSON/function calling 的迭代配置 6→11，major 遗漏 61→0、minor 遗漏 130→54，全部幻觉 4→3；实验 11 仍有 2 条 major 幻觉。结构有效不代表事实有效。

**短引文与定位。**

- “each sentence in the clinical note to ensure it was evidenced in the transcript”——Results → Experiments，定位人工 grounding 的方向。
- “output the status ‘unknown’ for instances where information was missing”——Results → Iterative experiments，紧接 Table 1/Fig. 8。
- “major hallucinations increased from 4 to 25”——同节 Fig. 10 前段，记录反向结果。
- 定义详见 Methods → Hallucination and Omission Taxonomy；数值见 Results → Hallucinations / Omissions；双向显示源句见 Fig. 15 图注。

**边界与内部不一致。** 配置反复使用输入，450 对不是 450 个独立就诊事件；样本小、单模型、模拟初级照护，不是儿科神经心理多来源报告。正文 Dataset 用“18×25 PriMock”概括，但方法又列实验 17 为临床医生记录、实验 18 为 ACI-Bench；因此仅引用其作者报告的汇总分母，不宣称全部 450 份均为同质独立 GPT-4/PriMock 记录。作者称低于既往人类记录错误，部分比较来自外部文献，不能据此声称前瞻临床优效或真实伤害减少。作者披露 CEO/员工关系于 Tortus AI；正文随后又写“declare no competing interests”，应保留商业关系作为解释背景。

**测试含义〔设计推论〕。** 生成句子必须映射源片段，另对重要源事实建立遗漏清单；unknown、否定、因果、上下文混淆分别测。比较单步与中间抽取流水线时，在同一冻结输入上同时测两类错误；不得只用 JSON 成功率或字数判定改善。评估样本须与提示调整样本分离。

### D2：格式评分可能掩盖“未询问→无”的内容错误

**方法。** 韩国 Healthcare Prompt-a-thon，52 人、33 份提示生成初次急诊记录，单模型 HyperCLOVA X。输入包括模拟分诊资料、医患对话、体检；正文明确资料为模拟情境。4 名医学专家用 5 项五分量表评审，并进行间隔一个月的复测；错误按 7 类、11 个临床栏目计数。每份提交只运行一次，没有检验同提示多次输出的稳定性。

**观察结果。**

- 212 项错误中 invalid generation 75 项（35.38%），structural malformation 62 项（29.25%），nongeneration 31 项（14.62%）。这些是**错误构成比**，不是记录错误率或逐句幻觉率。
- 总错误数与临床分数相关 r=−0.633，P<.001；结构错误相关 r=−0.654，P<.001。
- 但 Table 5 的 invalid generation r=0.114、P=.53；nongeneration r=0.138、P=.44，均未显示预期的负相关。不能据总相关推称所有事实错误都能被总体质量评分可靠捕捉。
- 初评 accuracy 平均 2.61/5、structure/format 3.30/5。复测总分相关 r=0.776；ICC(3,k) 各项 0.653–0.887，为**多评审平均分一致性**，不能当作模型准确率。

**短引文与定位。**

- “outputs information not provided in the input data”——Table 1，invalid generation 定义。
- “mislabeling unexamined items as ‘None’ ... were often overlooked”——Discussion → Comparing Clinical and Quantitative Evaluations。
- 全部错误计数与相关见 Results → Quantitative Error Analysis 及 Table 5；模拟资料来源见 Methods → Task Development；未评估重复性见 Discussion → Limitations。

**边界。** 小型竞赛、单一韩语模型与特定急诊任务，评价工具经过简化；观察相关不证明实际临床可用性或伤害降低。结构错误定义与 nongeneration 存在概念邻近，不宜直接与 D1 的句子级 taxonomy 合并。更高 retest 分数反映对同批输出的重评分，不能解释为模型经过改进。研究获 NAVER Cloud 支持及 HyperCLOVA X credits。

**测试含义〔设计推论〕。** 用合成缺失信息输入检查“未提及/未评估/明确阴性”是否保持区别；分别评分内容与模板，不允许漂亮格式抵销来源缺失。数值、频次、栏目错放、提示文本回显应有独立失败项。保留双人评审及分歧记录，同时增加重复生成的稳定性评估；后者是补足本文未测试的维度。

### D3：摘要更简洁，可能同时遗漏更多；原始临床材料应作为共同参照

**方法。** UCSF 单中心横断面研究，2019–2022 年 3–6 天住院、存活出院且全程 hospital medicine 的 100 次就诊；另有独立 100 次开发集用于提示工程/评审培训。GPT-4-turbo-128K，temperature=0，把此前非出院临床记录串接生成出院叙事。**人工与模型摘要均对照同一完整输入记录**，不是把人工摘要当作无误标准。22 名 attending 评审，其中 14 名 hospitalist 负责逐例错误、每例两人独立评审及第三人合并重复项；质量另含 PCP/SNF 读者。仅生成叙事部分，不能外推完整出院文书全部字段。

**观察结果。**

- 每份 unique errors：模型 2.91（SD 2.54）vs 医生 1.82（1.94），P<.001；遗漏 1.75（2.09）vs 0.86（1.43），P<.001；不准确 0.93（0.99）vs 0.65（1.01），P=.01。
- 幻觉项均值 0.23 vs 0.31，P=.23，**本研究并未发现模型幻觉显著更多**。错误差异主要由遗漏和不准确驱动。
- 简洁性 4.01 vs 3.70，P<.001；完整性 3.72 vs 4.13，P<.001。总体质量均值 3.67 vs 3.77，没有显著差异。
- 单错误潜在伤害均值 1.35 vs 1.34，P=.99；整份文书 global harmfulness 0.84 vs 0.36（0–7 量表），P<.001。模型有 6 项错误评分≥4，医生有 5 项；是评审判断的潜在伤害，**非观察到患者实际受害**。

**短引文与定位。**

- “we used the full corpus of encounter notes as the reference for both”——Methods → Discharge Summary Narrative Evaluation → Qualitative Evaluation。
- “more omissions and inaccuracies”——Discussion 首段；精确均值见 Results → Qualitative Evaluation: Individual Errors and Harm 及 Figure。
- “more concise ... but less comprehensive”——Results → Qualitative Evaluation: Global Metrics、Table 3。

**边界与正文矛盾。** 摘要/Table 3 的总体质量比较 P=.21，而 Results 的 Overall 段写 P=.67 并误指 Table 2；本矩阵保留这个可见冲突，不挑选更有利数字。上述两值均不能支持优效或等效。单中心、短住院、无跨科转诊；可能被语言风格部分揭盲；未测临床编辑之后的安全、工作时间、真实结局。医生可能掌握未写入此前记录的新事实，故“相对输入无来源”未必等同临床现实中的虚假信息。

**测试含义〔设计推论〕。** 对原始来源包建立共同参照；人工历史报告也接受相同审核。分别测遗漏、来源外新增、数值/时间误写；记录逐错误严重度和整份文书累计负担。用不同字数约束进行配对比较，防止靠删重要信息取得“更简洁”的分数。审批前需要人工逐项审阅的工作量另行实测，本文没有证明节时。

### D4：可读性提高不等于 factuality/完整性已被证明相当

**方法。** 单中心住院内科，2023 年、41–120 小时住院，起始提取 200 次就诊，经记录字符长度等筛选得到 108 次；GPT-4o、Azure、零样本。把筛选的 note types 按时间拼接并保留类型/时间戳/分隔。**只有 28 次进入人工评价**：4 位 hospitalist 各看 7 次，每次只由一人评分；不能将 108 写成安全评价样本量。四项七分量表，加 fabrication/omission、潜在伤害可能性与程度。

**观察结果（以 PMC 正文表为准）。**

- Table 4：模型/人工的 quality 均分 6.4/4.9、readability/conciseness 6.8/5.2、factuality 6.0/5.8、completeness 5.8/5.5。单侧 Wilcoxon：前两项作者报告 P≪.01；后两项均 P=.19。
- Table 7：fabrications 人工 4、模型 9；omissions 人工 13、模型 16（前两数由表的四个类别相加，正文也描述模型约两倍 fabrication）。不能说模型更少幻觉。
- AI omissions 按类别为药物 4、诊断 5、检查结果 2、随访建议 5。Table 5–6 的评审未给任何模型错误 severe/death 程度；这不是排除了罕见严重风险。

**短引文与定位。**

- “evaluated 28 of the 108” 及 “Each of the 28 encounters was evaluated once”——Methods → Manual Evaluation。
- “AI-generated summaries had about twice as many total fabrications”——Results → Manual Evaluation: Fabrication/Omission Detection。
- Table 4、Table 7 可直接定位分数与类别计数；Experimental Setup 定位时间顺序和 note headers。

**边界与矛盾。** 预印本摘要与论文将 factuality/completeness 描述为 comparable，但单侧 P=.19 的未显著结果**不构成预设等效/非劣检验**。小样本、单人逐例评审、长记录被排除、提示未明确列出全部出院诊断/药物要求；未测多来源儿童评估或独立复核的一致性。书目年份/卷存在索引冲突，见来源表；不能把另一个索引条目当成独立研究。作者给出的 API 成本没有包括临床审阅等全流程成本，不能据此证明成本效益。

**测试含义〔设计推论〕。** 明确区分“生成了多少份”与“人工审查了多少份”；药物/诊断/检验/随访等关键内容单列遗漏计数。按来源时间排序可作为候选处理，但不能据本文断定它本身消除时间冲突。若项目拟宣称与专家相当，应先确定比较目标和可接受差值，再设计配对盲评；不得用不显著 P 值宣称等效。

### D5：有源句也可能引用错对象，须检验说话人、事实主体与相关性

**方法。** MedDistractNotes 对 576 条对话构造 clean/distracted 配对；77 条 ACI-Bench 完整访问 + 499 条 MTS-Dialog 片段，后者来自原 500 条片段排除一条仅医生内容。两类干扰为第三人的医学状况及非医学含义的医学词，不改变患者的临床事实。4 个 frontier 模型和 4 个开放权重模型分别每组 4,608 对记录。Claude Sonnet 5 作污染/归属裁判，GPT-5.4 作一般质量裁判，**没有医生验证**。音频实验以 57 次 PriMock 模拟咨询叠加其他咨询的 5–15 秒片段，经无说话人分离的 Whisper large-v3 再生成记录。

**观察结果（均为 v2 作者报告）。**

- Frontier 组 1,612/4,608 distracted notes（35.0%，95% CI 33.6–36.3）写入干扰，clean 组 0/4,608；3.7% 为误归给患者或虽正确归属但被用于患者临床判断。**35% 不能全叫“把他人病史当成患者病史”**，其中大量只是记录了不相关旁谈。
- 分层后 ACI-Bench 完整访问 frontier 污染率 2.6%，MTS 短片段 40.0%；短片段干扰文字占比中位 43%，完整访问为 4%。合并 35% 不是常规完整就诊记录的预期发生率。
- 尽管上述污染，一般五分质量维度平均变化不超过 0.20 分。音频 −10 dB 条件有 55/114 转录（48.2%）出现至少一个背景 content word，24/456 下游记录（5.3%）被判污染；clean 下游记录为 1.3%。**词泄漏率、记录污染率、误归属率是不同指标**。

**短引文与定位。**

- “A check for statements absent from the transcript can miss this failure mode because the source statement is present but does not describe the patient.”——Discussion，直接说明 source presence 的不足。
- “contamination and attribution were judged by a single LLM without clinician validation”——Discussion → limitations 段。
- 样本及分母见 Results → Incidental conversation contaminates generated clinical notes、Fig. 2；音频分母见 Fig. 3 图注；配对与裁判设置见 Methods → Contamination judging / MedDistractAudio benchmark。

**边界。** 未同行评审；干扰为合成插入/叠加，LLM 裁判且未临床验证；主要 pooled 文本置信区间按 note pairs 重采样，未在主分析聚类同一 encounter 的多模型/干扰，作者另列 whole-encounter 敏感性分析。因此不把主 CI 当成独立就诊概率的精确界限。未测医生签署接受率和实际患者伤害。其注意力头干预来自医学问答探针，对文书生成的迁移明确未测试，不能据此提出已经验证的文书修复机制。

**测试含义〔设计推论〕。** 合成多来源输入可保持患者事实不变，分别加入家长谈他人情况、教师引语、非字面词语；评估是否被错归到受评者、是否进入解释/建议。每条引用除 source span 外还应检查说话人、事实主体、时间与临床相关性。文本引用命中只能作证据定位，不能自动判定该主张有支持。音频/ASR 不是当前文本任务的必要实现，但若未来接入音频，应独立验证转录污染再验证下游文书，不能沿用纯文本分数。

## 3. 跨研究解释与本项目可审查的测试方向

以下为研究支持的**设计推论**，并非已验证的产品规格或已运行测试。所有材料可用原创合成例子制作，不需要读取患者资料或复制专有神经心理测验题目。

| 测试主题 | 合成输入与需要观察的行为 | 指标/裁判要点 | 对应证据及适用边界 |
| --- | --- | --- | --- |
| 未知与明确否定 | 一版不提供某既往史，另一版明确否认；检查是否都错误写成“无”。 | 缺失来源事实的断言计数；unknown/否定混淆；重要度单列。 | D1、D2 直接支持风险类型；没有给出本项目通用合格阈值。 |
| 双向来源检查 | 输入包含已标记关键事实；输出每个临床主张均回查来源，来源每个关键事实回查输出。 | 主张→来源的 unsupported 数；重要源事实→报告的遗漏数；保留不同分母。 | D1、D3；不能用 ROUGE、总体满意度或引用存在代替人工事实审查。 |
| 人物归属 | 家长描述自己、同胞、受评儿童；教师和儿童不同叙述分别标记来源。 | 错对象主张、错说话人、无依据因果/诊断/建议计数；冲突须显式保留。 | D5 直接支持第三人污染；“多信息源冲突处理”用于儿科是迁移假设，尚无这 5 项直接验证。 |
| 时间与数值 | 先后不同日期材料，包含更新后的剂量/状态或同指标不同时间值。 | 数值/单位/时间误写；过期事实被当当前；来源可定位但对象/时间错误也判失败。 | D2 信息错误、D4 时间排序是方法先例；没有直接证明某种排序策略的因果优势。 |
| 流水线回归 | 同一冻结案例分别跑直接生成和“抽取→生成”，另比较 unknown/JSON/二次修订。 | 两类内容错误与严重度均比较；结构成功率独立记录；新方法增加重大错误即标记退步。 | D1 有抽取反而恶化的实证，不支持“加一步一定更安全”。 |
| 简洁性与安全 | 同一输入使用不同长度要求，关键事实集合保持一致。 | 质量/简洁评分与遗漏、严重度分别报告，不相互抵扣。 | D3 简洁升高同时完整性下降；D4 亦见可读性改善但 fabrication 更多。 |
| 评审可信度 | 对原创合成例子设已知错误，临床专家盲评；自动裁判对照专家子集。 | 已知错误检出/漏检；双人分歧及裁决；模型、提示、输入、输出版本固定。 | D1 双人+整合、D3 独立开发/测试；D5 自动裁判缺乏医生验证构成反例边界。 |

**不能直接推出的主张。** 这组文献不能证明来源引用机制、RAG、事实抽取或人工点击确认能消除幻觉；不能证明自动生成已降低患者伤害、已节省临床总时间、适用于儿科神经心理解释或优于专家。实际神经心理多信息源整合的合理性与临床可用性需要另外的任务证据。

**应保留的相反发现。** D1 的最佳配置可以降低部分错误，但某中间抽取配置显著恶化；D3 模型更多遗漏/不准确，却没有更多幻觉的显著证据；D4 的总体可读性优势与更多 fabrication 同时存在；D2 和 D5 都说明一般评分可漏掉事实层面的失败。不可将这些差异压缩成“LLM 通常比医生准确”或“LLM 一定更不安全”的单一结论。

## 4. 方法出处与未解决范围

本矩阵使用 research-lookup/citation-management 的来源核验、版本区分与 claim-to-source 组织方法。流程出处：Kassis T, Agarwal V, He Y, Patel D, Brueckner AM. *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*. 2026，arXiv:2609.00065，[DOI 10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065)。已读取 [arXiv 摘要记录](https://arxiv.org/abs/2609.00065) 核对题名、作者与年份；该文不是上述临床效果证据，不计入 5 项实证。

本次 5 项均取得正文，**没有以仅摘要的记录承载全文方法或未见数值**；但没有逐份核读独立补充文件，也没有完整出版后争议追踪。没有找到明确勘误不等于完成勘误清除；D3 的 P 值不一致、D4 的会议年份/卷冲突，以及 D5 未经临床验证的裁判，是引用与后续设计时必须随附的限制。
