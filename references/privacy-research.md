# 隐私资料研究：云处理、去标识化与心理治疗笔记

研究日期与访问日期：2026-11-06。范围：psychtool 的临床记录辅助设计；仅检索公共资料，没有输入、上传或使用真实个案信息。本文基于 HHS/OCR 官方指南、FAQ 与 eCFR 条文的已取得文本，提供设计依据，不认定 psychtool、任何供应商或任何工作流程已满足合规要求。

## 1. 证据状态与来源

已阅读 [hhs-sources.md](hhs-sources.md)。该文件记录的是此前访问失败及待核验问题；本次取得了相关正文，但没有修改原文件。

本次 TinyFish 的批量正文读取与搜索均在 30 秒 MCP 请求期限处超时；改用原始 HHS URL 直接读取，云计算、去标识化与两份心理健康资料仍返回 HTTP 403；Exa 批量正文读取也超时。随后通过 Jina Reader 读取公共官方页面，成功取得云计算问答、去标识化指南及两份 FAQ 正文。eCFR 直接访问出现自动访问限制页面，Reader 路径取得了目标条文的部分正文。

**证据等级约定：**

- **已取正文**：实际读取到官方页面内容的 Reader 转换文本，可引用其中明确出现的段落；这是官方原文的第三方传递文本，未完成与官方原站实时 HTML 的逐字校验，代理缓存时间未知。
- **搜索摘要**：仅用于发现地址；下文实质结论不以搜索摘要代替正文。
- **[INFERENCE] 设计推导**：由上述材料推导的产品建议，不是 HHS 对本项目的决定。
- **机构待确认**：学校、实习机构、诊所、督导或实际合同中的事实，公共指南无法回答。

