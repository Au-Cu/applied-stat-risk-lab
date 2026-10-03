# 应用统计择校风险实验室

面向全日制 `025200 应用统计` 的择校风险研究原型。当前覆盖传统 985/211 院校，预测普通统考拟录取初试成绩 P10 的概率分布，并把考纲变化、参考书调整、学制变化和考生反向选择纳入三情景分析。

- 公开网站：<https://applied-stat-choice-lab-2027.aucu050410.chatgpt.site>
- 当前版本：`v0.2.0`

## 当前交付

- 81 所学校的 2027 P50、P80、P90、P95 预测；
- 用户估分驱动的冲、观察、稳、保标签；
- 2024—2026 expanding-window 滚动回测；
- 分层贝叶斯动态模型与梯度提升分位数辅助模型；
- 官方事件三情景、市场反转和竞校溢出解释；
- 原始工作簿审计、24 条人工复核队列、字段字典和标准录入模板；
- 可交互网页和可运行的数据处理、训练、预测代码。
- 可点击的七步图形流程（证据层 → 推断层 → 决策层）、专业技术说明和精度优化路线图。

## 重要结论

原始工作簿没有逐名考生成绩，295 个训练目标均为最低分、中位数和录取人数构造的透明 Q10 代理。v0.2 在严格逐年滚动回测中加入“历史国家线以上边际分中位数”锚点，用多年的稳健中心抵抗单年爆冷/爆热。它在可比样本上的加权 MAE 为 17.12 分，优于上一年锚点的 18.58 分；完整主流程 MAE 由 v0.1 的 18.90 分降至 17.67 分。复杂候选模型的 MAE 为 20.35 分，因此仍只负责不确定性形状、事件情景、变量解释以及缺少透明锚点时的回退。

下一轮提升的最高优先级不是继续堆模型，而是取得普通统考逐名成绩的精确 P10，以及报名时已经可见的普通统考名额。完整优先级、验证门槛与文献依据见[精度优化路线图](docs/accuracy_roadmap.md)。

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
outputs/                本地生成的审计工作簿和预览（不提交）
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

重新训练、逐年回测并生成 2027 预测：

```powershell
.\.venv\Scripts\python.exe model\train_model.py
```

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
node node_modules/next/dist/bin/next build
```

输出位于 `out/`。

## 审计工作簿

```powershell
node scripts\build_audit_workbook.mjs
```

工作簿包含审计总览、预测结果、人工复核队列、年度数据模板、事件模板、回测明细、字段字典、来源台账和完整院校年度数据。

## 方法文档

- [模型公式与假设](docs/model_specification.md)
- [数据结构与来源口径](docs/data_dictionary.md)
- [精度优化路线图](docs/accuracy_roadmap.md)

## 发布规则

采用“先封存、再修改”：开始任何新一轮变更前，当前 `main` 必须已有对应 GitHub Release；完成并验证后发布新版本，作为下一轮修改的基线。本轮修改前已有 `v0.1.0`，本轮完成后发布 `v0.2.0`。

## 边界

这是学校间风险比较工具，不是个人最终录取概率保证。单科线、估分误差、复试表现、排名、临时政策和未发现事件仍可能改变结果。报名截止前应回到目标学校研究生院或学院官网人工复核招生目录、考试科目、名额和专项计划口径。
