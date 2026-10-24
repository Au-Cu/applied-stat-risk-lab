"use client";

import evidence from "../app/data/evidence-refresh.json";

export function schoolEvidence(school: string) {
  return evidence.schools.find((item) => item.school === school);
}

export function needsEvidenceReview(school: string) {
  return schoolEvidence(school)?.needsForecastReview ?? false;
}

export function EvidenceRefreshPanel({ school }: { school: string }) {
  const current = schoolEvidence(school);
  if (!current) return null;
  return (
    <section className="evidence-refresh-card" aria-label={`${school}最新证据核验`}>
      <h3>最新证据核验 <span>2026-10-24</span></h3>
      <p>以下是本轮核验记录；上方证据分数属于旧冻结预测。资料是否齐全、名单是否核对通过，与预测是否准确是不同的问题。</p>
      <dl className="evidence-counts">
        <div><dt>已有名单</dt><dd>{current.rosterImages} 张</dd></div>
        <div><dt>读出初试分数</dt><dd>{current.readableRows.toLocaleString("zh-CN")} 条</dd></div>
        <div><dt>通过名单核对</dt><dd>{current.exactYears.length} 个校年</dd></div>
      </dl>
      {current.units.length > 1 && <p className="evidence-scope-note">涉及 {current.units.join("、")}。校级汇总不能替代学院及试卷口径核验，报名时仍需选定培养单位。</p>}
      {!!current.currentDistribution.length && (
        <div className="evidence-table-wrap"><table>
          <caption>审计通过名单内的经验分布（非未来预测）</caption>
          <thead><tr><th>年份</th><th>人数</th><th>最低</th><th>Q10</th><th>中位</th><th>最高</th></tr></thead>
          <tbody>{current.currentDistribution.map((row) => <tr key={row.year}><th>{row.year}</th><td>{row.n}</td><td>{row.minimum}</td><td>{row.q10.toFixed(1)}</td><td>{row.median}</td><td>{row.maximum}</td></tr>)}</tbody>
        </table></div>
      )}
      {!!current.cutoffCorrections.length && <div className="evidence-correction">
        <strong>已更正全日制方向复试线</strong>
        <p>{current.cutoffCorrections.map((item) => `${item.year} 年 ${item.previous} → ${item.verified} 分`).join("；")}。旧值混入非全日制方向。下方官方来源可以核对。</p>
      </div>}
      {current.knownEvent && <div className="evidence-correction">
        <strong>{current.knownEvent.name}</strong>
        <p>{current.knownEvent.description}</p>
        <a href={current.knownEvent.url} target="_blank" rel="noreferrer">官方公告 · {current.knownEvent.publishDate} ↗</a>
      </div>}
      {!!current.quotaEvidence2027.length && <div className="evidence-correction"><strong>已有报名截止前净名额证据</strong>{current.quotaEvidence2027.map((item) => <div key={`${item.unit}-${item.url}`}><p>{item.unit}：推免后普通统考计划 {item.netSeats} 人，公布于 {item.publishDate}。{item.unitLinked ? "培养单位已对应。" : "与校级标签的培养单位尚未对应。"}原文核对状态：{item.reviewStatus}。名额候选仍未替换正式预测。</p><a href={item.url} target="_blank" rel="noreferrer">查看原公告 ↗</a></div>)}</div>}
      <details open={current.needsForecastReview}>
        <summary>仍需补齐的证据（{current.missing.length} 项）</summary>
        <ul>{current.missing.map((item) => <li key={item}>{item}</li>)}</ul>
        {current.needsForecastReview && <p>2023、2024 年官方复试成绩附件已找到，但最终拟录取状态尚未恢复；不能按综合排名截取或把复试者全部算作录取者。</p>}
      </details>
      {!!current.officialLinks.length && <details><summary>本轮核验的官方原文</summary><ul>{current.officialLinks.map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.title} {item.publishDate} ↗</a></li>)}</ul></details>}
      <p className="evidence-privacy-note">原图和逐人成绩留在本地；页面仅展示校年聚合。二次名单经核对通过，也不等于官方最终逐人名单已经全部取得。</p>
    </section>
  );
}

export function EvidenceRefreshOverview() {
  const summary = evidence.summary;
  const metrics = evidence.experiment?.same_key_test;
  return <section className="evidence-refresh-overview" aria-label="全校证据复查结果">
    <h3>先核对读到了什么，再判断模型有没有变好</h3>
    <p>本轮覆盖全部 {summary.scope_schools} 所目标学校，逐项保留 {summary.scope_school_years} 个校年的资料状态。公开接口读取成功 {summary.api_targets_successful}/{summary.api_targets_refreshed}；名单原图逐一校验内容哈希，并按表头检查初试成绩列。</p>
    <div className="evidence-change-flow">
      <div><span>原件</span><strong>{summary.unique_source_payloads} 份</strong><small>{summary.local_source_hashes_verified} 个索引，重复内容已标识</small></div>
      <b aria-hidden="true">→</b><div><span>识别</span><strong>{summary.unique_readable_score_rows_after.toLocaleString("zh-CN")} 条</strong><small>初试记录去重；核对分数列及图例</small></div>
      <b aria-hidden="true">→</b><div><span>标签</span><strong>{summary.exact_school_years_after} 个校年</strong><small>审计通过经验 Q10</small></div>
      <b aria-hidden="true">→</b><div><span>验证</span><strong>固定模型重算</strong><small>同一测试键与扩展测试集分开</small></div>
    </div>
    {metrics && <p>同一测试键：原证据 MAE {metrics.previous.mae.toFixed(2)} 分，更新后 {metrics.refreshed.mae.toFixed(2)} 分；标准 WIS {metrics.previous.wis.toFixed(2)} → {metrics.refreshed.wis.toFixed(2)}。这是数据更新的回溯复核，未调参，也没有自动晋级为正式预测。</p>}
    <p>原冻结预测保留以便对照。选中院校的最新证据及未闭环项可在详情面板查看，完整 405 行缺口表和修订论文随新版本公开。</p>
    <a href="https://github.com/Au-Cu/applied-stat-risk-lab/tree/main/data/processed/evidence_refresh_20261024" target="_blank" rel="noreferrer">查看全部院校的证据与缺口表 ↗</a>
    <p><a href="https://github.com/Au-Cu/applied-stat-risk-lab/releases/tag/v0.5.0" target="_blank" rel="noreferrer">查看 V6.2 修订论文和版本说明 ↗</a></p>
  </section>;
}
