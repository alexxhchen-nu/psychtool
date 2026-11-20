# HHS 官方来源与核验记录

建立日期：2026-11-06。

## 核验状态

2026-11-06 更新：已通过第三方 Jina Reader 取得 HHS 官方云计算、去标识化与心理健康 FAQ 的转换正文，并记录关键引文和定位。原站直接访问仍返回 HTTP 403；代理缓存时间未知，尚未与原站实时 HTML 逐字核对，没有另存完整官方网页副本。

此前 TinyFish 超时和原站 403 的记录保留为访问历史。当前证据、访问路径、局限及新增条文研究详见 [隐私资料研究](privacy-research.md)。eCFR 仅取得部分正文，不能声称完成全部法规核验。

## HHS-001：云计算与 HIPAA

- 发布机构：U.S. Department of Health and Human Services（HHS）。
- 官方入口：https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html
- 正文核验：已读取 Reader 转换正文；访问与时效局限见上文及研究文件。
- 用途：核对云服务商角色、业务伙伴协议（BAA）、风险分析及服务安排对电子受保护健康信息处理的要求。
- 对项目的设计关注点：不能仅凭供应商宣传、加密、付费套餐或“数据不用于训练”认定整套系统满足要求；需要核对实际服务范围和数据处理链。
- 已取得证据：适用主体、BAA、无解密密钥存储、责任分配与风险分析，定位见研究文件 HHS-001。

## HHS-002：去标识化指南

- 发布机构：U.S. Department of Health and Human Services（HHS）。
- 官方入口：https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
- 正文核验：已读取 Reader 转换正文；该路径报告重定向至 HHS `/special-topics/de-identification/index.html`，详见研究文件 HHS-002。
- 用途：核对 45 CFR 164.514(b) 下 Safe Harbor 与 Expert Determination 的适用要求。
- 对项目的设计关注点：删除姓名或运行自动扫描不能单独证明去标识化完成；自由文本、日期、稀有特征及信息组合需要纳入评估。
- 已取得证据：两种方法、实际知情条件、专家认定与记录、自由文本及组合识别风险，定位见研究文件 HHS-002。

## 如何在项目中使用

- 将官方原文、产品设计决定与尚待确认的判断分别记录。
- 每项隐私设计决定注明对应来源编号、核验状态及实际适用环境。
- HIPAA 是否适用、是否还涉及其他要求，取决于机构、记录类型与实际关系，不能仅由使用者是 临床培训生推定。
- 学校或实习机构的要求、记录保留与专业责任需单独收集；HHS 页面不能替代这些上下文。
- 公开资料核验只使用通用查询及公共 URL，不携带真实个案内容。
