# 模型精度优化路线图

## 判断原则

择校预测不是只追求平均误差最低，而是要同时控制“把一所危险学校误判为稳”的代价。所有优化必须在报名时点信息约束下做逐年滚动样本外验证，不能用当年最终录取人数、报名人数或最终名单反向解释当年。

当前瓶颈首先是标签和暴露量的测量误差，其次才是模型形式。295 个训练目标均为透明 Q10 代理，精确考生级 P10 为 0 条；在这种条件下直接增加深度模型，容易只把代理误差拟合得更精细。

## v0.2 已验证改进

v0.2 新增“历史国家线以上边际分中位数”锚点。对于学校 `s` 和待预测年份 `t`：

```text
robust_margin(s,t) = median{Q10_proxy(s,k) - national_line(zone,k) : k < t}
center(s,t) = predicted_national_line(zone,t) + robust_margin(s,t)
```

它把跨年国家线变化剥离，并用中位数降低单年爆冷、爆热和代理异常的影响。在 2024—2026 expanding-window 回测中：

| 候选策略 | 加权 MAE |
| --- | ---: |
| 历史边际分中位数锚点（可比样本） | 17.12 |
| 上一年锚点（可比样本） | 18.58 |
| 分层贝叶斯 + 梯度提升复杂候选 | 20.35 |
| v0.2 完整主流程 | 17.67 |

因此，v0.2 优先使用稳健锚点；历史不足时依次回退上一年锚点和复杂候选。复杂模型仍用于分布尾部、变量贡献与缺失锚点场景。

## 优先级

| 优先级 | 优化 | 为什么可能有效 | 验收标准 |
| --- | --- | --- | --- |
| P0 | 普通统考逐名初试成绩 | 直接计算真实 P10，去掉当前最大的标签代理误差 | 记录样本排除规则；与代理标签做偏差分解；滚动回测同时报告精确标签子集 |
| P0 | 报名时可见的普通统考计划名额 | 总计划、推免、专项与普通统考名额分开，捕捉真实供给变化 | 只采报名日前公告；对缩扩招做分段效应和缺失指示；禁止使用最终录取人数作为同年输入 |
| P0 | 初试科目级可比特征 | 同为总分 400，数三/自命题数学、英一/英二和专业课难度并不可比 | 收集各科分布或可核验难度代理；只保留跨年口径稳定的信号 |
| P1 | 数据证据质量与测量误差模型 | 官方、二次来源、第三方和代理标签可靠性不同 | 把来源等级转成显式观测误差，而不只是固定样本权重；检查高/低证据子组校准 |
| P1 | 历史事件相似案例库 | 换考纲、参考书、缩扩招的影响方向取决于相似事件后的真实市场反应 | 为事件编码公布日期、幅度、考试迁移成本；使用结构时序/干预候选并严格做事前预测 |
| P1 | 竞校迁移网络 | 考生不是独立选择学校，某校换科目会把需求推向可替代院校 | 以地域、层次、考试科目和分数带构图；只用滞后热度；与无网络基线比较 |
| P1 | 滚动分组共形校准 | 让 80/90/95% 上界的长期覆盖更接近标称值 | 仅用历史样本外残差；按数据质量/院校层级分组；同时约束覆盖率与区间宽度 |
| P2 | 样本外动态 stacking | 不同学校可能由不同模型占优，但固定全局权重会掩盖差异 | 权重只能由更早年份样本外预测学习；只有持续优于单一基线才上线 |
| P2 | 分层/分组预测协调 | 学校、地区、院校层次和全国热度应保持统计一致 | 在不泄漏的预测层级上协调；验证总体与子组误差是否同步改善 |

## 建议新增的数据字段

- `candidate_initial_score`、`candidate_type`、`special_plan`、`full_time`、`adjustment_status`：计算精确普通统考 P10。
- `published_regular_quota`、`recommended_exemption_quota`、`quota_publish_date`：得到报名日前真实供给。
- `subject_code_*`、`syllabus_change_type`、`reference_book_change`、`change_publish_date`：描述考试迁移成本。
- `event_magnitude`、`event_direction_uncertain`、`event_analogue_group`：让事件权重可学习、可复核。
- `source_grade`、`source_snapshot_date`、`extraction_method`、`reviewer_status`：显式建模证据质量。
- 权威且跨年口径一致时才加入 `applicant_count`、`view_index` 或搜索热度；不以平台私有口径拼接出虚假的长序列。

## 统一评估门槛

每个候选改动必须使用 expanding-window rolling origin；调参和模型选择不得看到待测年份。至少报告：

1. 加权 MAE 与中位绝对误差；
2. 低估三倍惩罚损失与低估率；
3. P80/P90/P95 的 pinball loss、实际覆盖率和平均区间宽度；
4. 985/211、A/B 区、证据等级、历史长短和事件学校子组校准；
5. 相对上一年锚点、稳健锚点和复杂候选的逐年差值，而不只报告三年合并平均；
6. 新模型只有在关键年份没有灾难性退化、且保守损失或校准明确改善时才进入生产。

## 方法依据

- Romano、Patterson 与 Candès 的 [Conformalized Quantile Regression](https://papers.neurips.cc/paper_files/paper/2019/file/5103c3584b063c431bd1268e9b5e76fb-Paper.pdf) 为分位数预测提供有限样本的覆盖校准框架；本项目必须改造成严格的时间滚动版本，不能随机打乱年份。
- Yao 等人的 [Stacking Bayesian Predictive Distributions](https://arxiv.org/abs/1704.02030) 支持按样本外预测表现组合完整分布；本项目只会在历史外推结果足够时学习局部权重。
- Brodersen 等人的 [Bayesian Structural Time Series for Causal Impact](https://kaybrodersen.github.io/publications/Brodersen_2015_AOAS.pdf) 提供干预与反事实时序思路；在本项目中，事件案例少且选择机制复杂，因此先作为候选情景模型，而不轻率宣称因果效应。
- Wickramasuriya、Athanasopoulos 与 Hyndman 的 [MinT forecast reconciliation](https://otext.robjhyndman.com/publications/mint/) 说明如何协调分组预测；是否适合院校—地区—层次结构仍需样本外验证。
