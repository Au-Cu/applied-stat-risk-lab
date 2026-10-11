"use client";

import { useId, useState } from "react";
import statistics from "../app/data/model-v6-statistics.json";

const research = statistics;
const choices = [
  { id: "finite", name: "这届完整名单", formula: "T = 名单分数的经验 Q10", explanation: "名单口径正确、完整且读取无误时，这个数可以直接计算。仍需查漏页、专项混入与 OCR；这些是观测问题，不是随机抽样误差。", uncertainty: "标签审核：是否完整、是否读对" },
  { id: "population", name: "假想重复招生总体", formula: "θ = 选择总体的 Q10", explanation: "另加独立同分布的工作假设，才能用顺序统计和 Bootstrap 推断潜在总体低尾。51/77 个校年的 95% 非参数下界只能取理论界，说明小名单识别能力有限。", uncertainty: "总体推断：需要额外统计假设" },
  { id: "future", name: "下一届未知结果", formula: "G(x) = P(下一届 T ≤ x | 报名前信息)", explanation: "择校真正需要预测这一层：即使今年的名单完全读对，下一年仍会有公共年份冲击、学校状态变化和未来队列波动。预测上界不是个人录取保证。", uncertainty: "未来预测：需要时间外检验" },
] as const;

const modelNames = {
  frozen_baseline: "冻结基线", v5_exact_enhanced: "精确标签增强", random_intercept: "观测误差随机截距",
  local_level: "局部水平随机过程", local_level_equal_precision: "等精度局部水平",
} as const;
const palette = ["#708090", "#387db3", "#20a693"];

