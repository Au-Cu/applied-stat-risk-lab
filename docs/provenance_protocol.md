# 数据来源、审计链与逐名成绩最小化协议

## 1. 证据链的基本原则

本项目不把研究者整理的 Excel 工作簿当作“公开原始来源”。工作簿是一个可复查的证据索引，其作用是把异质公开材料整理成统一字段；真正支撑数值的证据仍是学校、学院、教育部、研招网、公开名单图片或可核二次汇总。

每个建模字段尽可能保留以下链条：

```text
公开网页 / PDF / 名单图片
  → 工作簿的来源单元格
  → 工作簿的学校—年份—字段值单元格
  → 标准化处理行
  → 训练标签、特征或审计标记
  → 模型运行清单与论文图表
```

源工作簿的 SHA256 为：

```text
7104049cab26bbfe9db59035e71aa0d9e4430873cacc7b319742a370a6244865
```

仓库内只读副本与用户提供文件逐字节一致。工作簿中公开 URL 主要以单元格普通文本保存，而非 Excel 超链接；因此不能用“超链接数量为零”误判为没有来源。

## 2. 字段级台账

`scripts/build_provenance_ledger.py` 从“年度线与录取”“院校总表”“来源台账”三张表生成三个规范化文件：

- `data/processed/program_year_provenance.csv`：学校—年份—字段—公开 URL 一行一条；
- `data/processed/school_master_provenance.csv`：院校考试科目、教材和大纲字段的来源链；
- `data/processed/source_registry_urls.csv`：把来源台账中同一单元格的多个 URL 拆为一行一个 URL。

字段台账同时记录：字段值、来源 URL、域名、来源类型、权威等级、工作簿 SHA256、工作表、值单元格、来源单元格和原始行号。若一个来源单元格同时列出多个 URL，只标记为 `cell_scope`，不虚构“某个 URL 唯一支持某个字段”的精确对应。

截至 2026-10-09，405 个学校—年份记录全部至少有一个公开 URL；3,690 个非空核心字段中 3,685 个可回到公开 URL，字段级覆盖率为 99.86%。剩余 5 个字段保留 `missing_public_url`，进入人工补链队列，而不是被默认为“来源可靠”。详细统计见 `data/audit/provenance_coverage.json`。

同日对 694 个唯一 URL 做轻量可达性检查：464 个可直接访问，230 个返回失败或被服务器阻断。失败中 218 个来自已下线路灯考研页面，另有少量官网旧链、证书或反爬问题。历史 URL 不会因此从台账删除；`source_url_audit.csv` 同时保存检查时间、状态码和错误。对于失效的第三方校年链接，公开小程序接口提供了 984 条“值完全一致”的补充字段证据，覆盖 356 个校年；225 个含失效第三方链接的校年中，215 个已获得至少一条仍可访问的值一致补充来源。补充来源只并列，不覆盖原记录。

院校静态表中大量科目与培养单位原先只有全局目录来源，无法逐字段定位到院校详情页。`build_school_master_supplemental_provenance.py` 又将公开详情接口与处理后院校表逐值核对，形成 642 条精确或预先定义的语义等价补链，覆盖 79 所学校；其等级始终为 `secondary_structured`，不会因为数值相同而冒充学校官方原文。

## 3. 来源等级

规范化台账把来源类型和“工作簿声明的证据等级”分开保存：

| 类型 | 台账等级 | 解释 |
| --- | --- | --- |
| 学校/学院官网、教育部、研招网 | `primary_official` | 原始官方证据，优先级最高 |
| 小程序结构化详情接口 | `secondary_structured` | 可机器复查的二次结构化材料，不等同官方 |
| 小程序公开名单图片 | `secondary_snapshot` | 可哈希固定的二次名单快照，须和独立汇总交叉核验 |
| 微信文章 | `secondary_article` | 可核二次报道，用于交叉验证或补充线索 |
| 其他网页/PDF | `unclassified_*` | 尚未完成权威性分类，不自动提升为官方 |

“官方优先”不等于自动相信所有官网数字：还要核对培养单位、专业代码、学习方式、普通统考/专项、第一志愿/调剂和名单发布时间。

## 4. 小程序名单索引与隐私最小化

`scripts/fetch_mini_program_roster_index.py` 访问工作簿已经记录的公开学校详情接口。接口响应同时包含公开专业资料和评论区内容；程序只选择 `schoolMajorVO` 及其中的 `majorRepeatList`，在内存中直接丢弃评论、头像、昵称和用户标识，不写入任何文件。

`mini_program_year_index.csv` 还保留接口公开的年度复试线、拟录取最低分、复试人数和拟录取人数。`scripts/build_supplemental_provenance.py` 只有在这些值与工作簿处理值落在预先声明容差内时，才把接口添加为补充来源；不一致的 765 个候选项只进入审计报告，绝不自动改写数据。

