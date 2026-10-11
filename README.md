# 应用统计择校风险实验室

面向全日制 `025200 应用统计` 的择校风险研究原型。当前覆盖传统 985/211 院校，预测普通统考拟录取初试成绩 P10 的概率分布，并把考纲变化、参考书调整、学制变化和考生反向选择纳入三情景分析。

- 公开网站：<https://applied-stat-choice-lab-2027.aucu050410.chatgpt.site>
- GitHub Pages 镜像：<https://au-cu.github.io/applied-stat-risk-lab/>
- 当前版本：`v0.4.0`（V6 统计推断与现代统计建模）；保留 `v0.2.0`、`v0.3.0` 原 Release。

## 研究范围与功能

- 81 所学校的 2027 原始预测分布、P50 与学校特异的稳健 P80*/P90*/P95* 安全上界；
- 用户估分驱动的冲、观察、稳、保标签；
- 2024—2026 expanding-window 滚动回测；
- 贝叶斯正则化分层近似与梯度提升分位数辅助模型；新研究另比较 REML 共享方差的经验贝叶斯随机截距及局部水平过程；
- 官方事件三情景、市场反转和竞校溢出解释；
- 原始工作簿审计、24 条人工复核队列、字段字典和标准录入模板；
- 可交互网页和可运行的数据处理、训练、预测代码。
- 可点击的七步图形流程（证据层 → 推断层 → 决策层）、专业技术说明和精度优化路线图。
- “模型原理”阅读页：把 Q10 目标、相对国家线边际分、分层候选模型、事件混合分布和覆盖概率逐式对应到国家线共同波动图、单校加法分解桥图与时间外回测图；图形均直接读取公开模型快照，不使用装饰性插图。
- 五派系标签与筛选：纯贾、纯茆、贾茆、茆Pro、贾茆Pro（另保留“待核实”避免强行归类）。
- 81 所学校的交互坐标图、代表性办公集聚区、候选地铁/公交线路与高德实时公交路线入口。
- 报名时可见名额的严格时间截断数据契约、官方来源链接、质量审计和院校详情展示；当前严格名额覆盖 5/226 条滚动回测行，候选特征暂不改变生产预测。
- 字段级来源台账与链接健康审计：3,690 个非空核心字段值中 3,685 个附有公开 URL；逐名名单原图和考生级分数留在 Git 忽略的私有层。
- 14,317 条可读初试总分按统计角色完整利用：9,073 条已录取、2,444 条明确未录取、2,800 条结果未知；逐人原表始终留在 Git 忽略的私有层。
- 77 个校年、2,312 条普通统考全日制拟录取分数通过人口口径、图例与汇总核对，形成精确 Q10；另有 5,199 条已录取软证据和 1,562 条诊断记录，不因未晋级为精确标签而被丢弃。
- V5 模型原理页新增三类有决策含义的图形：成绩证据分流、`F_adm → T=Q10(F_adm) → G` 三个统计对象、模型候选晋级门禁；不使用装饰性插图。

## V6：统计推断与现代统计方法比较

本版新增非参数顺序统计区间、分位定义敏感性、嵌套 REML 方差模型、方法特异观测误差、经验贝叶斯状态预测、局部水平随机过程、岭回归、小型神经网络，以及相对分位曲线的主成分、因子、聚类分析。统计学取向体现为目标、假设、估计、依赖结构与时间外验证明确，不排除机器学习，也不为模型名称强行增加复杂度。

同一批 54 个精确校年上，观测误差随机截距 MAE 为 15.05 分，略高于已有增强模型的 14.90；但规范化 WIS 从 10.81 降至 8.80，平均 P90−P50 从 31.21 缩至 23.22 分，总体 P90 覆盖从 85.2% 增至 92.6%。2026 年覆盖仍仅 82.4%，故不能称为可靠 90% 保证。该候选没有通过全部升级护栏，不回写 2027 冻结数值。

岭回归和 4 隐节点网络的 MAE 为 22.26、23.68 分，未采用其中心。两主成分解释 94.8% 的观察形状变异；聚类描述较窄、中等、较宽的分布，单因子揭示中上分位共同展开与低尾独特差异，但小幅形状预测增益不足以确认优势。预测效果较弱的候选仍保留用于描述和诊断，不从论文中隐去。

年份条件化 REML 方差占比为院校间 26.9%、校年状态 19.9%、校年内个体 53.2%，同校同年相关 0.468。它与院校等权描述性分解不同，不代表全部全国报名者。完整、正确名单的已实现 Q10 没有条件随机抽样误差；总体 Bootstrap/顺序统计需要假想选择总体与独立同分布假设，下一届预测又是另一层不确定性。

