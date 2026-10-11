"""Assemble V6.1 from the preserved V6 thesis; no model or result is refitted.

Clarifies audited empirical labels, core versus ancillary statistical roles,
annual calibration, and display risk scales. Moves ancillary comparisons to
an appendix without deleting their methods, negative results or figures.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "paper/modeling_paper_v6.html"
TARGET = ROOT / "paper/modeling_paper_v6_1.html"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Ambiguous or absent refinement anchor: {old[:100]}")
    return source.replace(old, new, 1)


def main():
    source = SOURCE.read_text(encoding="utf-8")
    audit = json.loads((ROOT / "output/experiments/v6_1_interpretation_20261011/audit.json").read_text(encoding="utf-8"))
    # Preserve the entire technical definition, including machine names exact.
    source = replace_once(source, '<h3>3.3 数据范围、来源与统一口径</h3>', '''<h3>3.3 数据范围、来源与统一口径</h3>
    <p>本文统一称逐行对账通过者的标签为“审计通过经验 Q10”，代码沿用 <code>exact</code> 标记。其含义仅为：在当前已审计名单覆盖范围内，按既定经验分位定义直接计算，而非由最低分等汇总量估计。它不表示二级来源绝对无误、不保证已取得招生单位全部官方原件，也不把总体低尾或未来届次的不确定性消除。此前图中“精确”或 <code>exact</code> 的简称均按此定义理解。</p>''')
    for old, new in (
        ('精确标签增强', '经验标签增强'), ('精确—代理', '名单—代理'),
        ('精确－代理', '名单－代理'), ('精确−代理', '名单−代理'),
        ('精确 Q10', '审计通过经验 Q10'), ('精确Q10', '审计通过经验 Q10'),
        ('精确校年', '审计通过校年'), ('精确标签', '审计通过经验标签'),
        ('精确名单', '已审计名单'), ('精确层', '审计通过层'),
        ('全国精确池化', '全国已审计名单池化'), ('同校精确历史', '同校名单历史'),
        ('精确 Bootstrap', '名单 Bootstrap'), ('精确队列', '已审计队列'),
        ('精确历史', '已审计历史'), ('纯精确', '纯已审计名单'),
        ('精确增强模型', '经验标签增强模型'), ('精确配对', '名单—代理配对'),
        ('精确形状', '已审计形状'), ('真实 Q10', '审计通过经验 Q10'),
        ('最新精确', '最新已审计'), ('精确验证', '已审计验证'),
        ('已有精确', '已有已审计'), ('同校精确', '同校已审计'),
        ('本研究研究边界', '本研究边界')):
        source = source.replace(old, new)
    source = replace_once(source, '<h3>1.3 研究内容与主要贡献</h3>', '''<h3>1.3 研究内容与主要贡献</h3>
    <p>本文的核心统计问题是：如何在来源异质、代理观测、短时间面板和层级个体数据同时存在时，预测下一届拟录取分布的低尾分位数。方法围绕“Q10 测量—中心预测—未来分布—时间外验证”组织；组内与组间结构用于解释异质性，替代算法用于检验结构假设，而不以方法数量作为研究贡献。</p>
    <table class="small-table"><caption>研究主线与辅助分析的定位</caption><thead><tr><th>层次</th><th>研究任务</th><th>主要位置</th></tr></thead><tbody>
      <tr><td>核心预测</td><td>审计通过经验 Q10、代理观测误差、未来低尾预测和联合评分</td><td>3.3-3.9、4.9-4.10、5、7.6、7.11、8.7</td></tr>
      <tr><td>统计解释</td><td>REML 的组间/组内依赖、相对分位曲线的展开结构</td><td>3.8、4.8、4.12、7.10、7.13</td></tr>
      <tr><td>附加比较</td><td>局部水平、岭、网络、因子及聚类的替代假设与负结果</td><td>正文概述，完整补充见附录 C</td></tr>
    </tbody></table>''')
    source = source.replace('估分覆盖概率、情景及不确定性分解', '原始分布、保守风险刻度、情景及不确定性分解')
    source = source.replace('目标不可直接观察。学校公布材料', '目标并非总能直接观察。学校公布材料')
    source = replace_once(source, '缺失机制明显随历史补录进度变化，不能假定为完全随机缺失。', '可得性具有明显年度差异；仅凭这些差异不能确定缺失原因或识别 MAR/MNAR，也不能证明由历史补录造成。')
    source = source.replace('描述性缺失模型的样本内 AUC 为 0.898，仅用于诊断选择机制，不用于预测精度宣称。', '该图描述原代理字段可得性，不是新名单覆盖率。描述性缺失模型的样本内 AUC 为 0.898，仅表明在这批数据中可得性可预测，不证明缺失机制或因果关系。')
    # Keep core observation model; make the currently omitted covariance visible.
    covariance = r'''<p>更一般的观测方差应写为：</p>
    <div class="equation">\[ v^{obs,h}=v^{cohort}+v^{proxy,h}+2\operatorname{Cov}(\eta^{cohort},\eta^{proxy,h}). \]</div>
    <p>现实现把最后一项设为 0，这是工作近似而非经验检验结果。同一名单的“名单−代理”配对可识别部分方法差异，却不足以单独识别队列波动与代理误差的协方差。后续联合潜在测量模型需要独立复核、重复来源或更强可检验假设；不能只新增一个自由协方差参数就宣称解决识别。本次不凭现有三个测试年份追调该参数。</p>'''
    source = replace_once(source, '<h3>4.10 经验贝叶斯部分池化与局部水平随机过程</h3>', covariance + '\n<h3>4.10 经验贝叶斯部分池化与局部水平随机过程</h3>')
    # Move full ancillary regression specification and results, rather than delete.
    methods = re.search(r'<h3>4\.11 .*?(?=\s*<h3>4\.12 )', source, re.S)
    if methods is None:
        raise ValueError('Missing ancillary regression methods')
    appendix_methods = re.sub(r'<h3>4\.11 .*?</h3>', '<h3>C.1 回归与小型网络的完整规格</h3>', methods.group(), count=1)
    source = source[:methods.start()] + '''<h3>4.11 补充回归与非线性比较的定位</h3>
    <p>岭回归和 4 隐节点前馈网络用于比较跨校函数学习与学校部分池化。两者使用相同的七个严格历史特征及训练窗观测精度，只检验中心误差，不附加未经验证的概率上界。完整规格、内层调参与逐年负结果见附录 C.1-C.2；它们是核心结构的对照，不是最终预测链必须包含的额外算法。</p>\n''' + source[methods.end():]
    results = re.search(r'<h3>7\.12 .*?(?=\s*<h3>7\.13 )', source, re.S)
    if results is None:
        raise ValueError('Missing ancillary regression results')
    appendix_results = re.sub(r'<h3>7\.12 .*?</h3>', '<h3>C.2 中心候选的负结果与年度诊断</h3>', results.group(), count=1)
    source = source[:results.start()] + '''<h3>7.12 补充候选的结果概述</h3>
    <p>岭回归、小型网络的中心 MAE 为 22.26、23.68 分，局部水平为 16.64 分，均未改善经验标签增强的 14.90 分。网络在不同年份明显漂移，说明在给定特征和正则下增加非线性未自动解决短面板问题；这不否定相关统计方法类别。完整方法、逐年图与限定性的描述结论集中于附录 C，正文保留其作为结构对照的作用。</p>\n''' + source[results.end():]
    ancillary_shape = re.search(r'<figure class="wide"><img src="assets/v6/07_shape_typology_and_factor\.svg".*?</figure>\s*<p>单因子.*?</p>', source, re.S)
    if ancillary_shape is None:
        raise ValueError('Missing ancillary shape analysis')
    appendix_shape = '<h3>C.3 探索性聚类和因子分解的附加解释</h3>\n' + ancillary_shape.group()
    source = source[:ancillary_shape.start()] + '<p>聚类和因子分解的附加图及低尾独特方差解释见附录 C.3。它们不进入冻结风险排名，也不作为院校永久类别。</p>' + source[ancillary_shape.end():]
    # Annual calibration, with numerators, sample sizes and center bias.
    annual_rows = ''.join(f'<tr><td>{r["year"]}</td><td>{r["covered"]}/{r["n"]}</td><td>{r["coverage"]*100:.1f}%</td><td>{r["bias_actual_minus_prediction"]:+.2f}</td><td>{r["wis"]:.2f}</td></tr>' for r in audit['random_intercept_annual'])
    annual = '''<table class="small-table"><caption>随机截距候选的逐年覆盖与位置偏差</caption><thead><tr><th>原点</th><th>P90 覆盖数/校年数</th><th>覆盖率</th><th>实际−预测中心 / 分</th><th>标准 WIS</th></tr></thead><tbody>''' + annual_rows + '''</tbody></table>
    <p>总体 50/54 的 92.6% 由不同年份样本量加权而成；年份等权覆盖约为 90.8%，同样不能当作保证。2025 年中心偏高 13.89 分而覆盖全部 27 个校年，2026 年中心偏低 6.07 分并欠覆盖。仅扩大区间不能独自修复漂移，更不能据总体覆盖选择当前最漂亮的候选；必须结合 WIS、偏差和新原点验证。此处覆盖计数以校年为单位，不对同年相关校年套用独立二项标准误。</p>
    <figure class="wide"><img src="assets/v6_1/01_annual_coverage_and_bias.svg" alt="随机截距逐年覆盖计数和预测中心漂移" /><figcaption>左图保留覆盖分子和分母，右图检查同一年中心偏差；2025 年的高覆盖伴随位置偏高，2026 年方向反转。图来自既有时间外聚合记录的核算，没有重训或选择新参数。</figcaption></figure>'''
    source = replace_once(source, '<h3>7.12 补充候选的结果概述</h3>', annual + '\n<h3>7.12 补充候选的结果概述</h3>')
    # Distinguish conceptual G(x) from hybrid raw/safety interpolation R(x).
    source = source.replace('本节把离散分位点还原为近似分布函数，再根据个人估分计算覆盖概率', '本节区分原始预测分布与安全调整，并根据固定估分形成保守风险刻度')
    source = source.replace('<h3>6.1 由七个分位锚点构造门槛分布函数</h3>', '<h3>6.1 安全锚点的风险刻度与目标概率</h3>')
    source = replace_once(source, '前端保存 \\(q_{0.05},q_{0.10},q_{0.20},q_{0.50},q_{0.80},q_{0.90},q_{0.95}\\) 七个锚点。若 \\(x\\in[q_{\\alpha_j},q_{\\alpha_{j+1}}]\\)，则线性插值：', r'理论目标是第二节的覆盖概率 \(C(x)=G(x)\)。但前端锚点的下半部来自原始预测，上半部采用安全调整后的 \(q^*_{0.80},q^*_{0.90},q^*_{0.95}\)；记这些展示锚点为 \(a_{\alpha_j}\)。它们不构成已经联合校准的预测分位函数。对于 \(x\in[a_{\alpha_j},a_{\alpha_{j+1}}]\)，实际显示风险刻度：')
    # Only section six's estimated CDF notation changes; true G remains intact.
    six = re.search(r'<section>\s*<h2>六、.*?</section>', source, re.S)
    text = six.group().replace('\\widehat G_{s,t}(x)', '\\widehat R_{s,t}(x)')
    text = text.replace('x-q_{\\alpha_j}', 'x-a_{\\alpha_j}').replace('q_{\\alpha_{j+1}}-q_{\\alpha_j}', 'a_{\\alpha_{j+1}}-a_{\\alpha_j}')
    text = text.replace('因此由其得到的概率也应读作保守决策尺度，而不是精确录取概率。', r'因此 \(\widehat R\) 只是保守决策刻度，不宣称等于 \(G\)，也未证明它在每校都是概率下界。百分号表示政策刻度的位置，不是已验证的个人录取概率。')
    text = text.replace('这里“稳”的 90% 是用户给定的保守风险约束。', '这里“稳”的 90% 是用户规定的安全刻度阈值，不是已经验证达到的风险概率。')
    text = text.replace('assets/v3/09_ecnu_cdf.svg', 'assets/v6_1/02_safety_risk_scale.svg').replace('七个分位锚点插值得到的覆盖概率曲线', '安全锚点插值得到的风险刻度曲线')
    text = text.replace('400 分对应门槛覆盖概率约 91%。', '400 分对应保守风险刻度约 91%，不是经验验证的 91% 概率。')
    text = text.replace('不同估分的覆盖概率示例', '不同固定估分的保守风险刻度示例').replace('class="center">覆盖概率', 'class="center">风险刻度')
    guard = '''<h3>6.4 极宽上界、证据完备度与停止精算</h3>
    <p>原始 P90 和安全 P90* 应同时展示。发布时冻结的横截面 Tukey 上围栏为 44.25 分，用来诊断异常的 P90*−P50 宽度，不是经时间外验证的条件覆盖阈值或学校难度界线。合肥工业大学为唯一触发学校；其安全跨度约 71 分、原始跨度约 18.5 分。网页对该行统一显示“需复核/不宜精算”，不输出普通百分比或稳保结论，也不裁剪上界。</p>
    <p>宽区间既可能来自未来波动和数据不足，也可能来自校准保守或模型失配；不能由宽度本身识别原因。证据完备度描述材料的覆盖和质量，不是预测成功率。当前安全刻度仍服务于有边界的学校风险比较，不能替代来源复核、事件情景或官方招生规则。</p>'''
    text = text.replace('</section>', guard + '\n</section>', 1)
    source = source[:six.start()] + text + source[six.end():]
    source = source.replace('按预先声明的 Tukey 上围栏 44.25 分', '按发布时冻结的横截面 Tukey 上围栏 44.25 分')
    source = source.replace('被标为“证据不足：不宜精算”', '被标为“需复核：不宜精算”')
    source = source.replace('“证据不足：不宜精算”表示上界宽度越过预先声明的异常阈值', '“需复核：不宜精算”表示上界宽度越过发布时冻结的横截面异常阈值；该阈值不具条件覆盖保证')
    # Explicitly refuse to retroactively turn retrospective candidates into
    # prospective forecasts that have not actually been saved.
    forward = '''<h3>8.9 前瞻评分对象与信息时点</h3>
    <p>2027 基线已在 2026-10-08 冻结，信息截点为 2026-10-07 23:59；应在结果揭示后只评分，不回调该版本。V6 候选目前仅保存 2024-2026 的回溯输出，没有单独冻结的 2027 候选数值，故不能把它们追认为同一次盲测。若以后比较新候选，应在结果可见前另行冻结模型、输入快照、预测值和评分规则，并明确其较晚的信息时点，不与原基线混写。</p>
    <p>历史滚动重建也不等于真实历史信息快照：当前资料即使声明更早发布时间，其现存页面仍可能修订。940 个公开 URL 和高字段链接率说明可追溯入口，不代表每个源都已留存当时原件、核值或完整来源链。官方原件、时间版本和新独立年份仍是后续所需证据，当前不能宣称全源历史快照已完备。</p>'''
    robustness = re.search(r'<section>\s*<h3>8\.7 .*?</section>', source, re.S)
    if robustness is None:
        raise ValueError('Missing chapter eight supplemental section')
    source = source[:robustness.start()] + robustness.group().replace('</section>', forward + '\n</section>', 1) + source[robustness.end():]
    source = source.replace('未来应在 2027 及后续新原点上评分', '冻结基线应在 2027 结果揭示后评分；新候选须先独立冻结才可在后续新原点评分')
    source = source.replace('已有相对精确标签', '已有相对经验标签')
    source = source.replace('第六版研究稿 - 统计推断、分布结构与现代统计候选比较', '第六版修订研究稿（V6.1）- 测量口径、年度校准边界与研究主线')
    source = source.replace('源代码与 PDF 保存于独立 v0.4.0 Release。原 v0.2.0 与 v0.3.0 不覆盖。', 'V6 基础统计结果保存于 v0.4.0 Release，本修订稿与解释审计保存于 v0.4.1 Release。原 v0.2.0、v0.3.0 及 V6 均不覆盖。')
    source = source.replace('模板由 <code>paper/scripts/build_v6_thesis.py</code> 注入拟合指标。', '原稿模板由 <code>paper/scripts/build_v6_thesis.py</code> 注入拟合指标；本修订由 <code>paper/scripts/build_v6_refinement.py</code> 保留数值并重组。新增年度计数和风险刻度图来自 <code>model/audit_v6_interpretation.py</code> 的只读核算。')
    appendix = '<section class="page-break"><h2>附录 C　补充候选及探索性分布比较</h2><p>本附录列示替代模型的规格、逐年表现和探索性分布解释，目的在于检验核心结构的替代假设。未获得稳定时间外支持的候选不用于既有前瞻预测，也不因负结果而被省略。</p>\n' + appendix_methods + '\n' + appendix_results + '\n' + appendix_shape + '\n</section>\n'
    source = replace_once(source, '</main>', appendix + '</main>')
    source = source.replace('并根据固定估分形成保守风险刻度，并将风险偏好', '根据固定估分形成保守风险刻度，并将风险偏好')
    source = replace_once(source, '岭回归、局部水平与小型网络未改善本次中心预测，因子和聚类的形状预测优势亦有限；这些负结果仍有描述和稳定性诊断价值，不构成对相应统计方法类别的否定。只有三个外层年份，误差差的年份 t 区间跨 0，故研究不能宣称新年份稳定显著优越。后续应优先补官方完整名单、独立年份、报名前统招名额和事件库，再评估超参数积分、误差相关性及更丰富的非线性结构。2027 前瞻基线独立冻结，新回溯候选不回写该数值，个人估分随机性仍不在本研究范围内。', '局部水平、岭回归与小型网络没有改善中心误差，因子和聚类的形状优势亦有限；这些负结果只适用于本次设定。三个外层年份不足以确认稳定优越。后续应优先补官方名单、独立年份、报名前名额与事件库，再评估误差相关和超参数积分。2027 基线独立冻结，回溯候选不回写其数值，考生估分随机性仍不在研究范围。')
    # Equation numbers follow the new reading order, including the appendix.
    old_tags = re.findall(r'\\tag\{(\d+)\}', source)
    if len(old_tags) != len(set(old_tags)):
        raise ValueError('Duplicate original equation tags')
    mapping = {old: str(i + 1) for i, old in enumerate(old_tags)}
    source = re.sub(r'\\tag\{(\d+)\}', lambda m: '\\tag{' + mapping[m.group(1)] + '}', source)
    source = re.sub(r'式（(\d+)）', lambda m: '式（' + mapping[m.group(1)] + '）', source)
    headings = [h for h in re.findall(r'<h2>([^<]+)</h2>', source) if h not in ('摘　要', '目　录')]
    index = ROOT / 'paper/assets/v6_1/layout_index.json'
    pages = json.loads(index.read_text(encoding='utf-8'))['chapters'] if index.exists() else {}
    toc = '<ol class="toc-list">' + ''.join(f'<li><span class="label">{h}</span><span class="dots"></span><span class="page" data-toc="{i}">{pages.get(h, "")}</span></li>' for i, h in enumerate(headings)) + '</ol>'
    source = re.sub(r'<ol class="toc-list">.*?</ol>', lambda m: toc, source, count=1, flags=re.S)
    TARGET.write_text(source, encoding='utf-8')
    print(json.dumps({'source': str(TARGET), 'equations': len(old_tags), 'chapters': len(headings), 'refitted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