| 编号 | 官方来源与定位 | 日期及本次访问状态 |
| --- | --- | --- |
| HHS-001 | [Guidance on HIPAA & Cloud Computing](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)，Introduction、Q1–Q11 | 已取正文；Reader 元数据显示 Published Time 为 2016-10-06；提取文本未显示内容最后审阅日期，因此不把发布日期当作更新时间。[本次读取路径](https://r.jina.ai/https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)。 |
| HHS-002 | [Guidance Regarding Methods for De-identification…](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)，标准、§2、§3 | 已取正文；原清单中的 `/privacy/special-topics/de-identification/index.html` 经 Reader 报告重定向到左列地址；Published Time 为 2012-09-07，未取得页面最后审阅日期。[本次读取路径](https://r.jina.ai/https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)。 |
| HHS-003 | [Does HIPAA provide extra protections for mental health information compared with other health information?](https://www.hhs.gov/hipaa/for-professionals/faq/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html)，正文两段 | 已取正文，页面明示 Content last reviewed September 12, 2017；原带 `/2088/` 的地址转至左列地址。[本次读取路径](https://r.jina.ai/https://www.hhs.gov/hipaa/for-professionals/faq/2088/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html)。 |
| HHS-004 | [Does a parent have a right to receive a copy of psychotherapy notes about a child’s mental health treatment?](https://www.hhs.gov/hipaa/for-professionals/faq/does-parent-have-right-receive-copy-psychotherapy-notes-about-childs-mental-health-treatment.html)，正文两段 | 已取正文，页面明示 Content last reviewed September 12, 2017；原带 `/2094/` 的地址转至左列地址。[本次读取路径](https://r.jina.ai/https://www.hhs.gov/hipaa/for-professionals/faq/2094/does-parent-have-right-receive-copy-psychotherapy-notes-about-childs-mental-health-treatment.html)。 |
| CFR-001 | [45 CFR §164.508](https://www.ecfr.gov/current/title-45/section-164.508)，(a)(2)(i)(A)–(C)、(b)(3)(ii) | Reader 取得部分条文；页面显示 Title 45 up to date as of 11/04/2026，并自述 authoritative but unofficial。这是整个 Title 45 的状态，不等于本条修订日期。转换文本缺少部分编号段落，不把它当作全部授权例外的完整清单。[本次读取路径](https://r.jina.ai/https://www.ecfr.gov/current/title-45/section-164.508)。 |

下列短引文保留在本文，便于以后核对；没有另存完整官方网页副本。页面当前可被代理读取，也不代表已证明这些指南涵盖截至研究日的所有修法、州法与机构规则。

## 2. 云处理：BAA、加密与责任不能互相替代

### 2.1 谁可能是业务伙伴

**已取正文，HHS-001 Introduction、Q1、Q2：** 当 covered entity 委托云服务商（CSP）代表其创建、接收、保存或传输电子 PHI（ePHI）时，服务商属于 business associate；business associate 再委托的相应云分包商也属于 business associate。这包括仅保存加密数据、没有解密密钥的情形。

> “Lacking an encryption key does not exempt a CSP from business associate status and obligations under the HIPAA Rules.”

来源：[HHS-001](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)。不能仅从使用者是 临床培训生推定 HIPAA 适用；指南对 covered entity、workforce 与 business associate 的定义涉及主体身份及实际服务关系。

**已取正文，Q3：** conduit 例外主要限于传输服务及传输附带的暂存；持续存储或处理 ePHI 的云服务通常不因无法查看内容而成为 conduit。不能仅因为一个产品称自己是“中转层”便套用此例外。来源同上，Q3。

### 2.2 BAA 是相关前提，不是产品认证

**已取正文，Q1：** HHS 允许相关主体使用云服务处理 ePHI，前提包括与相应 CSP 签订 BAA，并遵守其他适用要求。BAA 规定允许及要求的使用、披露、安全保护等；各方仍需理解实际云环境并开展风险分析与风险管理。Q2 明确指出，加密不能单独覆盖完整性、可用性、应急恢复、行政与物理保护等问题。

> “OCR does not endorse, certify, or recommend specific technology or products.”（Q4）

来源：[HHS-001 Q1、Q2、Q4、Q5](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)。因此，不能凭“付费账户”“不用于训练”“已加密”或营销中的 HIPAA 标签，对整条数据处理链作合规结论。

**[INFERENCE] 对 psychtool 的设计含义：** 如果未来要处理真实临床内容，应先画出实际接收者清单：前端与服务端、模型 API、数据库、文件存储、日志、错误追踪、备份、客服访问与分包商。逐项核对实际产品、套餐、端点与合同覆盖范围，并明确谁负责访问控制、密钥、删除、恢复和事件响应。HHS 没有逐项列出这里所有现代 AI 组件；这个清单是把指南的处理链与风险分析要求应用到产品设计。

### 2.3 退出服务、地域与事件处理

**已取正文，Q1、Q6、Q8–Q10：**

- SLA 可处理可用性、备份与恢复、服务结束后的数据返还、安全责任，以及使用、保留和披露限制；其内容应与 BAA 一致。
- 服务商的安全事件处理、记录和报告，与达到未受保护 PHI 泄露门槛后的通知义务有关但并非完全同一件事；不能把“有加密”直接推成“不必处理或报告任何事件”。
- 服务结束时，BAA 应要求可行时返还或销毁 PHI；如不可行，需延续保护并限制后续用途。该段没有给出适用于本项目的临床病历保存年限。
- Q9 没有提出 HIPAA 下绝对的美国境内存储要求，但要求将地域、风险与保护措施可执行性纳入评估；这不证明机构允许境外处理。
- Q10 说 HIPAA 本身不明确要求 CSP 向客户提供全部安全文档或接受客户审计；客户可以根据自身风险分析，通过合同索取额外保证。不要把自行选择的供应商审查材料一律说成 HHS 逐项强制要求。

来源：[HHS-001](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)。

## 3. 去标识化：删除姓名与“扫描通过”都不足以单独作结论

### 3.1 两条路径与各自条件

**已取正文，HHS-002 “The De-identification Standard”：** 指南引述 45 CFR §164.514(a)–(c)，提供两种方法。

| 方法 | 正文中的条件 | 对产品的含义 |
| --- | --- | --- |
| Expert Determination | 具有适当统计与科学知识、经验的人，结合预期接收者及其他合理可获得信息，判断识别个体的风险 very small；记录支持结论的方法与分析结果。§2.2 说没有单一指定学位或认证；§2.3 说没有适用于所有情境的固定数值风险阈值。 | **[INFERENCE]** 模型自评、固定“匿名分数”或开发者声明不能替代这一路径。需要明确专家、具体数据、接收者和分析文档。 |
| Safe Harbor | 移除列明的 18 类标识符，范围包括记录主体及其亲属、雇主或同住者；同时 covered entity 不得实际知悉剩余信息可以单独或结合其他信息识别主体。 | **[INFERENCE]** 必须同时检查指定标识符与剩余叙事情境；检测器的“未发现”只能是辅助结果。 |

来源：[HHS-002 标准](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#standard)、[专家资格](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#expert)、[风险水平](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#idrisk)。

Safe Harbor 的 18 类按原 A–R 次序为：姓名；小于州的地理划分；与个人直接相关的日期要素及高龄信息；电话；传真；电子邮件；社会安全号码；病历号；健康计划受益人号；账户号；证书或执照号码；车辆标识及序列号；设备标识及序列号；URL；IP 地址；指纹、声纹等生物识别标识；全脸照片及可比图像；其他独特识别号码、特征或代码。地理项的邮编前三位存在基于最新公开人口普查数据的条件例外；不能直接硬编码指南列举的旧人口数据。日期通常只能保留年，超过 89 岁及可推知该年龄的日期要素有额外处理要求，可归为“90 岁及以上”。来源：[HHS-002 标准及 §3.1–3.4](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#safeharborguidance)。

### 3.2 自由文本与组合信息

**已取正文，§3.10：**

> “The de-identification standard makes no distinction between data entered into standardized fields and information entered as free text…”

> “…an identifier listed in the Safe Harbor standard must be removed regardless of its location in a record if it is recognizable as an identifier.”

该节明确举出 progress notes、出院摘要等自然语言文档，说明临床叙事包含丰富的历史和生活方式信息，可能容易识别个体。§3.5–3.6 举出的情形包括特殊职位、明确的家庭关系、被媒体报道的稀有临床事件，以及已知接收者拥有识别手段。来源：[HHS-002 §3.10](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#protected)、[§3.5](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#uniquenumber)、[§3.6](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#actualknowledge)。注意页面 `#protected` 同时出现在顶部 PHI 定义相关导航中，定位时应以完整节标题 “Must a covered entity remove protected health information from free text fields…” 为准。

**已取正文，§3.7：** actual knowledge 指清楚、直接知悉本次剩余信息可识别个体。仅仅知道存在重识别研究，不自动构成该条件；不应把该要求描述为所有理论风险必须归零。指南同时明确：两种方法正确应用后的识别风险也不是零。来源：[§3.7](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#specificstudies)、[De-identification and its Rationale](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#rationale)。

**[INFERENCE] 对 psychtool 的设计含义：**

1. 提供不涉及真实个案的虚构样例，让设计、模板与交互工作可以继续。不能把“从真实案例改几个细节”未经评估地叫作虚构或已去标识化。
2. 若将来有机构允许的真实数据工作流，先明确处理发生在何处、由谁负责、使用哪条去标识化路径、对哪个接收者有效。扫描应提示直接标识符、日期、罕见经历和关系线索，并明确保留人工及机构判断；不显示“保证匿名”或“自动合规”。
3. 先把原始内容发送到外部模型再要求其去标识化，不能让先前的传输追溯变成只传输了去标识化信息。HHS-002 允许业务伙伴按 BAA 授权范围代表机构进行去标识化；HHS-001 Q11 的前提是云端**仅接收、保存已经按规则去标识化的信息**。来源：[HHS-002 “Covered Entities, Business Associates, and PHI”](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html#coveredentities)、[HHS-001 Q11](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html)。
4. 代号不等于完成去标识化。§164.514(c) 下允许的重识别代码有来源与保密条件；§3.2 明说姓名缩写等残余标识符不满足 Safe Harbor；§2.9 关于专家认定下的哈希另有条件，不能混用两条路径。来源：[HHS-002 标准、§2.9、§3.2](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)。

## 4. Psychotherapy notes 与普通临床／进展记录

### 4.1 分类取决于内容、作者和分离保存

**已取正文，HHS-003：** HIPAA 通常对不同类型 PHI 统一适用；psychotherapy notes 是有额外保护的一类。其定义是由心理健康专业的医疗服务提供者记录、用于记载或分析个别、团体、联合或家庭咨询谈话内容，并且与其余病历分开保存的笔记。

> “…documenting or analyzing the contents of a conversation … and that are separate from the rest of the patient’s medical record.”

来源：[HHS-003，第一段，引用 §164.501](https://www.hhs.gov/hipaa/for-professionals/faq/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html)。

| 内容或形态 | 官方原文可支持的区分 | psychtool 的设计推导 |
| --- | --- | --- |
| 谈话内容的记录／分析，符合专业作者条件，且与其余病历分开 | 可能落入 psychotherapy notes 的定义；不能仅凭文件名判断。 | **[INFERENCE]** 如需支持，应由机构确认分类，并与普通进展记录分开管理权限、检索、导出与分享。 |
| 药物处方和监测、会谈起止时间、治疗方式与频次、临床测试结果 | HHS-003 明确排除在 psychotherapy notes 定义之外。 | **[INFERENCE]** 不因为由心理治疗者书写就一律套用私人笔记分类。 |
| 诊断、功能状态、治疗计划、症状、预后、迄今进展的摘要 | HHS-003 明确排除；保存在病历中的信息也不属于该定义的 psychotherapy notes。 | **[INFERENCE]** 常规临床摘要或进展记录草稿应作为独立任务设计；不能通过改名规避普通病历规则。 |
| 学习反思、督导笔记、病例概念化草稿 | 本次材料没有给这些日常名称一个自动适用的统一分类；其中仍可能包含可识别健康信息。 | **[INFERENCE]** “仅供学习”“草稿”或“个人笔记”都不能自动解除保护；需机构按实际内容和使用方式判定。 |

本表事实来源均为 [HHS-003](https://www.hhs.gov/hipaa/for-professionals/faq/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html)；第三列不是已确认的机构政策。普通记录不属于 psychotherapy notes，不等于它可以自由披露。

### 4.2 授权与培训例外不能被省略

**已取正文，HHS-003 第二段：** 除少数例外，披露 psychotherapy notes 通常需要患者授权，甚至包括为了治疗而披露给原作者之外的医疗服务提供者。HHS 举出法律要求的披露及某些强制报告／警示情形，且提醒州法有所不同。来源：[HHS-003](https://www.hhs.gov/hipaa/for-professionals/faq/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html)。这不是“所有心理健康信息一律需要特别授权”，也不是“治疗用途永远不需授权”。

**已取正文，CFR-001 (a)(2)(i)(B)：** 条文另列 covered entity 为其自身培训项目进行使用或披露的例外，涉及学生、受训者或心理健康从业者在督导下学习／改进个别、团体、联合或家庭咨询技能。

> “Use or disclosure by the covered entity for its own training programs in which students, trainees, or practitioners in mental health learn under supervision…”

来源：[45 CFR §164.508(a)(2)(i)(B)](https://www.ecfr.gov/current/title-45/section-164.508#p-164.508(a)(2)(i)(B))。本次转换文本还取得原作者治疗使用与机构应对当事人提起法律程序等段落，但部分其他编号段落未提取，本文不枚举全部例外。

**[INFERENCE]** 不能因“学生在接受督导”就断言外部 AI 上传落入上述自身培训项目例外；也不能断言所有培训使用一概必须另外取得授权。psychtool 是否属于机构自身项目、外部服务角色、允许用途、患者授权与州法条件，都需要结合实际安排确认。BAA 与 psychotherapy notes 的使用／披露依据是不同问题，不能用“供应商签了 BAA”代替记录类型与用途判断。

**已取正文，CFR-001 (b)(3)(ii)：** psychotherapy notes 的使用／披露授权只能与另一份 psychotherapy notes 授权组合。**[INFERENCE]** 因此不能把一个通用“同意使用 AI”勾选框直接说成满足该条要求的有效授权。来源：[§164.508(b)(3)(ii)](https://www.ecfr.gov/current/title-45/section-164.508#p-164.508(b)(3)(ii))。

### 4.3 访问权与“绝不向患者提供”不是一回事

**已取正文，HHS-004：** HIPAA 的个人／个人代表访问权包含 psychotherapy notes 例外；普通病历内的诊断、症状、计划等信息与之不同。该 FAQ 同时说，HIPAA 一般允许服务提供者自行决定向本人或其个人代表直接披露本人的信息，包括 psychotherapy notes，并应先查看州法是否限制或附加条件。

来源：[HHS-004，引用 §164.524(a)(1)(i)](https://www.hhs.gov/hipaa/for-professionals/faq/does-parent-have-right-receive-copy-psychotherapy-notes-about-childs-mental-health-treatment.html)。其家长问题有未成年人及个人代表背景，不能据此推断每位家长总能取得孩子全部资料。

**[INFERENCE]** 导出功能不应把所有笔记默认混成一份“完整病历”，也不应宣称 psychotherapy notes 永远不能提供给本人。具体访问、授权、审查和导出规则应由负责记录的机构决定。

## 5. 可立即推进的设计，以及仍需机构材料的事实

**[INFERENCE] 可立即推进：** 在不接入真实个案的条件下，先完成虚构样例、记录类别说明、普通进展记录的结构化草稿、人工审阅／修改／确认流程，以及数据流与供应商清单。把“待检查的隐私线索”与“已正式确认去标识化”区分呈现，避免用扫描结果作法律结论。普通记录与私人谈话分析笔记使用不同的产品入口与预览／导出范围；这属于设计建议，并非已批准真实资料进入系统。

以下问题没有从公开 HHS 文本得到项目特定答案，不把调查问卷作为继续所有设计工作的前提，但真实资料接入决定需要相应证据。

| 尚未确认的事实 | 应取得的材料或确认主体 | 直接影响的设计决定 |
| --- | --- | --- |
| 记录所属机构是谁；HIPAA covered entity／workforce／business associate 关系；教育记录是否涉及 FERPA | 学校、实习机构或诊所的适用范围说明、角色和记录归属制度 | 产品用户与机构权限、允许处理的数据范围；不能由学生身份直接推定。 |
| 哪些内容属于正式病历、psychotherapy notes、督导资料或一般学习材料 | 机构病历模板、分类政策、督导及隐私负责人的解释 | 输入类别、保存分离、检索与导出边界。 |
| 是否允许个人设备、个人账户、外部模型和云服务；允许哪些具体功能与端点 | 机构 AI／外部工具政策、批准服务清单、合同与 BAA | 是否能开放真实资料模式、具体服务及可访问者。 |
| 督导分享是否属于机构自身培训项目；是否需患者授权及其范围 | 培训项目安排、机构解释、适用授权文件；不能仅依据“有督导” | 督导共享、外部 AI 使用和跨机构流转。 |
| 采用哪种去标识化方法，谁负责认定，接收者能接触哪些其他信息 | 去标识化流程、专家分析或 Safe Harbor 的实施及复核记录 | 扫描提示与正式确认的责任、发送边界、可保留信息。 |
| 病历／草稿／日志／备份的保留、返还、删除与离岗交接 | 州法和机构保存政策、服务合同、法律保留要求 | 删除按钮、备份周期、导出与账号停用；不能从云指南 Q8 推导统一保存年限。 |
| 地域、分包商、客服访问、故障与安全事件责任 | 供应商具体服务文档和合同、机构风险分析 | 部署地域、数据路径、支持权限、事件联络与处理。 |
| 未成年人、药物使用障碍记录等是否有额外适用要求 | 实际业务范围、机构隐私／法律材料及相关专门规则 | 访问与授权例外、分享和导出的具体限制；本文未研究其全部规则。 |

HHS-002 已说明 PHI 定义中的若干教育／雇佣记录例外，并在脚注提示 FERPA 或其他联邦保护可能另行适用；这只能支持“需判断具体制度”，不能证明 psychtool 已适用或被排除。来源：[HHS-002 “Protected Health Information”、Glossary 与脚注 4](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)。

本次交付仅为资料研究，未运行测试、构建或格式化；未读取机构内部政策、患者授权或供应商实际合同，未对真实数据流程进行审计。
