"""Build V6.2 from auditable data-version sensitivity results.

Scientific figures are views of the coverage audit, admitted quantile
summaries and fixed-model backtests. Existing frozen figures and papers stay
unchanged; their earlier sample is explicitly distinguished from the update.
"""
from pathlib import Path
import html
import json
import re
import hashlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/processed/evidence_refresh_20261024"
EXP = ROOT / "output/experiments/evidence_refresh_20261024"
ASSETS = ROOT / "paper/assets/v6_2"


def save_figure(fig, filename):
    fig.tight_layout()
    path = ASSETS / filename
    fig.savefig(path, bbox_inches="tight", metadata={"Date": "2026-10-24"})
    path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


def figures(summary, experiment, coverage, distributions):
    plt.rcParams.update({"font.family": "Microsoft YaHei", "axes.unicode_minus": False,
                         "font.size": 9, "svg.fonttype": "none"})
    names = list(dict.fromkeys(coverage.school))
    cmap = ListedColormap(["#eeeeee", "#d4b574", "#4b8d9a"])
    for part, chunk in enumerate((names[:42], names[42:]), 1):
        fig, axes = plt.subplots(1, 2, figsize=(8.4, 5.2))
        middle = (len(chunk)+1)//2
        for axis, schools in zip(axes, (chunk[:middle], chunk[middle:])):
            values = []
            for school in schools:
                group = coverage[coverage.school.eq(school)].sort_values("year")
                values.append([2 if row.exact_candidate_n else 1 if row.readable_initial_score_rows else 0 for row in group.itertuples()])
            axis.imshow(values, cmap=cmap, aspect="auto", vmin=0, vmax=2, interpolation="nearest")
            axis.set_xticks(range(5), range(2022, 2027), fontsize=8); axis.xaxis.tick_top()
            axis.set_yticks(range(len(schools)), schools, fontsize=8.5)
            axis.tick_params(length=0, pad=4)
            axis.set_xticks(np.arange(-.5, 5), minor=True); axis.set_yticks(np.arange(-.5, len(schools)), minor=True)
            axis.grid(which="minor", color="white", linewidth=1); axis.tick_params(which="minor", length=0)
            for spine in axis.spines.values(): spine.set_visible(False)
        fig.legend(handles=[Patch(color=cmap.colors[i], label=label) for i, label in enumerate(["未取得可用初试分数", "可读但录取口径待核", "审计通过Q10（n≥10）"])],
                   loc="lower center", ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(.5, -.025))
        save_figure(fig, f"01_coverage_part{part}.svg")
    # Separate the distribution of already admitted people from the predictive
    # distribution of a future Q10. Do not export individual empirical steps.
    tongji = distributions[distributions.school.eq("同济大学")].sort_values("year")
    fig, axis = plt.subplots(figsize=(8.7, 4.3))
    qs = [5, 10, 20, 25, 50, 75, 80, 90, 95]
    for (_, row), color in zip(tongji.iterrows(), ["#537d9b", "#af7043"]):
        axis.plot(qs, [row[f"score_q{q:02d}"] for q in qs], marker="o", markersize=4,
                  color=color, label=f"{int(row.year)} 年，普通统考拟录取 {int(row.candidate_n)} 人")
    axis.set(xlabel="名单内分位水平（%）", ylabel="已实现初试总分（分）", xticks=[5,10,25,50,75,90,95])
    axis.grid(axis="y", color="#dddddd"); axis.legend(frameon=False)
    save_figure(fig, "02_tongji_admitted_quantiles.svg")
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.1))
    common = experiment["same_key_test"]
    for axis, metric, label in zip(axes, ["mae", "wis"], ["中心 MAE（分）", "标准 WIS（分）"]):
        vals = [common["previous"][metric], common["refreshed"][metric]]
        axis.bar([0,1], vals, color=["#8d9ca7", "#4b8d9a"], width=.55)
        for i,v in enumerate(vals):axis.text(i,v+.08,f"{v:.2f}",ha="center")
        axis.set_xticks([0,1],["基础证据", "修订证据"]);axis.set_ylabel(label);axis.set_ylim(0,max(vals)*1.22)
        axis.spines[["top", "right"]].set_visible(False)
    save_figure(fig, "03_fixed_model_comparison.svg")
    annual = experiment["yearly"]
    fig, axis = plt.subplots(figsize=(8.7,4.2))
    for name,color,offset,label in [("previous_common","#8d9ca7",-.09,"基础证据"),("refreshed_common","#4b8d9a",.09,"修订证据")]:
        rows=[r for r in annual if r["vintage"]==name]
        xx=np.array([r['year'] for r in rows]); yy=np.array([r['q90_coverage']*100 for r in rows])
        axis.scatter(xx+offset,yy,color=color,label=label,s=55)
        for x,y,r in zip(xx,yy,rows):axis.annotate(f"{y:.0f}%",(x+offset,y),xytext=(0,9 if offset<0 else -17),textcoords="offset points",ha="center",fontsize=8)
    axis.axhline(90,color="#9b7250",linestyle="--",label="名义90%")
    axis.set(xticks=[2024,2025,2026],xticklabels=["2024", "2025", "2026"],ylim=(30,110),ylabel="同一测试键的 P90 实际覆盖（%）")
    axis.legend(frameon=False,loc="lower left");axis.grid(axis="y",color="#eeeeee")
    save_figure(fig,"04_yearly_coverage.svg")


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    experiment = json.loads((EXP / "summary.json").read_text(encoding="utf-8"))
    coverage = pd.read_csv(DATA / "coverage_by_school_year.csv")
    distributions = pd.read_csv(DATA / "exact_distribution_summary.csv")
    sources = pd.read_csv(DATA / "official_source_registry.csv").fillna("")
    figures(summary, experiment, coverage, distributions)
    old, new = experiment["same_key_test"]["previous"], experiment["same_key_test"]["refreshed"]
    expanded = experiment["expanded_audited_test"]
    reml = experiment["current_audited_distribution"]["nested_reml_calendar_adjusted"]
    vintage_names={"previous_common":"基础证据·同一测试键","refreshed_common":"修订证据·同一测试键","refreshed_expanded":"修订证据·扩展评价集"}
    year_rows = "".join(f'<tr><td>{r["year"]}</td><td>{vintage_names[r["vintage"]]}</td><td>{r["n"]}</td><td>{r["mae"]:.2f}</td><td>{r["wis"]:.2f}</td><td>{r["q90_coverage"]*100:.1f}%</td><td>{r["q90_mean_width"]:.2f}</td></tr>' for r in experiment["yearly"])
    source = (ROOT / "paper/modeling_paper_v6_1.html").read_text(encoding="utf-8")
    source = re.sub(r'<div class="version-note">.*?</div>', '<div class="version-note">V6.2 数据审计修订研究稿｜基础分析快照与修订证据分开报告｜原2027预测保留｜2026-10-24｜不纳入考生分数随机性</div>', source, count=1, flags=re.S)
    source = source.replace('<h3>3.3 数据范围、来源与统一口径</h3>', f'''<h3>3.3 数据范围、来源与统一口径</h3>
    <p>本研究采用两个可区分的数据快照。基础快照用于已完成的模型族比较，包含77个审计通过校年、44所学校和2,312名拟录取者；后续表格中未特别标注者均指该快照。修订快照对全部452张既存名单重新核对分数列与来源，覆盖{summary['exact_school_years_after']}个审计通过校年、{summary['exact_schools_after']}所学校及{summary['exact_candidate_rows_after']:,}名拟录取者。第8.8—8.10节在保持模型规格固定的条件下评估数据修订影响，并报告扩展评价集。两次分析不混报样本量，也不将新取得的资料冒充历史时点原件已经完整存档。</p>''',1)
    abstract = f'''<div class="abstract"><h2>摘　要</h2>
    <p>研究生招生要求考生在考试成绩揭示前完成单志愿选择。本文以985/211院校全日制应用统计硕士为研究对象，预测普通统考拟录取者初试总分的低位经验分位数。该指标描述已录取群体的初试低尾，不是制度分数线或个人录取概率。研究区分已实现名单、假想重复队列总体与未来未知结果，围绕观测口径、层级分布和时间外验证建立统计分析框架。</p>
    <p>数据面板覆盖81校2022—2026年的405个校年。修订中重新读取108个公开专业资料入口，核验452张本地原图的内容哈希，并逐图按列名审查初试分数。修订快照包含{summary['exact_school_years_after']}个审计通过校年、{summary['exact_schools_after']}所学校和{summary['exact_candidate_rows_after']:,}名拟录取者，其他资料按复试池、软证据或诊断用途保留。工作簿只作为整理索引，证据回到公开页面、学院公告和名单快照。</p>
    <p>基础快照采用年份固定效应和学校、校年嵌套随机效应解释组内与组间依赖，比较经验贝叶斯状态模型、局部水平、岭回归及小型网络。修订后的固定随机截距模型在同一测试键上的中心MAE由{old['mae']:.2f}变为{new['mae']:.2f}分，标准WIS由{old['wis']:.2f}变为{new['wis']:.2f}分；扩展评价集含{expanded['n']}个校年，另行报告而不直接与旧测试集作优劣比较。各原点的观测误差参数与状态方差只由更早年份估计，没有按本轮结果重新搜索超参数。</p>
    <p>官方原文核对揭示，同济大学2025、2026年全日制方向复试线分别为385、396分，原校级记录混入非全日制方向；2027年考试大纲调整公告亦须进入证据层，但事件分数冲击尚未识别。上述结果表明，输入语义与人群一致性是概率预测有效性的前提。三个外层年份、名单选择性和历史版本缺失仍限制推广；新增回溯结果不追认为盲测，原2027预测单独保留。</p>
    <p class="keywords"><strong>关键词：</strong>分位数预测；观测误差；层级模型；经验贝叶斯；数据审计；滚动验证</p></div>'''
    source = re.sub(r'<div class="abstract">.*?</div>\s*<div class="version-note">',lambda m:abstract+'\n<div class="version-note">',source,count=1,flags=re.S)
    new_section = rf'''<h3>8.8 原始名单再读取与数据版本敏感性</h3>
    <p>观测误差不仅来自数值识别，也可能来自被读取变量的语义不一致。例如同一张表同时出现初试、复试与综合成绩，正确识别“总成绩”的字符并不意味着得到了初试总分。因此修订采用“定位列名—识别分数—读取录取图例—排除特殊人群—核对人数及可得摘要”的顺序；不依据目标Q10或期望的模型误差倒推漏行值。多尺度一致识别、原始行序号以及可得的四门单科合计用于补读验证。已通过的基础标签不因追求更小MAE而改动。</p>
    <div class="equation">\[ Y^{{read}}_{{it}}=Q_{{0.10}}(A^{{target}}_{{it}})+e^{{numeric}}_{{it}}+e^{{scope}}_{{it}}. \]</div>
    <p>其中 \(e^{{numeric}}\) 表示漏行、错位和OCR造成的差异，\(e^{{scope}}\) 表示学习方式、招生类型或阶段混合造成的差异。该式为审计误差的概念分解，不意味着两项可独立估计或满足加性正态分布。改变表头定位、排除专项或恢复录取图例属于测量修订；不得把它们作为改善拟合的超参数。</p>
    <table class="small-table"><caption>全样本来源复查与用途分层</caption><thead><tr><th>项目</th><th>基础快照</th><th>修订快照</th></tr></thead><tbody>
    <tr><td>图像原件</td><td>452</td><td>452，逐一校验SHA256</td></tr>
    <tr><td>可读初试记录</td><td>14,317</td><td>{summary['readable_score_rows_after']:,}</td></tr>
    <tr><td>审计通过经验Q10校年</td><td>77</td><td>{summary['exact_school_years_after']}</td></tr>
    <tr><td>审计通过拟录取人数</td><td>2,312</td><td>{summary['exact_candidate_rows_after']:,}</td></tr>
    <tr><td>审计通过学校数</td><td>44</td><td>{summary['exact_schools_after']}</td></tr></tbody></table>
    <p>452个索引对应{summary['unique_source_payloads']}份不同内容，可读记录去重后为{summary['unique_readable_score_rows_after']:,}条，另有{summary['duplicate_readable_references']}条重复来源引用，不增加有效人数。可读记录的增减同时反映补读和错列排除，不能等同于新增独立信息量。未达到审计条件的名单仍保留用途；缺最终状态者只描述复试池，人数不足10者不因能算经验分位就放宽预测标签门槛。多学院学校仍存在试卷与人口口径异质性，校级合并不被解释为已经解决学院级识别。</p>
    <figure class="wide"><img src="assets/v6_2/01_coverage_part1.svg" alt="目标学校逐年名单证据覆盖第一部分"/><figcaption>图31　目标学校的逐年名单证据状态（第一部分）。灰色表示当前未形成可用初试数据，金色表示名单可读但录取口径尚未闭环，蓝色表示在既定审计条件及人数门槛下通过。颜色代表证据用途，不代表学校难度或预测准确率。</figcaption></figure>
    <figure class="wide"><img src="assets/v6_2/01_coverage_part2.svg" alt="目标学校逐年名单证据覆盖第二部分"/><figcaption>目标学校的逐年名单证据状态（第二部分），与前图采用相同口径。分图用于保留院校名称的可读性，两图合计覆盖全部81所学校。</figcaption></figure>
    <h3>8.9 固定模型跨数据版本复核</h3>
    <p>为隔离“增加资料”与“重新选模型”的作用，固定使用第4.9—4.10节的观测误差随机截距结构。各原点仅纳入更早校年；测试年人数、Q10及新名额不参与该原点拟合。同一测试键用于比较训练证据修订，扩展评价集用于描述新增可评价学校的表现，两者分别报告。修订后的名单若改变测试标签，另列同键目标变化，不将口径改变误算为模型精度提高。</p>
    <table class="small-table"><caption>固定模型的数据版本比较</caption><thead><tr><th>数据及评价范围</th><th>校年数</th><th>MAE</th><th>标准WIS</th><th>P90覆盖</th><th>P90−P50</th></tr></thead><tbody>
    <tr><td>基础证据，同一测试键</td><td>{old['n']}</td><td>{old['mae']:.2f}</td><td>{old['wis']:.2f}</td><td>{old['q90_coverage']*100:.1f}%</td><td>{old['q90_mean_width']:.2f}</td></tr>
    <tr><td>修订证据，同一测试键</td><td>{new['n']}</td><td>{new['mae']:.2f}</td><td>{new['wis']:.2f}</td><td>{new['q90_coverage']*100:.1f}%</td><td>{new['q90_mean_width']:.2f}</td></tr>
    <tr><td>修订证据，扩展评价集</td><td>{expanded['n']}</td><td>{expanded['mae']:.2f}</td><td>{expanded['wis']:.2f}</td><td>{expanded['q90_coverage']*100:.1f}%</td><td>{expanded['q90_mean_width']:.2f}</td></tr></tbody></table>
    <figure class="wide"><img src="assets/v6_2/03_fixed_model_comparison.svg" alt="同一测试键下的MAE和WIS比较"/><figcaption>图32　固定模型、同一测试键的数据版本复核。两个指标分别衡量中心误差和概率分布的联合质量，修订资料不保证每项指标均改善。</figcaption></figure>
    <table class="small-table"><caption>逐年结果：分组反映日历年变化，不能视为独立同分布个体</caption><thead><tr><th>年</th><th>范围</th><th>n</th><th>MAE</th><th>WIS</th><th>P90覆盖</th><th>上尾宽</th></tr></thead><tbody>{year_rows}</tbody></table>
    <figure class="wide"><img src="assets/v6_2/04_yearly_coverage.svg" alt="三个外层年份P90实际覆盖"/><figcaption>图33　逐年覆盖诊断。这里只有三个共同年份冲击；总体覆盖不等于每个年份、每类学校均已达到名义覆盖，亦不构成个人录取概率。</figcaption></figure>
    <p>修订快照的年份条件化嵌套REML方差占比为：学校间{reml['variance_shares']['between_school']*100:.1f}%、校年状态{reml['variance_shares']['school_year']*100:.1f}%、校年内个体{reml['variance_shares']['within_school_year']*100:.1f}%。该描述利用组内充分统计量和组间协方差，与第7章基础样本采用同一工作高斯结构；不是所有全国应用统计报名者的总体方差，也不能据此认定新增资料具有随机代表性。未以本轮三个外层年份重新选择结构或宣布显著优越。</p>
    <h3>8.10 官方资料的外部交叉核验</h3>
    <p>同济大学数学科学学院的官方通知分别将2025年、2026年应用统计01、02方向复试线列为385、396分，03、04非全日制方向列为323、324分。按年度专业目录区分学习方式后，原校级复试线须作修订。复试线与拟录取Q10是不同变量，前者的纠错本身不等于后者已获官方最终名单认证。</p>
    <p>对2025年原图底部的排除规则重新核验后，普通拟录取人数为33，经验Q10为388.0分；2026年补读漏行并排除原图明确标注的专项后，普通拟录取人数为29，经验Q10为412.2分。2026年官方复试成绩附件可交叉核对404分记录及386分专项，但最终拟录取入口现已关闭，故目前仍按经汇总及结构核对的二次名单快照表述，不声称取得全部官方最终逐人原件。2023、2024年官方复试成绩材料仅保留为阶段证据，不能依据综合排名和计划人数截取所谓最终名单。</p>
    <figure class="wide"><img src="assets/v6_2/02_tongji_admitted_quantiles.svg" alt="同济两个已实现录取队列的分位轮廓"/><figcaption>图34　同济大学审计名单的组内分位轮廓。两条曲线描述两个已实现队列，不是下一年Q10的预测区间；年际位置变化与校年内展开必须区分。</figcaption></figure>
    <p>2027年432科目调整公告发布于2026年6月26日，早于原信息冻结截点。事件存在性可核实，不能据此确定其对门槛的影响方向、幅度或三情景概率。另有学院目录“97人”，原文注明为上一年实际招生总数且含推免及专项、跨多个专业，故排除为当年应用统计普通统考净名额。证据时点、统计年度、专业人群与数字定义须同时一致，才构成可用特征。</p>
    <p>这些修订作为独立数据版本保留，不覆盖原2027预测。当前网页对于已确认口径错误且遗漏已知事件的学校暂停稳保标签；这属于预测使用边界修订，不是对未重新估计的事件概率作数值补丁。</p>
    '''
    marker='  <section>\n    <h2>九、讨论：方法价值、局限与推广</h2>'
    if source.count(marker)!=1:raise ValueError("Ambiguous new analysis insertion")
    new_section=re.sub(r'<figcaption>图\d+　', '<figcaption>', new_section).rstrip()
    source=source.replace(marker,'<section>\n'+new_section+'\n</section>\n'+marker,1)
    # New material uses existing chapter structure; preserve all old methods,
    # negative results and sources while making their data vintage explicit.
    conclusion='<p>来源审计修订再次表明，复杂的预测分布无法补救输入字段含义或学习方式混合。固定模型的跨数据版本复核应与重新调参分开进行，并在同一评价对象上比较。资料不足时保留缺口与适用限制，比以代理、旧年份名额或未经识别的事件概率补出完整数值更符合可验证的统计研究。</p>'
    source=source.replace('<h2>十、结论</h2>', '<h2>十、结论</h2>'+conclusion,1)
    extra_refs='<section class="references"><h2>附录 D　修订证据的官方来源与定位</h2><p>下表为新核验的第一手公开来源。整理工作簿不作为公共原始文献；旧来源目录继续保留。网页抓取时间和内容哈希见同名公开数据台账，个人名单原件不再公开镜像。无日期入口不补造发布日期。</p>'
    extra_refs+=''.join(f'<p>[D{i+1}] {html.escape(row.school)}. {html.escape(row.title)}[EB/OL]. {html.escape(row.publish_date or "发布日期未核定")}. <a href="{html.escape(row.source_url,quote=True)}">{html.escape(row.source_url)}</a>. {html.escape(row.notes)}.</p>' for i,row in enumerate(sources.itertuples()))+'</section>'
    source=source.replace('</main>',extra_refs+'\n</main>',1)
    source=source.replace('</ol><p class="toc-summary', '<li><span class="label">附录 D　修订证据的官方来源与定位</span><span class="dots"></span><span class="page" data-toc="14"></span></li></ol><p class="toc-summary',1)
    source=source.replace('<h2>附录 A　2027 年 81 所院校预测表</h2>', '<h2>附录 A　原冻结快照的2027年81校预测表</h2><p>此表保留原冻结结果作前瞻对照。对同济大学已确认的方向口径错误及遗漏事件，表内数值不作当前稳保判断。最新资料见第8.10节和修订证据台账。</p>',1)
    # The existing table of contents has hand-coded page numbers. Remove
    # them instead of publishing stale pagination after inserting new results.
    source=re.sub(r'(<span class="page" data-toc="\d+">)\d+(</span>)',r'\1\2',source)
    source=source.replace('</style>',' .references a { overflow-wrap:anywhere; word-break:break-all; }\n</style>',1)
    toc_audit=ASSETS/'toc_pages.json'
    if toc_audit.exists():
        stored=json.loads(toc_audit.read_text(encoding='utf-8'))
        if stored['source_content_sha256']==hashlib.sha256(source.encode()).hexdigest():
            for record in stored['headings']:
                source=re.sub(r'(<span class="page" data-toc="'+str(record['index'])+r'">)\d*(</span>)',
                    lambda m:m.group(1)+str(record['page'])+m.group(2),source,count=1)
    target=ROOT/'paper/modeling_paper_v6_2.html';target.write_text(source,encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