`scripts/collect_roster_assets.py` 下载公开名单图片，保存 URL、HTTP 状态、尺寸、字节数和 SHA256。原图可能含姓名或考号，因此只能存放在被 Git 忽略的 `data/private/roster_assets/`，不得提交到公开仓库。公开 manifest 只保留来源与哈希。

`scripts/extract_candidate_scores.py` 不对姓名列做 OCR，只识别：

1. 图片标题，用于确定学校、年份、专业与名单阶段；
2. 图片脚注，用于判定绿色行代表拟录取或未拟录取；
3. 总分列，用于提取初试总分。

本地逐人表使用不可逆的“图片 SHA256 + 行索引”哈希作为行标识，不保存姓名、考号或微信用户信息。即便去名后的“学校—年份—分数—名单行号”仍可能被重新链接，逐人表也只写入 Git 忽略的 `data/private/`；公开仓库仅保留校年级人数、Q10、四项核对结果、URL 和图片哈希。

## 5. 真实 Q10 的升级门槛

一张图片不能因为标题写着“录取名单”就直接成为精确标签。学校—年份只有同时满足以下条件才进入 `model_eligible=true`：

1. 标题可识别为全日制 025200 应用统计目标人群；
2. 图片本身明确给出拟录取行或未拟录取行的标记规则，或图片就是完整拟录取名单；
3. 已排除专项、推免、调剂、非全日制等非目标人群；
4. 去标识化逐行数据的拟录取人数与独立汇总完全一致；
5. 逐行分数的最低分、中位数、最高分与独立汇总分别在预先设定的 0.51、0.76、0.51 分容差内一致；
6. 来源 URL、图片哈希、OCR 置信度、识别行号和校验状态完整保留。

只满足“复试名单可读”但无法识别谁最终拟录取的记录，仍可进入本地私有的 `data/private/retest_initial_scores.csv` 作为竞争强度材料，不能冒充真实拟录取 Q10。为避免“未晋级即丢弃”，逐人数据按用途分层：

1. `exact`：人口口径与汇总对账通过、样本量不少于 10，可直接形成经验 Q10；
2. `soft`：专业、学习方式、图例、排序和 OCR 质量内部一致，但外部汇总尚未完全闭环，只能降权进入分布形状敏感性；
3. `diagnostic`：口径不明、特殊人群或汇总不一致，只用于发现问题和安排人工复核；
4. `not_admitted`：图例明确时用于描述复试选择梯度；
5. `unknown_outcome`：只描述复试池分布，不转换成录取标签。

本次运行共索引 452 张名单图片，412 张形成结构化解析结果；读取 14,317 条初试总分，60 条完全重复行不重复计数。最终 77 个校年、44 所学校、2,312 条本地私有拟录取分数进入精确 Q10 层；另有 5,199 条拟录取软证据和 1,562 条拟录取诊断记录。2,444 条明确未录取记录与已录取记录共同构成 200 个合格复试选择队列；2,800 条结果未知记录保留在复试池敏感性层。公开审计只给出校年或全局聚合，不输出候选哈希。

## 6. 快照与可复现性

当前公开图片快照均有 SHA256；外部网页/PDF 仍以 URL 为主，尚未全部完成本地快照。因网页可能更新或撤回，后续应按以下顺序补齐：

1. 官方 PDF/HTML 保存本地只读快照；
2. 记录抓取时间、HTTP 状态、Content-Type、字节数和 SHA256；
3. 对同一字段的多个冲突版本保留全部快照，不覆盖旧证据；
4. 每次预测发布声明精确的数据冻结时间；
5. 任何结果揭示后的修改必须另建模型版本，不能回写既有前瞻基线。

## 7. 已知限制

- 99.86% 是“字段存在公开 URL”的覆盖率，不代表 99.86% 的字段已经由官方逐项人工确认。
- 工作簿部分单元格同时列出多个来源，现阶段只能做到单元格级关联。
- 小程序名单图片属于可核二次快照；即使通过汇总一致性校验，也应继续寻找学校官方名单交叉验证。
- OCR 的机器一致性校验可以发现大量漏读或错读，但不能代替所有图片的人工抽查。
- 当前模型的精确标签覆盖仍受公开名单年份和排除口径限制；未通过升级门槛的校年继续使用代理标签并降低权重。

## 8. 复现命令

```powershell
.\.venv\Scripts\python.exe scripts\audit_source_workbook.py `
  data\source\applied_statistics_985_211_2026_source.xlsx `
  --output output\audits\source_workbook_20261009
.\.venv\Scripts\python.exe scripts\build_provenance_ledger.py
.\.venv\Scripts\python.exe scripts\fetch_mini_program_roster_index.py
.\.venv\Scripts\python.exe scripts\collect_roster_assets.py
.\.venv\Scripts\python.exe scripts\check_source_urls.py
.\.venv\Scripts\python.exe scripts\build_supplemental_provenance.py
.\.venv\Scripts\python.exe scripts\build_school_master_supplemental_provenance.py
.\.venv\Scripts\python.exe scripts\extract_candidate_scores.py --workers 4
.\.venv\Scripts\python.exe model\validate_candidate_scores.py
```
