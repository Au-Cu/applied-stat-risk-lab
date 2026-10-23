# 名额证据数据字典（R2）

本字典补充[R1字段定义](quota_deadline_collection_20261023.md)，不改变正式模型的冻结输入。年度始终指入学年。

| 字段 | 定义与限制 |
| --- | --- |
| `reported_exam_quota` | 原文明确的统考/公招计划列；须联合记录类型判断拟招、推免结算及专项状态 |
| `total_plan_same_scope` | 原文总计划列；候选记录仍可能未核定学习形式或学院范围 |
| `accepted_recommended` | 已接收/拟录取推免的原文统计；学习形式待核时仍不能扣减全日制T |
| `planned_recommended` | 拟接收推免计划，永不自动当实际R |
| `total_less_accepted` | T、实际R均为数字时的算术差额；不是普通统考核定量 |
| `actual_exam_admitted_count` | 事后统考录取数，对照层；不能冒充当年报名前计划 |
| `actual_all_admitted_count` | 事后含推免录取总数，对照层 |
| `unclassified_plan_count` | 从计划资料转录但总/净范围尚未核定的数值 |
| `unclassified_recommended_count` | 尚未核定是计划推免还是实际接收的原文列值 |
| `unclassified_numeric_count`, `raw_numeric_cells` | 坐标行恢复的未分类数字/同一行数字数组；甚至未确认哪列为名额，不可入模 |
| `study_mode` | `全日制`或`待核`；目标为全日制不意味着每份混合原表都能自动归到全日制 |
| `unit` | 培养单位/独立项目；待核行禁止跨学院合并 |
| `ordinary_scope_verified` | 仅表示普通/专项范围有明确证据，不代表时间、实际推免及其余前提全部完成 |
| `effective_publish_date` | 当前记录版本的公开证据日或证据齐备日；不是保证第一次发布的时间 |
| `nominal_notice_publish_date` | 父公告初发日期；若现挂附件更晚或版本不明，不能替代当前数值版本时间 |
| `publication_precision` | `date`或`minute`；同日无时刻无法依发布日期判定22:00前可见 |
| `publication_date_basis` | 正文、配套公告、版本标注等取时间依据；不使用URL和HTTP元信息替代 |
| `capture_time` | 获取原件的带时区时间，不是假定的发布日期 |
| `observation_as_of` | 原表说明“截至某时”的统计时点，不是公开时间 |
| `observed_before_deadline` | 构成该记录的原件抓取均早于对应截止；只适用于当次原件，不能证明历史版本 |
| `available_by_deadline` | `true`/`false`/空：由当次抓取或可靠公开证据时间支持；仍不保证口径合格 |
| `availability_basis` | 可见性证据及历史版本限制 |
| `deadline_timing` | 仅按公开证据日及精度计算的截止关系；与抓取证明可见是两个维度 |
| `source_grade` | `A-official`官方原文、`B-reprint`转载；转载日期不冒充原官网初发日期 |
| `review_status` | 原文数字核对、规则待读、历史待纠错、待用户终审等阶段；不得混称人工终审通过 |
| `model_eligible` | 本批统一为false，阻止研究候选自动替换正式模型输入 |
| `source_ids` | `r1:`、`r2:`区分采集批次，避免不同批次同名证据ID撞车 |
| `source_sha256`, `primary_source_url`, `source_locator` | 原件哈希、原文URL与行/页定位；哈希不能证明更早年份可见 |
| `legacy_unit_parse_raw` | 旧批次错误单位解析的原始内容，仅作追查，不参与单位匹配 |

`coverage_gaps.csv`中的所有数量都是**记录数**，例如`fulltime_actual_recommended_records=0`只表示未取得合格记录，不表示该校推免人数为0。`strict_ordinary_net_records`还要求截止前、学习形式、专项和直接推免后计划条件同时成立；它不是学校实际录取人数。

`recommended_roster_counts.json`的`all_modes_count`为同校025200跨单位公示计数；`explicit_fulltime_count=0`可能只是没有逐行标明模式。该文件不公开姓名、考生编号、单人成绩或个人去重哈希。`target_rows_without_same_row_identifier`提示读取未闭合，不得把未读出的行自动判为0人。
