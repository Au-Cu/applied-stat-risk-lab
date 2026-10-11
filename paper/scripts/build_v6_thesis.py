"""Mechanically assemble V6 from frozen V5 text and fitted statistics.

Never edits V5. The new analytical sections are authored in an HTML template;
all fitted values/tables come from the common experiment summary.
"""
from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parents[2]
EXP=ROOT/'output/experiments/v6_statistical_inference_20261011'
TITLE='报名前信息集下应用统计硕士拟录取初试低位分数的概率预测'


def fmt(v,d=2):return f'{v:.{d}f}'


def main():
    source=(ROOT/'paper/modeling_paper_v2.html').read_text(encoding='utf-8')
    template=(ROOT/'paper/v6_statistics_sections.html').read_text(encoding='utf-8')
    s=json.loads((EXP/'summary.json').read_text(encoding='utf-8'))
    q=s['quantile_diagnostics'];r=s['nested_reml_calendar_adjusted'];shape=s['multivariate_shape_pca'];infer=s['paired_small_year_inference'];reg=s['regression_challengers']['metrics']
    values={'DEFINITION_MEDIAN':fmt(q['definition_range_median']), 'DEFINITION_MAX':fmt(q['definition_range_max']),
        'RANK0510':fmt(q['rank_spearman_q05_q10'],3),'RANK1020':fmt(q['rank_spearman_q10_q20'],3),
        'SUPPORT_COUNT':str(q['support_bound_count']),'ICC_SCHOOL':fmt(r['same_school_different_year_icc'],3),
        'ICC_COHORT':fmt(r['same_school_year_icc'],3),'RIDGE_MAE':fmt(reg['ridge']['mae']),
        'NEURAL_MAE':fmt(reg['neural_4']['mae']),'PC1':fmt(shape['explained_variance_ratio'][0]*100,1),
        'PC2':fmt(shape['explained_variance_ratio'][1]*100,1),'PC12':fmt(sum(shape['explained_variance_ratio'][:2])*100,1),
        'PC1_IQR':fmt(shape['pc1_iqr_spearman'],3),'PC2_SKEW':fmt(shape['pc2_bowley_spearman'],3),
        'T_LOW':fmt(infer['t90_interval_df2'][0]),'T_HIGH':fmt(infer['t90_interval_df2'][1]),
        'SIGN_P':fmt(infer['exact_year_signflip_two_sided_p']),
        'CLUSTER_COUNTS':'、'.join(str(g['groups']) for g in shape['descriptive_cluster_profiles']),
        'CLUSTER_SPANS':'、'.join(fmt(g['span_q95_q05'],1) for g in shape['descriptive_cluster_profiles'])}
    values['VARIANCE_ROWS']=''.join(f"<tr><td>{name}</td><td>{fmt(r['variances'][k],1)}</td><td>[{fmt(r['profile95_intervals'][k]['lower'],1)}, {fmt(r['profile95_intervals'][k]['upper'],1)}]</td><td>{fmt(r['variance_shares'][k]*100,1)}%</td></tr>" for k,name in (('between_school','院校间'),('school_year','校年状态'),('within_school_year','校年内个体')))
    values['MODEL_ROWS']=''.join(f"<tr><td>{name}</td><td>{fmt(m['mae'])}</td><td>{fmt(m['wis'])}</td><td>{fmt(m['q90_coverage']*100,1)}%</td><td>{fmt(m['q90_mean_width'])}</td></tr>" for key,name in (('frozen_baseline','冻结基线'),('v5_exact_enhanced','精确标签增强'),('random_intercept','观测误差随机截距'),('local_level','局部水平'),('local_level_equal_precision','等精度局部水平')) for m in [s['rolling_metrics'][key]])
    names={'pooled':'全国池化','lag_full':'同校未压缩滞后','lag_pca1':'一主成分','lag_pca2':'二主成分','lag_factor1':'单因子','lag_cluster3':'三类聚类'}
    values['SHAPE_ROWS']=''.join(f"<tr><td>{names[k]}</td><td>{fmt(shape['rolling_shape_mae'][k])}</td><td>{'位置展开的基准' if k=='pooled' else '过去形状的收缩或压缩'}</td></tr>" for k in names)
    for k,v in values.items():template=template.replace('@@'+k+'@@',v)
    if '@@' in template:raise ValueError('Unresolved fitted-value placeholder')
    parts={}
    matches=list(re.finditer(r'<!-- (ESTIMANDS|METHODS|RESULTS|ROBUSTNESS) -->',template))
    for i,m in enumerate(matches):parts[m.group(1)]=template[m.end():matches[i+1].start() if i+1<len(matches) else len(template)].strip()
    for key,chapter in (('ESTIMANDS','四、门槛预测方法'),('METHODS','五、事件冲击与预测不确定性'),('RESULTS','八、稳健性分析'),('ROBUSTNESS','九、讨论：方法价值、局限与推广')):
        marker='  <section>\n    <h2>'+chapter+'</h2>'
        if source.count(marker)!=1:raise ValueError('Chapter insertion ambiguity: '+chapter)
        source=source.replace(marker,parts[key]+'\n\n'+marker,1)
    abstract=r'''<div class="abstract">
      <h2>摘　要</h2>
      <p>研究生招生在成绩揭示前要求完成单志愿选择。本文以传统 985/211 院校全日制应用统计专业为例，研究报名前信息集下普通统考拟录取者初试总分第 10 百分位的概率预测。该量是群体低位风险指标，不是制度分数线或个人录取概率。区分已实现有限总体、假想选择总体与未来队列预测，形成来源审计、分层测量、状态推断与时间外验证框架。</p>
      <p>研究覆盖 81 校、2022-2026 年 405 个校年。14,317 条可读成绩按用途保留，审计层确认 77 个精确校年、44 校和 2,312 名拟录取者；另保留软证据、未录取与状态未知记录。来源台账关联 3,685/3,690 个非空核心字段，伴随目录逐项列示 940 个公开来源，不以研究者工作簿替代原始公开文献。</p>
      <p>对逐人成绩建立年份固定效应和院校、校年嵌套随机效应模型。REML 方差占比分别为院校间 26.9%、校年状态 19.9%、校年内个体 53.2%，同校同年相关为 0.468。相对 Q10 分位曲线的前两个主成分解释 94.8% 的观察变异，聚类描述较窄、中等与较宽的分布形状；这些描述不等于全国总体推断或预测增益。总体低尾的非参数识别在小名单中受限。</p>
      <p>同一批 54 个精确时间外校年中，标签增强使中心 MAE 从 15.83 降至 14.90 分。新观测误差随机截距候选 MAE 为 15.05 分，但标准 WIS 为 8.80，低于增强模型 10.81；平均 P90−P50 从 31.21 缩至 23.22 分，总体覆盖由 85.2% 增至 92.6%，2026 年却仍只有 82.4%。局部水平、岭回归、小型神经网络均未改善中心误差；形状压缩仅有小幅增益。三个年份的 MAE 差 t 区间跨 0，不能宣布新年份稳定优越。</p>
      <p>研究据此保留经比较支持的简约结构，并将预测效果较弱的候选用于描述分布异质性和诊断跨年稳定性。代理误差、队列波动和未来状态不确定性尚有识别限制；精确名单覆盖、独立年份、官方计划名额及事件库仍是改进重点。2027 前瞻基线保持独立冻结，新增结果属于回溯性统计研究，不回写既有预测。</p>
      <p class="keywords"><strong>关键词：</strong>分位数预测；限制最大似然；观测误差；经验贝叶斯；随机过程；多元统计；机器学习；滚动验证</p>
    </div>'''
    source=re.sub(r'<div class="abstract">.*?</div>\s*<div class="version-note">',lambda m:abstract+'\n    <div class="version-note">',source,count=1,flags=re.S)
    source=re.sub(r'<div class="version-note">.*?</div>', '<div class="version-note">第六版研究稿 - 统计推断、分布结构与现代统计候选比较｜2027 基线冻结于 2026-10-08｜研究快照 2026-10-11｜不纳入考生估分随机性</div>',source,count=1,flags=re.S)
    # Correct finite-roster versus hypothetical-population language throughout.
    source=source.replace('逐人样本可改善 \\(F^{adm}_{s,t}\\) 及其 Q10 抽样误差估计','逐人样本可直接计算 \\(F^{adm}_{s,t}\\) 及其经验 Q10；额外的总体分位数推断须另加假设')
    source=source.replace('逐人数据显著改善校年分布与抽样误差估计','逐人数据显著改善已实现校年分布，并支持带假设的重复队列低尾波动估计')
    source=source.replace('为避免把 2,312 名考生误当成 2,312 个独立年份，本文以院校等权口径分解：','为避免把 2,312 名考生误当成 2,312 个独立年份，本文先按院校等权作描述性方差分解；以下分量是有限样本均值与残差的记号，不是本节已拟合随机效应的 REML 估计：')
    source=source.replace('精确标签增强在当前三年回溯样本上有一致的年份块改善','精确标签增强在当前测试集合上改善中心误差，但三年中一年的配对差为正，且小年份 t 区间跨 0')
    source=source.replace('校年内拟录取分布 (F^{adm}_{s,t})','校年内拟录取分布 \\(F^{adm}_{s,t}\\)')
    source=source.replace('其低位分位数 (T_{s,t})','其低位分位数 \\(T_{s,t}\\)')
    source=source.replace('未来门槛预测分布 (G_{s,t})','未来门槛预测分布 \\(G_{s,t}\\)')
    # Do not interpret an interpolated empirical quantile as a population parameter.
    source=source.replace('明确已录取样本的精确 Q10 及其抽样不确定性','明确已录取样本的经验 Q10 及假想重复队列不确定性')
    source=source.replace('校年分布与抽样误差','校年分布与重复队列低尾波动')
    source=source.replace('即使逐名名单完整，经验 Q10 仍有有限样本误差。对每个校年重复抽取拟录取分数并重算 Q10，bootstrap 标准差中位数为 3.09 分、90 分位数为 6.03 分、最大值为 10.18 分。因此“精确”表示名单口径与逐行总分可核，不表示潜在总体分位数无抽样不确定性。样本量较小的专业应自然获得更宽的测量区间。','给定正确完整的本届名单，经验 Q10 可直接计算，不另加随机抽样误差。若在假想选择总体下把本届分数作为独立同分布重复队列样本，Bootstrap 标准差中位数为 3.09 分、90 分位数为 6.03 分、最大值为 10.18 分。这些值描述带模型假设的低尾波动，不是 OCR 或名单覆盖误差，也不是下一年预测区间；统计对象的进一步区别见第 3.9 节。')
    source=source.replace('精确名单仍包含顺序统计量的有限样本误差。散点为 77 个精确校年的 Q10 bootstrap 标准差，虚线给出 \\(c/\\sqrt n\\) 参考尺度；该图用于确定测量不确定性，不把考生个体数误当成独立预测年份数。','在假想独立同分布选择总体下，散点为 77 个校年 Q10 的 Bootstrap 标准差，虚线给出 \\(c/\\sqrt n\\) 参考尺度。该图描述重复队列低尾的工作波动，不表示完整名单的已实现 Q10 含随机抽样误差，也不把个体数当成独立年份数。')
    source=source.replace('新增逐名样本已量化顺序统计插值的观测误差和经验 Q10 的抽样误差','新增逐名样本已量化代理与精确标签的差异，并在假想重复队列下计算低尾波动近似')
    source=source.replace('本研究研究边界','本研究边界')
    source=source.replace('F_{s,t}(x)','G_{s,t}(x)')
    source=source.replace('Z^{\\mathrm{complex}}_{s,t}\n        \\sim\n        0.65\\,Z^{\\mathrm{Bayes}}_{s,t}\n        +0.35\\,Z^{\\mathrm{GB}}_{s,t}.','\\mathcal L(Z^{\\mathrm{complex}}_{s,t})\n        =\n        0.65\\,\\mathcal L(Z^{\\mathrm{Bayes}}_{s,t})\n        +0.35\\,\\mathcal L(Z^{\\mathrm{GB}}_{s,t}).')
    source=source.replace('真正需要回答的是：在报名时点已有信息下，该校当年普通统考全日制录取门槛可能落在什么区间','真正需要回答的是：在报名时点已有信息下，该校当年普通统考全日制拟录取低位风险指标可能落在什么区间')
    # This is a thesis, not an artifact-submission report.
    source=source.replace('本轮','本研究').replace('论文与模型的主要可复查产物','主要研究记录及统计口径')
    source=source.replace('<h3>4.1 动态特征与市场行为</h3>','<h3>4.1 动态特征与市场行为</h3><p>预测关联不等于市场机制识别。上一年偏离与次年回落也可能由测量噪声的回归均值造成；在缺少历史报考人数和独立热度证据时，“冷热反转”只作为滞后预测假设，不解释为已识别的考生迁移因果效应。</p>')
    additions='''<p>[22] Patterson H D, Thompson R. Recovery of Inter-block Information When Block Sizes Are Unequal[J]. Biometrika, 1971, 58(3): 545-554. DOI: 10.1093/biomet/58.3.545.</p>
      <p>[23] Hyndman R J, Fan Y. Sample Quantiles in Statistical Packages[J]. The American Statistician, 1996, 50(4): 361-365. DOI: 10.1080/00031305.1996.10473566.</p>
      <p>[24] Durbin J, Koopman S J. Time Series Analysis by State Space Methods[M]. 2nd ed. Oxford: Oxford University Press, 2012. DOI: 10.1093/acprof:oso/9780199641178.001.0001.</p>
      <p>[25] Lu Z J. Estimating Instrument Performance: with Confidence Intervals and Confidence Bounds[R]. NIST Technical Note 2119, 2020. DOI: 10.6028/NIST.TN.2119. 第 5.3 节：总体分位数置信区间。</p>
      <p>[26] Jolliffe I T, Cadima J. Principal Component Analysis: a Review and Recent Developments[J]. Philosophical Transactions of the Royal Society A, 2016, 374: 20150202. DOI: 10.1098/rsta.2015.0202.</p>
      <p>[27] Rumelhart D E, Hinton G E, Williams R J. Learning Representations by Back-propagating Errors[J]. Nature, 1986, 323: 533-536. DOI: 10.1038/323533a0.</p>'''
    marker='    </div>\n    <p class="footnote no-indent">数据来源说明：'
    source=source.replace(marker,additions+'\n'+marker,1)
    # Update the conclusion and roadmap rather than appending contradictory text.
    marker='    <h2>十、结论</h2>'
    source=source.replace(marker,marker+'''<p>本文综合回归、贝叶斯部分池化、随机过程、非参数分位推断、多元统计与机器学习，统计学取向体现在目标与似然明确、误差来源分开、参数有估计依据和时间外验证，而不是算法类别的排除。年份条件化 REML 说明组内与组间均有实质异质性；主成分、因子与聚类使分布展开结构更清晰，即使预测增益不大，仍提供受限但有用的描述证据。</p>''',1)
    source=source.replace('下一阶段应优先补官方逐名原件、报名时计划名额和历史事件面板，并把方法特异代理偏差、Q10 抽样误差与未来状态波动纳入潜在真实门槛模型。','观测误差与随机效应候选已进行了插件 REML 试验：WIS 改善而 MAE 未超过精确增强模型，2026 年 P90 仍有欠覆盖。下一阶段应优先补官方逐名原件、报名时计划名额和历史事件面板，再传播超参数不确定性与公共年份—边际依赖。')
    conclusion='''<h2>十、结论</h2>
    <p>本文将报名前单志愿择校中的学校风险表达为普通统考全日制拟录取初试低位分数的概率预测，区分完整名单的已实现 Q10、假想选择总体分位数和下一届预测分布。研究以可审计公共材料及逐人成绩构建分层证据：明确使用精确、软证据、未录取和状态未知记录的不同统计角色，不以研究者工作簿替代公开一手材料，也不把低位风险指标解释为个人录取保证。</p>
    <p>在审计样本上，年份条件化 REML 的院校间、校年状态与校年内个体方差占比为 26.9%、19.9%、53.2%，说明组内与组间均须保留；PCA、因子和聚类进一步描述分布展开及低尾独特结构。精确标签增强在同一 54 个时间外校年上将中心 MAE 从 15.83 降至 14.90 分；观测误差随机截距 MAE 为 15.05，但 WIS 改善至 8.80、平均 P90−P50 缩至 23.22 分。总体覆盖较好而 2026 年仍欠覆盖，表明联合评价比仅比较 MAE 或覆盖率更有实际意义。</p>
    <p>岭回归、局部水平与小型网络未改善本次中心预测，因子和聚类的形状预测优势亦有限；这些负结果仍有描述和稳定性诊断价值，不构成对相应统计方法类别的否定。只有三个外层年份，误差差的年份 t 区间跨 0，故研究不能宣称新年份稳定显著优越。后续应优先补官方完整名单、独立年份、报名前统招名额和事件库，再评估超参数积分、误差相关性及更丰富的非线性结构。2027 前瞻基线独立冻结，新回溯候选不回写该数值，个人估分随机性仍不在本研究范围内。</p>'''
    source=re.sub(r'<h2>十、结论</h2>.*?(?=\s*</section>)',lambda m:conclusion,source,count=1,flags=re.S)
    source=source.replace('已确认方法差异；尚未用同一批数据重估生产权重','已确认方法差异；新候选只在各训练窗校准偏差与方差，不改生产权重')
    source=source.replace('用方法特异偏差、方差和 Q10 bootstrap 误差区分代理测量误差与状态波动','插件 REML 候选已完成；下一步检验稳健创新、超参数积分与误差相关性')
    source=source.replace('区分潜在真实门槛 \\(Y^*\\) 与代理观测 \\(\\widetilde Y\\)','已区分潜在总体分位数与代理观测；进一步扩展年份和条件覆盖')
    source=source.replace('PSIS-LOO、时间外加权区间分数','优先新原点 WIS 和条件覆盖；普通留一法不能代替时间外检验')
    source=source.replace('2026-10-09 新增的来源台账','2026-10-09 来源研究与 2026-10-11 统计候选均不回写前瞻数值；新增的来源台账')
    extra='''<h3>B.5 统计模型与公开聚合复现</h3><p>新统计分析由 <code>model/experiment_statistical_inference.py</code> 计算，聚合结果保存于 <code>output/experiments/v6_statistical_inference_20261011/</code>；图形和网页共用同一摘要。公开复现可使用 <code>--aggregate-only</code>，由既有精确校年的均值、标准差、人数及分位数重估 REML、状态和机器学习候选；该模式读取已经发布的顺序统计诊断，不能从聚合量重新审核 OCR 或任意新分位数。完整名单定义与原图审核仍需获授权的私有成绩层。固定随机种子为 20261011；Python 依赖见 <code>requirements.txt</code>，前端依赖见锁文件，源代码与 PDF 保存于独立 v0.4.0 Release。原 v0.2.0 与 v0.3.0 不覆盖。</p><p>新增图均由 <code>paper/scripts/build_v6_statistical_figures.py</code> 读取统计结果生成；模板由 <code>paper/scripts/build_v6_thesis.py</code> 注入拟合指标。代码测试覆盖分位区间概率、逐人/充分统计似然等价、时间特征隔离与 WIS 规范化。描述性全样本 PCA/因子/聚类不进入未来测试拟合，个人考分随机性仍明确排除。</p>'''
    source=source.replace('  </section>\n</main>',extra+'\n  </section>\n</main>',1)
    # Renumber all displayed equations in reading order, including old letter tags.
    number=0;mapping={}
    def tag(m):
        nonlocal number
        number+=1;mapping[m.group(1)]=number
        return '\\tag{'+str(number)+'}'
    source=re.sub(r'\\tag\{([^}]+)\}',tag,source)
    source=re.sub(r'式（(\d+)）',lambda m:'式（'+str(mapping.get(m.group(1),m.group(1)))+'）',source)
    headings=re.findall(r'<h2>([^<]+)</h2>',source)
    chapters=[h for h in headings if h not in ('摘　要','目　录')]
    index_path=ROOT/'paper/assets/v6/layout_index.json'
    page_index=json.loads(index_path.read_text(encoding='utf-8'))['chapters'] if index_path.exists() else {}
    toc='<ol class="toc-list">'+''.join(f'<li><span class="label">{h}</span><span class="dots"></span><span class="page" data-toc="{i}">{page_index.get(h, "")}</span></li>' for i,h in enumerate(chapters))+'</ol>'
    source=re.sub(r'<ol class="toc-list">.*?</ol>',lambda m:toc,source,count=1,flags=re.S)
    source=source.replace('</style>','.toc-summary { font-size:9pt; line-height:1.8; margin-top:12mm; } figure img { max-height:155mm; object-fit:contain; } table.formula-list { break-inside:avoid; page-break-inside:avoid; } .references { line-height:1.45; } .references p { margin:0.25em 0; }\n  </style>',1)
    source=source.replace(toc,toc+'<p class="toc-summary no-indent">研究逻辑：先界定有限名单与未来风险目标，继而说明公开证据与观测误差，再估计分层状态和分布形状，最后以真实时间顺序比较中心、锐度、覆盖和少数年份的不确定性。描述性统计不自动等于预测增益，预测上界也不等于个人录取保证。</p>',1)
    (ROOT/'paper/modeling_paper_v6.html').write_text(source,encoding='utf-8')
    print(json.dumps({'chapters':len(chapters),'equations':number,'version':'V6','generated_from':'V5 text + statistical templates + fitted summary'},ensure_ascii=False))


if __name__=='__main__':main()