原三年份 Bootstrap 区间不用于宣称显著优越。年份均值的 90% t 区间为 [-4.64, 1.62]，符号翻转双侧 p=0.50，两者亦有独立性、正态或对称假设。最新论文见 [V6 PDF](output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V6_统计推断与现代统计建模.pdf)；技术细节与已知限制见 [V6 统计模型说明](docs/statistical_model_v6.md)。个人考生分数随机性继续排除。

## 既有研究结论（冻结基线与 V5）

原始工作簿的 295 个生产训练目标由最低分、中位数和录取人数构造。V5 对 452 张名单图像做隐私最小化 OCR、图例识别和校年汇总复核，最终确认 77 个样本量不少于 10 的精确校年，覆盖 44 所学校、2,312 名普通统考全日制拟录取者。冻结 v0.2 基线在 2024—2026 滚动回测中的主流程加权 MAE 为 17.66 分；将精确标签替换进历史状态并重算滞后特征后，54 个精确回测校年的 P50 MAE 从 15.83 降至 14.90 分，年份等权 MAE 差为 -1.51 分，90% 年份分块 bootstrap 区间为 [-2.68, -0.33]。由于独立外层日历年仍只有 3 个，该结果只作为冻结后回溯证据，不覆盖 2027 前瞻数值。

73 个精确—代理配对首次同时校准两类代理：50 个顺序统计插值代理平均低估 2.85 分、MAE 3.14 分；23 个仅最低分代理平均低估和 MAE 均为 6.05 分。经验 Q10 的 bootstrap 标准差中位数为 3.09 分、90 分位数为 6.03 分，说明“名单精确”仍不等于潜在总体分位数无抽样误差。

逐人样本把“一个全国分布”拆成三个可比较层次。总方差中 46.1% 来自校年内考生差异，10.9% 来自同校跨年波动，43.0% 来自学校间差异；同校上一期分布形状把分位形状 MAE 从 6.05 降至 5.73。把软证据再混入只额外改善约 0.001 分，落入预先设定的 0.05 分简约等价带，因此选择更简单的 `lag_exact`，避免为了微小样本内优势增加复杂度。

明确录取与未录取的逐人分数也被用于复试选择诊断：200 个双结果队列、10,246 名考生的校年 AUC 中位数为 0.876，录取组与未录取组中位数差为 17 分；但将这些特征严格滞后后，在仅有的 2026 年 14 个重叠校年上使 MAE 从 16.59 恶化到 21.84 分，故不进入预测。状态未知的分数只描述复试池分布，不被转换成录取标签。

概率部分不再把所有学校统一加一个约 26 分的安全垫。V3 使用“跨历史预测年份最不利标准化残差 + 学校特异误差尺度”形成暂定安全上界：在只允许使用更早残差的 2025—2026 严格嵌套检验中，原始 P90 覆盖率为 79.7%、WIS 为 9.98；稳健 P90* 覆盖率为 92.1%、WIS 为 9.70，但平均 P90*-P50 宽度由 17.68 增至 29.35 分。由于严格校准只有两个外层年份且标签仍是代理，P90* 只解释为安全上界，不宣称已有精确 90% 频率保证。

2027 预测增加了不依赖结果的“极宽上界”护栏：若稳健 P90*-P50 超过当期院校横截面的 Tukey 上围栏（本版为 44.25 分），网页标为“证据不足：不宜精算”，不把该上界解释为学校真实难度更高，也不通过裁剪制造虚假确定性。本版唯一触发学校为合肥工业大学。模型、输入、输出和核心脚本已写入 `data/audit/forecast_freeze_2027.json`；2027 结果揭示后只评分，不用该结果回调本基线。

下一轮提升的最高优先级不是继续堆模型，而是扩大精确名单的独立年份覆盖、补足报名时已经可见的普通统考名额，并用方法特异的观测误差模型传播代理与 Q10 抽样不确定性。完整优先级、验证门槛与文献依据见[精度优化路线图](docs/accuracy_roadmap.md)。

## 目录

```text
app/                    交互网页
app/data/forecast.json  网页使用的预测数据
data/source/            原始工作簿副本（只读输入）
data/processed/         标准化数据、事件、回测和预测
data/audit/             数据与模型审计摘要
docs/                   模型公式、假设和数据字典
model/                  数据准备、训练、回测和预测代码
scripts/                审计工作簿与网站构建辅助脚本
output/                 选定公开论文与校年级聚合实验结果
outputs/                本地生成的审计工作簿和预览（不提交；工作簿随 Release 发布）
```

## Python 环境

需要 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

重新提取和审核原始工作簿：

