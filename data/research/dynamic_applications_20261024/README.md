# 动态报名截图与统考名额的复算输入

本目录是公开的学校/招生单元级聚合输入；[结果、公式和限制](../../../output/research/dynamic_applications_20261024/README.md)说明计算对象。

| 文件 | 作用 |
| --- | --- |
| screenshot_rows.csv | 25页截图转录的242条原始排名，不去掉非目标学校和重复标签 |
| screenshot_manifest.json | 页码、原文件名、排名范围、SHA256和日期证据边界；不公开截图 |
| legacy_quota_selections.json | 对R2已核记录的精确键匹配；各记录明确指定截图排名，避免模糊跨学院合并 |
| quota_overrides.json | 新核对的官方名额记录；包含原文定位和来源ID，不凭数字相似自动合并 |
| reviewed_dates.json | 从公告正文核定的日期；不以采集时间填充发布日期 |
| source_manifest.json | 公共URL、采集时间、状态和SHA256，计算只依赖此公开清单 |
| sources.json | 官方公开页面/附件的采集入口，少量POST仅为公开目录的只读查询 |
| unresolved_quota_leads.json | 已读到但尚不能作为分母的线索及原因，待核数字不参与比值 |

`net_exam_quota`是采用的统考计划/扣推免参考差额，必须同时看`denominator_evidence`、`quota_stage`和`quota_scope`。目录预计统考列不等于推免结算后的最终名额；“已对照原文”不等于人工终审通过。既有R2记录的“截止后”指相对于2026入学年上一次报名截止，此次作2027的历史回退参考，不能回填到2026报名前模型。

JSON中缺失为`null`，CSV为空，不用0占位。`observed_applicants=0`如果真实出现仍保留0；未出现学校不新增0报名记录。录取名单、考生姓名、编号和逐人成绩均不属于本批次公开内容。