export function StatisticalResearchPanel() {
  const instance = useId();
  const [objectIndex, setObjectIndex] = useState(2);
  const [varianceBasis, setVarianceBasis] = useState<"descriptive" | "reml">("reml");
  const selected = choices[objectIndex];
  const reml = research.nested_reml_calendar_adjusted;
  const variance = varianceBasis === "reml"
    ? [reml.variance_shares.between_school, reml.variance_shares.school_year, reml.variance_shares.within_school_year]
    : [.430, .109, .461];
  const metrics = research.rolling_metrics;
  const shape = research.multivariate_shape_pca;
  const inference = research.paired_small_year_inference;

  return (
    <section className="statistical-research" aria-labelledby={`${instance}-title`}>
      <div className="section-title-row"><div><span className="eyebrow">V6 · MODERN STATISTICAL RESEARCH</span><h3 id={`${instance}-title`}>统计学不是算法名单：目标、层次与证据要对应</h3></div><span className="section-note">2,312 名考生 · 77 校年 · 只有 3 个时间外年份</span></div>
      <p className="statistics-intro">回归、随机过程、贝叶斯、非参数、多元分析和机器学习均可使用。这里将它们放到各自能回答的问题上，并展示实际比较结果；新研究没有覆盖已冻结的 2027 预测。</p>

      <div className="stat-object-switch" role="tablist" aria-label="选择统计对象">
        {choices.map((choice, index) => <button type="button" role="tab" aria-selected={index === objectIndex} aria-controls={`${instance}-content`} id={`${instance}-object-${index}`} className={index === objectIndex ? "active" : ""} key={choice.id} onClick={() => setObjectIndex(index)}>{index + 1}. {choice.name}</button>)}
      </div>
      <div className="stat-object-detail" id={`${instance}-content`} role="tabpanel" aria-labelledby={`${instance}-object-${objectIndex}`}>
        <span>{selected.uncertainty}</span><strong>{selected.formula}</strong><p>{selected.explanation}</p>
      </div>

      <div className="stat-inference-flow" aria-label="新研究候选的实际计算链">
        <article><span>历史证据</span><strong>精确优先，代理不重复</strong><small>更早配对估计代理偏差与方差；有精确名单时只用一次目标。</small></article><i aria-hidden="true">→</i>
        <article><span>潜在状态</span><strong>学校共享 + 校年变化</strong><small>REML 估计方差；经验贝叶斯借用跨校信息，或让状态按时间延续。</small></article><i aria-hidden="true">→</i>
        <article><span>下一届分布</span><strong>共同年份 + 状态 + 队列</strong><small>未来队列精度只能用历史估计，不读取测试年人数。</small></article><i aria-hidden="true">→</i>
        <article><span>真正的检验</span><strong>只预测未见年份</strong><small>同时看中心误差、WIS、上尾宽度和逐年覆盖，而非只看 MAE。</small></article>
      </div>
      <p className="stat-technical">技术含义：观测为 y = 潜在边际 m + 队列项 + 代理误差；随机截距 m = μ + a<sub>学校</sub> + u<sub>校年</sub>；动态候选 m<sub>t</sub> = m<sub>t−1</sub> + ω<sub>t</sub>。高斯预测近似的方差是国家线、状态与未来队列方差之和，依赖近似独立假设；超参数插件估计尚未全部积分。</p>

      <div className="stat-two-column">
        <article className="stat-card">
          <h4>同一批数据，可以有不同方差问题</h4>
          <div className="stat-basis-switch" role="group" aria-label="方差口径">
            <button type="button" aria-pressed={varianceBasis === "descriptive"} onClick={() => setVarianceBasis("descriptive")}>院校等权描述</button>
            <button type="button" aria-pressed={varianceBasis === "reml"} onClick={() => setVarianceBasis("reml")}>年份条件化 REML</button>
          </div>
          <div className="stat-variance-strip">{variance.map((v, i) => <span key={i} style={{ width: `${v * 100}%`, background: palette[i] }}>{(v * 100).toFixed(1)}%</span>)}</div>
          <div className="stat-variance-labels">{["院校间", "校年状态", "校年内个体"].map((name, i) => <span key={name}><i style={{ background: palette[i] }} />{name}</span>)}</div>
          <p>{varianceBasis === "reml" ? "REML 是逐人高斯工作模型，控制共同年份差异；同校同年相关约 0.468。" : "描述性分解对院校等权，描述这批已观察学校，不估计随机效应超参数。"} 两种比例不是同一估计目标，也不代表全部报名者。</p>
          {varianceBasis === "reml" && <div className="stat-variance-intervals">{(["between_school", "school_year", "within_school_year"] as const).map((key, i) => <span key={key}>{["院校间", "校年", "个体"][i]}方差：{reml.variances[key].toFixed(1)}，近似 95% [{reml.profile95_intervals[key].lower.toFixed(1)}, {reml.profile95_intervals[key].upper.toFixed(1)}] 分²</span>)}</div>}
        </article>
        <article className="stat-card">
          <h4>新候选改善了概率评分，没有赢下所有指标</h4>
          <svg viewBox="0 0 470 225" role="img" aria-label="冻结、精确增强与随机截距的上尾宽度和WIS比较">
            <line x1="65" y1="175" x2="435" y2="175" stroke="#66788d" /><line x1="65" y1="35" x2="65" y2="175" stroke="#66788d" />
            <text x="230" y="215" textAnchor="middle">平均 P90−P50 / 分（越窄越锐）</text><text x="13" y="22">标准 WIS（越小越好）</text>
            {[22, 26, 30, 34].map(v => <text x={65 + (v - 21) * 26} y="191" key={v} textAnchor="middle">{v}</text>)}
            {[9, 10, 11].map(v => <text x="52" y={175 - (v - 8) * 42} key={v} textAnchor="end">{v}</text>)}
            {(["frozen_baseline", "v5_exact_enhanced", "random_intercept"] as const).map((key, i) => {
              const m = metrics[key]; const x = 65 + (m.q90_mean_width - 21) * 26; const y = 175 - (m.wis - 8) * 42;
              return <g key={key}><circle cx={x} cy={y} r="6" fill={palette[i]} /><text x={x} y={y + (i === 0 ? -14 : 23)} textAnchor="middle" fill={palette[i]}>{modelNames[key]}</text></g>;
            })}
          </svg>
          <p>随机截距 MAE {metrics.random_intercept.mae.toFixed(2)} 分，略高于精确增强 {metrics.v5_exact_enhanced.mae.toFixed(2)}；WIS 则从 {metrics.v5_exact_enhanced.wis.toFixed(2)} 降至 {metrics.random_intercept.wis.toFixed(2)}。总体 P90 覆盖约 93%，但 2026 年只有约 82%，不能宣布可靠“90% 保证”。</p>
        </article>
      </div>

      <div className="stat-model-table-wrap"><table className="stat-model-table"><caption>同一批 54 个精确校年的方法比较；分数单位为分</caption><thead><tr><th>方法</th><th>MAE ↓</th><th>标准 WIS ↓</th><th>P90 覆盖</th><th>P90−P50</th></tr></thead><tbody>
        {(Object.keys(modelNames) as (keyof typeof modelNames)[]).map(key => <tr key={key}><th scope="row">{modelNames[key]}</th><td>{metrics[key].mae.toFixed(2)}</td><td>{metrics[key].wis.toFixed(2)}</td><td>{Math.round(metrics[key].q90_coverage * 100)}%</td><td>{metrics[key].q90_mean_width.toFixed(1)}</td></tr>)}
        {(["ridge", "neural_4"] as const).map(key => <tr key={key}><th scope="row">{key === "ridge" ? "岭回归" : "4 隐节点神经网络"}</th><td>{research.regression_challengers.metrics[key].mae.toFixed(2)}</td><td colSpan={3}>只验证中心，不制造概率上界</td></tr>)}
      </tbody></table></div>

      <div className="stat-two-column">
        <article className="stat-card">
          <h4>聚类与因子分析：描述有价值，预测要另验</h4>
          <svg viewBox="0 0 470 225" role="img" aria-label="三个探索性聚类的相对分位曲线，不代表学校风险等级">
            <line x1="54" y1="172" x2="437" y2="172" stroke="#66788d" /><line x1="54" y1="32" x2="54" y2="180" stroke="#66788d" />
            <text x="5" y="21">相对本校年 Q10 / 分</text>
            {[0, 20, 40, 60].map(v => <text x="44" y={172 - v * 2} textAnchor="end" key={v}>{v}</text>)}
            {[5, 10, 25, 50, 75, 90, 95].map(q => <text x={54 + (q - 5) / 90 * 380} y={q === 10 || q === 95 ? 217 : 197} textAnchor="middle" key={q}>Q{String(q).padStart(2, "0")}</text>)}
            {shape.descriptive_cluster_profiles.map((g, i) => {
              const offsets = [g.relative_quantile_centroid[0], 0, ...g.relative_quantile_centroid.slice(1)];
              const points = [5, 10, 25, 50, 75, 90, 95].map((q, j) => `${54 + (q - 5) / 90 * 380},${172 - offsets[j] * 2}`).join(" ");
              return <polyline points={points} fill="none" stroke={palette[i]} strokeWidth="2.5" key={g.cluster} />;
            })}
          </svg>
          <div className="stat-variance-labels">{shape.descriptive_cluster_profiles.map((g, i) => <span key={g.cluster}><i style={{ background: palette[i] }} />形状类 {g.cluster}：{g.groups} 校年</span>)}</div>
          <p>前两个主成分解释约 {Math.round(shape.explained_variance_ratio.slice(0, 2).reduce((a, b) => a + b) * 100)}% 的观察形状变异。聚类主要描述分布宽窄；单因子显示中上分位有共同展开、低尾仍有独特差异。它们不是五派系，也不是固定学校类型或因果机制。</p>
          <p className="stat-technical">聚类形状 MAE {shape.rolling_shape_mae.lag_cluster3.toFixed(2)}，未压缩同校形状 {shape.rolling_shape_mae.lag_full.toFixed(2)}：改善很小，未自动替换。描述用全样本；测试逐年重拟合，不能用未来基底。</p>
        </article>
        <article className="stat-card">
          <h4>少数年份：不能只挑漂亮的区间</h4>
          <div className="stat-year-differences">{Object.entries(inference.year_mean_differences).map(([year, v]) => <div key={year}><span>{year}</span><strong className={v > 0 ? "worse" : "better"}>{v > 0 ? "+" : ""}{v.toFixed(2)}</strong><small>精确增强 − 冻结基线 MAE</small></div>)}</div>
          <p>年份等权差约 −1.51 分，但三个年份中一年恶化。自由度 2 的 90% t 区间 [{inference.t90_interval_df2.map(v => v.toFixed(2)).join(", ")}] 跨过 0；年份符号翻转双侧 p={inference.exact_year_signflip_two_sided_p.toFixed(2)}。</p>
          <p>这些推断仍依赖年份独立、正态或对称假设，不能由 3 年可靠检验。恰当结论是“当前测试集合有改善”，不是“新年份显著且稳定优越”。</p>
          <a href="https://github.com/Au-Cu/applied-stat-risk-lab/releases/tag/v0.4.0" target="_blank" rel="noreferrer">查看 V6 论文、公开聚合结果和完整假设 ↗</a>
        </article>
      </div>
      <div className="research-freeze-note"><strong>研究与前瞻分开：</strong><span>新增候选未通过全部升级护栏。统计描述不被丢弃，预测失败也如实保留；2027 排名和分数仍读取原冻结快照。没有纳入个人考生估分随机性。</span></div>
    </section>
  );
}