```powershell
.\.venv\Scripts\python.exe model\prepare_data.py
```

如需从头更新地图与通勤参考数据，应先执行一次性地理编码和通勤表构建；公开 Nominatim 服务须遵守其限速与缓存政策：

```powershell
.\.venv\Scripts\python.exe scripts\geocode_school_locations.py
.\.venv\Scripts\python.exe scripts\build_commute_reference.py
```

重新训练、逐年回测并生成 2027 预测：

```powershell
.\.venv\Scripts\python.exe model\train_model.py
```

建立或核验 2027 前瞻预测冻结清单：

```powershell
.\.venv\Scripts\python.exe model\forecast_freeze.py --create
.\.venv\Scripts\python.exe model\verify_frozen_forecast_outputs.py
```

`--create` 只用于新版本首次冻结，已有清单时会拒绝覆盖。

验证报名时名额和本地私有逐人成绩分层数据，并复现实验：

```powershell
.\.venv\Scripts\python.exe model\validate_quota_events.py
.\.venv\Scripts\python.exe model\validate_candidate_scores.py
.\.venv\Scripts\python.exe model\experiment_quota_features.py
.\.venv\Scripts\python.exe model\train_model.py --output-dir output\experiments\v5_exact_labels_20261009 --audit-dir output\experiments\v5_exact_labels_20261009 --site-json output\experiments\v5_exact_labels_20261009\forecast.json
.\.venv\Scripts\python.exe model\experiment_exact_labels.py --enhanced-backtest output\experiments\v5_exact_labels_20261009\rolling_backtest.csv --output-dir output\experiments\v5_exact_labels_20261009\exact_evaluation
.\.venv\Scripts\python.exe model\experiment_hierarchical_distribution.py
.\.venv\Scripts\python.exe model\experiment_retest_selection.py
```

后两项分别复现逐人分布/三层方差/形状门禁，以及录取—未录取选择梯度与严格滞后候选实验。它们只读取本地私有逐人表，公开输出均为校年级聚合或审计统计。

随机种子固定为 `20261003`。训练会更新：

- `data/processed/rolling_backtest.csv`
- `data/processed/forecast_2027.csv`
- `data/processed/forecast_2027.json`
- `data/audit/model_run.json`
- `app/data/forecast.json`

## 网页

需要 Node.js 22.13+。

```powershell
npm ci
npm run dev
```

当前 Windows ARM64 环境中的 `workerd` 不提供对应二进制时，可直接用 Next.js 本地预览：

```powershell
node node_modules/next/dist/bin/next dev -H 127.0.0.1
```

生产静态构建：

```powershell
npm run build:static
```

输出位于 `out/`。

## 审计工作簿

```powershell
node scripts\build_audit_workbook.mjs
powershell -ExecutionPolicy Bypass -File scripts\repair_audit_workbook_excel.ps1
```

第二条命令仅在 Excel 无法正常打开生成文件时执行兼容性修复。工作簿包含审计总览、预测结果、人工复核队列、年度数据模板、事件模板、回测明细、字段字典、来源台账和完整院校年度数据。

## 方法文档

- [模型公式与假设](docs/model_specification.md)
- [数据结构与来源口径](docs/data_dictionary.md)
- [数据来源、审计链与逐名成绩最小化协议](docs/provenance_protocol.md)
- [精度优化路线图](docs/accuracy_roadmap.md)
- [报名时可见名额数据契约](docs/quota_data_contract.md)
- [V5 论文 PDF](output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V5_逐人分布与来源审计增强.pdf)
- [逐字段公共数据来源目录 PDF](output/pdf/应用统计硕士择校研究_逐字段公共数据来源目录_V5.pdf)

## 发布规则

采用“先封存、再修改”：开始任何新一轮变更前，当前 `main` 必须已有对应 GitHub Release；完成并验证后发布新版本，作为下一轮修改的基线。V5 已封存为 `v0.3.0`；本次 V6 新增为 `v0.4.0`，原 `v0.2.0`、`v0.3.0` 的标签、Release 与附件均不覆盖。

## 边界

这是学校间风险比较工具，不是个人最终录取概率保证。单科线、估分误差、复试表现、排名、临时政策和未发现事件仍可能改变结果。报名截止前应回到目标学校研究生院或学院官网人工复核招生目录、考试科目、名额和专项计划口径。

地图采用无行政区界线的坐标网格，仅用于比较相对位置，不是导航底图；学校坐标应以校方地址为准。办公区是代表性就业集聚区而非就业去向排名，静态地铁/公交文字为待人工复核的候选方案，实际出行请点击高德入口按当时路况和运营信息重新规划。
