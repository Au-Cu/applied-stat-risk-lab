# 方法论文

本目录保存模型方法论文的可复现源文件。第一、二版保留用于对照；当前 V5 按普通统计研究论文重写，并与精确逐名标签、分层分布实验、字段级来源审计、严格嵌套校准和网页口径同步。

## 文件

- methods_paper.html：第一版方法论文，保留用于对照。
- modeling_paper_v2.html：当前 V5 正文源文件（保留旧文件名以避免破坏既有渲染入口）。
- public_source_bibliography.html：940 个去重公共来源的伴随目录源文件。
- scripts/build_paper_analysis.py：从处理后数据和模型产物重新计算指标、生成全部统计图、复现清单与附录表。
- scripts/build_v5_distribution_figures.py：从校年级聚合实验结果生成逐人证据分流、三层方差、抽样误差、可靠性与选择梯度图。
- scripts/render_pdf.cjs：第一版 A4 PDF 渲染器。
- scripts/render_paper_v2.cjs：第二版 A4 PDF 渲染器，并自动注入 81 所院校附录表。
- scripts/render_paper_v3.cjs：第三版 A4 PDF 渲染器，包含 MathJax 完整性审计。

## 生成第一版

在仓库根目录配置 NODE_PATH 后运行 paper/scripts/render_pdf.cjs。

输出文件：

output/pdf/应用统计择校门槛概率预测_方法论文_初稿.pdf

## 生成第二版

先安装 requirements.txt 中的 Python 依赖，再运行：

.\.venv\Scripts\python.exe paper\scripts\build_paper_analysis.py --repo-root . --output-dir paper\assets\v2

该程序会从与公开网页相同的处理后数据中重新计算指标，生成 12 组 SVG/PNG 图、paper_metrics.json 与 forecast_appendix.csv。

随后配置 NODE_PATH 并运行 paper/scripts/render_paper_v2.cjs。输出文件：

output/pdf/应用统计择校门槛概率预测_数模论文_V2.pdf

MathJax 由其官方 CDN 在渲染时加载；PDF 中的公式会固化为可缩放排版结果。

第二版不使用 AI 生成图片。正文图表全部由统一 Python 分析程序读取真实数据和模型结果后生成；该程序是论文分析层的可复用入口，而不是为单张图片临时编写的绘图脚本。

## 生成第三版

```powershell
.\.venv\Scripts\python.exe paper\scripts\build_paper_analysis.py --repo-root . --output-dir paper\assets\v3
node paper\scripts\render_paper_v3.cjs
```

该程序会生成 19 组 SVG/PNG 图、指标快照、数据 SHA256 清单和 81 校五分风险带附录。新增图形用于解释校准候选的覆盖—锐度权衡、条件覆盖失配，以及极宽安全上界为何不宜精算。最终 PDF 位于：

```text
output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V3.pdf
```

第三版不使用 AI 生成图片。所有图表均由同一分析程序从冻结数据、滚动回测和预测产物生成；稳健 P90* 只称为暂定安全上界，不宣称已有充分的 90% 频率保证。2027 基线另由 `model/forecast_freeze.py` 生成不可覆写的哈希清单，用于真正的下一年度前瞻检验。

## 生成 V5

先生成通用分析图与逐人分布增强图，再渲染正文和公共来源目录：

```powershell
.\.venv\Scripts\python.exe paper\scripts\build_paper_analysis.py --repo-root . --output-dir paper\assets\v3
.\.venv\Scripts\python.exe paper\scripts\build_v5_distribution_figures.py
node paper\scripts\render_paper_v3.cjs
node paper\scripts\render_source_bibliography.cjs
.\.venv\Scripts\python.exe model\verify_frozen_forecast_outputs.py
```

公开输出：

```text
output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V5_逐人分布与来源审计增强.pdf
output/pdf/应用统计硕士择校研究_逐字段公共数据来源目录_V5.pdf
```

V5 的逐人名单原图与考生级 OCR 表不进入 Git；图形脚本只读取校年级聚合、去标识审计摘要与实验指标。三个统计对象在全文保持区分：校年内拟录取分布 `F_adm`、其低位分位数 `T=Q10(F_adm)`，以及未来门槛的预测分布 `G`。回溯实验不改写已冻结的 2027 数值。
