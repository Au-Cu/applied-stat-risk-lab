"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  Database,
  FileSearch,
  Gauge,
  GitBranch,
  Info,
  Layers3,
  Network,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  TestTube2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import forecastData from "./data/forecast.json";

type EventScenario = {
  type: string;
  name: string;
  severity: string;
  source: string;
  status: string;
  scenarios: { withdrawal: number; neutral: number; crowd: number };
};

type Prediction = {
  school: string;
  is985: boolean;
  zone: string;
  unit: string | null;
  english: string | null;
  math: string | null;
  location: string | null;
  latestCutoff: number | null;
  latestQ10Proxy: number | null;
  historyCount: number;
  confidence: string;
  confidenceScore: number;
  q05: number;
  q10: number;
  q20: number;
  q50: number;
  q80: number;
  q90: number;
  q95: number;
  nationalLineMedian: number;
  nationalLineQ90: number;
  lagSurpriseZ: number | null;
  peerPressure: number | null;
  events: EventScenario[];
  eventCoverage: string;
  selectedModel: string;
  decomposition: Record<string, number>;
};

const predictions = forecastData.predictions as Prediction[];
const meta = forecastData.meta;

const pipelineSteps = [
  {
    id: "collect",
    code: "01",
    title: "收集证据",
    short: "官网与历史结果",
    plain: "先把每所学校过去发生过什么收齐：复试线、拟录取成绩、招生人数、考试科目和官方公告。每个数字都要能追溯到来源。",
    technical: "抓取并标准化院校—年份面板；为官网、官方二次来源和第三方来源分别赋证据等级，不把网页文本直接当成可训练数值。",
    input: "招生目录、复试名单、拟录取名单、学院公告",
    output: "带年份、口径和来源链接的原始记录",
    guardrail: "只使用报名开始前已经公开的信息",
  },
  {
    id: "audit",
    code: "02",
    title: "统一口径",
    short: "排除混入样本",
    plain: "把专项计划、非全日制、调剂生等不属于目标人群的记录排除，并标出互相矛盾或缺少来源的数据。",
    technical: "定义正常统考全日制025200样本；执行复试线、最低分、复录比和专项计划一致性规则，并把证据质量转换为训练权重。",
    input: "原始记录与招生口径",
    output: "可训练标签、缺失标记和人工复核队列",
    guardrail: "宁可降权或留空，也不把不确定值伪装成真值",
  },
  {
    id: "features",
    code: "03",
    title: "构造信号",
    short: "把分数变成可比量",
    plain: "不同年份国家线不同，直接比较总分会失真。因此先看学校分数高出国家线多少，再加入冷热反转、招生变化和竞校热度。",
    technical: "以国家线以上边际分为核心状态量，生成严格滞后的历史中位数、惊讶度、同层竞校压力、名额与缺失机制特征。",
    input: "清洗后的历年成绩与当时可见信息",
    output: "不会偷看未来的模型特征",
    guardrail: "所有动态字段至少滞后一年",
  },
  {
    id: "models",
    code: "04",
    title: "候选模型",
    short: "简单模型也参赛",
    plain: "让稳健历史锚点、分层贝叶斯和提升树一起参加比赛，而不是默认更复杂的模型一定更准。",
    technical: "比较稳健边际分锚点、上一年锚点、部分池化动态回归与梯度提升分位数；复杂模型同时提供尾部形状与变量解释。",
    input: "同一套无泄漏特征",
    output: "多个候选点预测和概率分布",
    guardrail: "复杂度必须通过样本外回测赢得权重",
  },
  {
    id: "backtest",
    code: "05",
    title: "逐年回测",
    short: "模拟真实报名时点",
    plain: "假装自己回到2024、2025、2026年报名之前，只用更早的数据预测，再和后来真实结果比较。",
    technical: "采用 expanding-window rolling origin；同时评估加权MAE、低估三倍损失、分位覆盖率和区间宽度。",
    input: "候选模型的历史外推结果",
    output: "谁真正更准、谁只是在拟合历史",
    guardrail: "模型选择和校准都只能使用当时以前的残差",
  },
  {
    id: "scenarios",
    code: "06",
    title: "事件与校准",
    short: "传播未知风险",
    plain: "换考纲可能让人退潮，也可能吸引人涌入，所以不拍脑袋给一个固定加分，而是保留三种情景并扩大不确定区间。",
    technical: "将官方事件映射为退潮/中性/涌入离散混合；再用滚动残差校准P80/P90/P95上界，并为未闭环事件加入厚尾噪声。",
    input: "基础预测、官方事件和历史残差",
    output: "经过校准的完整分数分布",
    guardrail: "未发现公告不等于确认没有事件",
  },
  {
    id: "decision",
    code: "07",
    title: "个人决策",
    short: "把分布翻译成冲稳保",
    plain: "最后才把你的估分放进学校的预测分布，计算达到目标所需分数的把握度，并按统一阈值给出冲、观察、稳、保。",
    technical: "对分位锚点分段插值形成个人通过概率；稳≥90%、保≥95%，同时展示数据可信度与主要不确定性来源。",
    input: "你的悲观估分与学校概率分布",
    output: "P50/P80/P90/P95、把握度和风险标签",
    guardrail: "这是学校间风险比较，不是个人录取保证",
  },
] as const;

const accuracyRoadmap = [
  { priority: "P0", title: "考生级精确P10", impact: "最高", status: "待补数", why: "当前最大误差来自目标标签本身。拿到普通统考逐人成绩后，可直接计算P10并彻底替换代理值。" },
  { priority: "P0", title: "报名时可见的统考名额", impact: "最高", status: "待补数", why: "区分总计划、推免和普通统考名额，避免用最终录取人数造成信息泄漏。" },
  { priority: "已完成", title: "历史边际分稳健锚点", impact: "已验证", status: "v0.2", why: "用历年高出国家线的中位数抵抗单年爆冷爆热；滚动回测MAE由18.58降至17.12。" },
  { priority: "P1", title: "事件相似案例库", impact: "高", status: "设计中", why: "把历次换考纲、扩缩招和学制变化变成可学习样本，让三情景权重由历史相似事件决定。" },
  { priority: "P1", title: "竞校迁移网络", impact: "中高", status: "设计中", why: "按地域、层次、考试科目和分数带建立替代关系，估计某校变化会把考生推向哪些学校。" },
  { priority: "P1", title: "滚动保序校准", impact: "中高", status: "待实验", why: "在时间切分下做分组共形分位校准，使90%稳妥线更接近真实90%覆盖率且不过度保守。" },
  { priority: "P2", title: "样本外动态集成", impact: "中", status: "待实验", why: "只有当复杂模型在某类学校持续胜出时，才用分层stacking分配局部权重，而不是全局固定加权。" },
];

const pipelineIcons = {
  collect: FileSearch,
  audit: Database,
  features: Layers3,
  models: GitBranch,
  backtest: TestTube2,
  scenarios: Network,
  decision: Target,
} as const;

function probabilityAtScore(item: Prediction, score: number) {
  const anchors = [
    [item.q05, 0.05],
    [item.q10, 0.1],
    [item.q20, 0.2],
    [item.q50, 0.5],
    [item.q80, 0.8],
    [item.q90, 0.9],
    [item.q95, 0.95],
  ];
  if (score <= anchors[0][0]) return Math.max(0.01, 0.05 - (anchors[0][0] - score) / 180);
  if (score >= anchors.at(-1)![0]) return Math.min(0.99, 0.95 + (score - anchors.at(-1)![0]) / 180);
  for (let index = 1; index < anchors.length; index += 1) {
    const [rightScore, rightProbability] = anchors[index];
    const [leftScore, leftProbability] = anchors[index - 1];
    if (score <= rightScore) {
      const width = Math.max(1, rightScore - leftScore);
      return leftProbability + ((score - leftScore) / width) * (rightProbability - leftProbability);
    }
  }
  return 0.5;
}

function riskLabel(probability: number) {
  if (probability >= 0.95) return { label: "保", tone: "safe" };
  if (probability >= 0.9) return { label: "稳", tone: "steady" };
  if (probability >= 0.6) return { label: "观察", tone: "watch" };
  return { label: "冲", tone: "reach" };
}

function signed(value: number | null) {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function ScoreRail({ item, score }: { item: Prediction; score: number }) {
  const min = Math.max(280, Math.floor((item.q05 - 20) / 10) * 10);
  const max = Math.min(500, Math.ceil((item.q95 + 20) / 10) * 10);
  const position = (value: number) => `${Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))}%`;
  const points = [
    { key: "P50", value: item.q50, tone: "median" },
    { key: "P80", value: item.q80, tone: "watch" },
    { key: "P90", value: item.q90, tone: "steady" },
    { key: "P95", value: item.q95, tone: "safe" },
  ];

  return (
    <div className="score-rail-wrap">
      <div className="score-rail" aria-label="预测分数分布">
        <div className="rail-band median" style={{ left: position(item.q20), width: `calc(${position(item.q80)} - ${position(item.q20)})` }} />
        <div className="rail-band safe" style={{ left: position(item.q80), width: `calc(${position(item.q95)} - ${position(item.q80)})` }} />
        {points.map((point) => (
          <div className={`rail-point ${point.tone}`} style={{ left: position(point.value) }} key={point.key}>
            <span>{Math.round(point.value)}</span>
            <small>{point.key}</small>
          </div>
        ))}
        <div className="score-marker" style={{ left: position(score) }}>
          <span>你的分数 {score}</span>
        </div>
      </div>
      <div className="rail-scale"><span>{min}</span><span>所需分数越高，风险越大</span><span>{max}</span></div>
    </div>
  );
}

export default function Home() {
  const [score, setScore] = useState(390);
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("all");
  const [sortBy, setSortBy] = useState("q90");
  const [pipelineStepId, setPipelineStepId] = useState<(typeof pipelineSteps)[number]["id"]>("collect");
  const defaultSchool = predictions.find((item) => item.school === "华东师范大学")?.school ?? predictions[0].school;
  const [selectedSchool, setSelectedSchool] = useState(defaultSchool);

  const rows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return predictions
      .filter((item) => !normalized || item.school.toLowerCase().includes(normalized) || item.location?.toLowerCase().includes(normalized))
      .filter((item) => tier === "all" || (tier === "985" ? item.is985 : !item.is985))
      .map((item) => ({ ...item, probability: probabilityAtScore(item, score) }))
      .sort((a, b) => {
        if (sortBy === "probability") return b.probability - a.probability;
        if (sortBy === "confidence") return b.confidenceScore - a.confidenceScore;
        return a.q90 - b.q90;
      });
  }, [query, score, sortBy, tier]);

  const selected = predictions.find((item) => item.school === selectedSchool) ?? rows[0] ?? predictions[0];
  const selectedProbability = probabilityAtScore(selected, score);
  const selectedRisk = riskLabel(selectedProbability);
  const backtest = meta.backtest;
  const activePipelineStep = pipelineSteps.find((step) => step.id === pipelineStepId) ?? pipelineSteps[0];
  const liveExample = (() => {
    if (pipelineStepId === "collect") return `${selected.school}：已形成 ${selected.historyCount} 个历史目标标签，最新复试线 ${selected.latestCutoff ?? "待核验"} 分。`;
    if (pipelineStepId === "audit") return `${selected.school} 当前数据可信度 ${selected.confidenceScore}/100；异常记录会降权并进入人工复核队列。`;
    if (pipelineStepId === "features") return `最近一年冷热惊讶度 ${signed(selected.lagSurpriseZ)}σ，同层竞校压力 ${signed(selected.peerPressure)}σ。`;
    if (pipelineStepId === "models") return `本校点预测采用“${selected.selectedModel}”，复杂模型只负责分布形状与解释。`;
    if (pipelineStepId === "backtest") return `v0.2 主流程滚动MAE ${backtest.mae} 分；稳健锚点 ${backtest.robust_margin_anchor_mae} 分，上一年锚点 ${backtest.last_year_baseline_mae} 分。`;
    if (pipelineStepId === "scenarios") return `${selected.events.length ? `${selected.events.length}条官方事件进入三情景` : "未检索到官方事件，已加入未知事件厚尾"}；90%残差加成 ${meta.calibrationOffsets.q90} 分。`;
    return `你的估分 ${score} 分，对 ${selected.school} 的当前把握约 ${Math.round(selectedProbability * 100)}%，标签为“${selectedRisk.label}”。`;
  })();

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><BarChart3 size={18} /></div>
        <div className="brand-copy">
          <strong>应用统计择校风险实验室</strong>
          <span>025200 · 全日制 · 985/211 · 公开研究</span>
        </div>
        <div className="topbar-meta">
          <Badge className="live-badge">2027 预测 · v0.2</Badge>
          <span>信息截点 {meta.asOf}</span>
        </div>
      </header>

      <section className="control-strip">
        <div className="score-control">
          <div className="section-kicker"><Gauge size={15} /> 我的初试估分</div>
          <div className="score-value"><strong>{score}</strong><span>分</span></div>
          <Slider value={[score]} onValueChange={(value) => setScore(value[0])} min={300} max={460} step={1} aria-label="初试估分" />
          <div className="slider-labels"><span>300</span><span>建议用悲观模拟分</span><span>460</span></div>
        </div>
        <div className="scope-note">
          <ShieldCheck size={18} />
          <div><strong>“稳”按 ≥90% 定义</strong><span>低估学校所需分数的损失按高估的 3 倍计算</span></div>
        </div>
      </section>

      <Tabs defaultValue="map" className="workspace-tabs">
        <TabsList variant="line" className="main-tabs">
          <TabsTrigger value="map">择校地图</TabsTrigger>
          <TabsTrigger value="backtest">回测与可信度</TabsTrigger>
          <TabsTrigger value="audit">数据审计</TabsTrigger>
          <TabsTrigger value="method">全流程与优化</TabsTrigger>
        </TabsList>

        <TabsContent value="map" className="tab-panel">
          <div className="main-grid">
            <section className="ranking-panel panel">
              <div className="panel-head">
                <div><span className="eyebrow">RISK RANKING</span><h1>按你的分数筛学校</h1></div>
                <span className="row-count">{rows.length} / {predictions.length} 所</span>
              </div>
              <div className="filter-row">
                <div className="search-box"><Search size={15} /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学校或城市" /></div>
                <select value={tier} onChange={(event) => setTier(event.target.value)} aria-label="院校层次"><option value="all">全部层次</option><option value="985">985</option><option value="211">非985的211</option></select>
                <select value={sortBy} onChange={(event) => setSortBy(event.target.value)} aria-label="排序方式"><option value="q90">按稳妥线</option><option value="probability">按把握度</option><option value="confidence">按数据可信度</option></select>
              </div>

              <div className="table-wrap">
                <table>
                  <thead><tr><th>院校</th><th>中位预测</th><th>90%稳妥线</th><th>当前把握</th><th>标签</th></tr></thead>
                  <tbody>
                    {rows.map((item) => {
                      const risk = riskLabel(item.probability);
                      return (
                        <tr key={item.school} data-active={item.school === selected.school} onClick={() => setSelectedSchool(item.school)}>
                          <td><strong>{item.school}</strong><span>{item.is985 ? "985" : "211"} · {item.zone}区 · {item.confidence}可信</span></td>
                          <td className="mono">{Math.round(item.q50)}</td>
                          <td className="mono emphasis">{Math.round(item.q90)}</td>
                          <td><div className="prob-cell"><span>{Math.round(item.probability * 100)}%</span><Progress value={item.probability * 100} /></div></td>
                          <td><span className={`risk-pill ${risk.tone}`}>{risk.label}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {!rows.length && <div className="empty-state">没有符合当前筛选条件的学校</div>}
              </div>
            </section>

            <aside className="detail-panel panel">
              <div className="detail-title">
                <div><span className="eyebrow">SELECTED SCHOOL</span><h2>{selected.school}</h2><p>{selected.unit ?? "培养单位待核验"} · {selected.math ?? "数学科目待核验"}</p></div>
                <span className={`risk-orb ${selectedRisk.tone}`}><strong>{selectedRisk.label}</strong><small>{Math.round(selectedProbability * 100)}%</small></span>
              </div>

              <div className="confidence-banner">
                <span>数据可信度</span><strong>{selected.confidence} · {selected.confidenceScore}/100</strong>
                <Progress value={selected.confidenceScore} />
              </div>

              <ScoreRail item={selected} score={score} />

              <div className="quantile-grid">
                <Metric label="中位预测" value={`${Math.round(selected.q50)}`} note="50% 情景" />
                <Metric label="80% 上界" value={`${Math.round(selected.q80)}`} note="偏稳参考" />
                <Metric label="90% 上界" value={`${Math.round(selected.q90)}`} note="稳妥线" />
                <Metric label="95% 上界" value={`${Math.round(selected.q95)}`} note="保守线" />
              </div>

              <div className="signal-grid">
                <div><span>上年热/冷异常</span><strong>{signed(selected.lagSurpriseZ)}σ</strong><small>{(selected.lagSurpriseZ ?? 0) > 0.8 ? "偏热，警惕次年回撤" : (selected.lagSurpriseZ ?? 0) < -0.8 ? "偏冷，警惕考生涌入" : "接近常态"}</small></div>
                <div><span>同层竞校压力</span><strong>{signed(selected.peerPressure)}σ</strong><small>相近院校上一年共同热度</small></div>
              </div>

              <div className="event-card">
                <div className="card-title"><Sparkles size={16} /><strong>事件情景</strong><span>{selected.events.length ? `${selected.events.length} 条官方事件` : "事件扫描未闭环"}</span></div>
                {selected.events.length ? selected.events.map((event) => (
                  <div className="event-item" key={`${event.type}-${event.name}`}>
                    <p>{event.name}</p>
                    <div className="scenario-row"><span>退潮 {signed(event.scenarios.withdrawal)}</span><span>中性 {signed(event.scenarios.neutral)}</span><span>涌入 {signed(event.scenarios.crowd)}</span></div>
                    <a href={event.source} target="_blank" rel="noreferrer">查看官方原文 <ArrowUpRight size={13} /></a>
                  </div>
                )) : <p className="muted-copy">尚未检索到官方变更公告，不代表已经确认无变化；报名截止前必须人工复核招生简章。</p>}
              </div>
              <p className="model-note"><Info size={14} /> {selected.selectedModel}</p>
            </aside>
          </div>
        </TabsContent>

        <TabsContent value="backtest" className="tab-panel">
          <section className="wide-panel panel">
            <div className="panel-head"><div><span className="eyebrow">ROLLING ORIGIN · 2024—2026</span><h2>稳健历史锚点胜出，复杂模型继续负责尾部与解释</h2></div><BookOpenCheck size={28} /></div>
            <div className="metric-row">
              <Metric label="v0.2 主流程 MAE" value={`${backtest.mae} 分`} note={`${backtest.rows} 条逐年外推`} />
              <Metric label="稳健锚点 MAE" value={`${backtest.robust_margin_anchor_mae} 分`} note="历年边际分中位数" />
              <Metric label="上一年锚点 MAE" value={`${backtest.last_year_baseline_mae} 分`} note="v0.1 点预测中心" />
              <Metric label="复杂候选 MAE" value={`${backtest.complex_candidate_mae} 分`} note="未取得领先" />
            </div>
            <div className="evidence-grid">
              <div className="method-card"><span>01</span><h3>严格时间切分</h3><p>预测某一年时只使用此前年份的数据；动态特征全部滞后，避免把当年结果偷渡进输入。</p></div>
              <div className="method-card"><span>02</span><h3>单年异常先降噪</h3><p>用历年“高出国家线多少分”的中位数抵抗单年爆冷爆热；其回测MAE比上一年锚点低 {Math.max(0, backtest.last_year_baseline_mae - backtest.robust_margin_anchor_mae).toFixed(2)} 分。</p></div>
              <div className="method-card"><span>03</span><h3>保守上界再校准</h3><p>用滚动残差的 80/90/95 分位校准上界；本版 90% 残差加成约 {meta.calibrationOffsets.q90} 分。</p></div>
            </div>
            <div className="warning-line"><AlertTriangle size={16} /> 当前低估率为 {Math.round(backtest.underprediction_rate * 100)}%。P10 多为代理标签，因此回测评估的是“代理目标可预测性”，不是最终录取概率的临床式校准。</div>
          </section>
        </TabsContent>

        <TabsContent value="audit" className="tab-panel">
          <section className="wide-panel panel">
            <div className="panel-head"><div><span className="eyebrow">DATA PROVENANCE</span><h2>先区分“有数据”和“可用于决策的数据”</h2></div><Database size={28} /></div>
            <div className="metric-row"><Metric label="覆盖院校" value="81 所" note="传统985/211口径" /><Metric label="院校年度记录" value="405 条" note="2022—2026" /><Metric label="可训练标签" value="295 条" note="全部为P10代理" /><Metric label="待人工复核" value="24 条" note="已进入审计队列" /></div>
            <div className="audit-layout">
              <div>
                <h3>关键审核结论</h3>
                <ul className="audit-list"><li><strong>370</strong><span>条复试线有数值，其中原表仅 46 条标记为官方或官方二次来源。</span></li><li><strong>6</strong><span>条差额复试比例在字段间不一致。</span></li><li><strong>8</strong><span>条录取最低分低于所选复试线，需要核查是否混入专项计划。</span></li><li><strong>10</strong><span>条专项计划排除口径不明确。</span></li></ul>
              </div>
              <div className="warning-stack">{meta.dataWarnings.map((warning) => <p key={warning}><AlertTriangle size={14} />{warning}</p>)}</div>
            </div>
          </section>
        </TabsContent>

        <TabsContent value="method" className="tab-panel">
          <section className="wide-panel panel">
            <div className="panel-head"><div><span className="eyebrow">FROM EVIDENCE TO DECISION</span><h2>一条“稳/保”结论究竟是怎么来的</h2></div><BarChart3 size={28} /></div>

            <div className="pipeline-group-labels" aria-hidden="true">
              <span className="evidence-layer"><FileSearch size={14} />证据层 · 收集与清洗</span>
              <span className="inference-layer"><GitBranch size={14} />推断层 · 建模与验证</span>
              <span className="decision-layer"><ShieldCheck size={14} />决策层</span>
            </div>
            <div className="pipeline-graph" role="list" aria-label="从数据到择校决策的七步图形流程">
              {pipelineSteps.map((step, index) => {
                const StepIcon = pipelineIcons[step.id];
                const active = step.id === pipelineStepId;
                return (
                  <div className="graph-step-wrap" role="listitem" key={step.id}>
                    <button type="button" className="graph-step" data-active={active} aria-pressed={active} aria-label={`${step.title}：${step.plain}`} onClick={() => setPipelineStepId(step.id)}>
                      <span className="graph-orb"><StepIcon size={24} aria-hidden="true" /><i>{step.code}</i></span>
                      <strong>{step.title}</strong>
                      <small>{step.short}</small>
                    </button>
                    {index < pipelineSteps.length - 1 && <ChevronRight className="graph-connector" size={19} aria-hidden="true" />}
                  </div>
                );
              })}
            </div>
            <div className="pipeline-feedback"><span className="feedback-path" aria-hidden="true" /><TestTube2 size={17} aria-hidden="true" /><div><strong>回测不达标，就返回数据或特征层</strong><span>复杂度不是上线理由；只有报名时点的样本外表现能让模型进入下一环。</span></div></div>

            <div className="pipeline-explainer" aria-live="polite">
              <div className="explain-heading">
                <div><span className="eyebrow">{activePipelineStep.code} · 当前环节</span><h3>{activePipelineStep.title}</h3></div>
                <span className="technical-badge">技术说明</span>
              </div>
              <p className="explain-copy">{activePipelineStep.technical}</p>
              <div className="pipeline-facts">
                <div><span>进入这一环</span><strong>{activePipelineStep.input}</strong></div>
                <div><span>离开这一环</span><strong>{activePipelineStep.output}</strong></div>
                <div><span>防错闸门</span><strong>{activePipelineStep.guardrail}</strong></div>
              </div>
              <div className="live-example"><CheckCircle2 size={17} aria-hidden="true" /><div><span>用当前选中院校走一遍</span><strong>{liveExample}</strong></div></div>
            </div>

            <div className="formula-card"><code>所需分数 = 预测国家线 + 历史边际分稳健锚点 + 分布形状 + 事件情景 + 未知风险</code><p>v0.2 的关键变化是用历年边际分中位数抵抗单年异常；分层贝叶斯与提升树仍负责不确定性、尾部和解释。</p></div>

            <div className="roadmap-head"><div><span className="eyebrow">ACCURACY ROADMAP</span><h3>提高精度，先修数据，再增加复杂度</h3></div><p>“影响”是预期优先级，不是未经验证的分数承诺。每项优化都必须重新通过逐年滚动回测。</p></div>
            <div className="roadmap-grid">
              {accuracyRoadmap.map((item) => (
                <article className="roadmap-item" key={item.title}>
                  <div><span className="roadmap-priority">{item.priority}</span><span className="roadmap-impact">影响：{item.impact}</span></div>
                  <h4>{item.title}</h4>
                  <p>{item.why}</p>
                  <small>{item.status}</small>
                </article>
              ))}
            </div>
            <div className="research-links"><span>方法依据</span><a href="https://papers.neurips.cc/paper_files/paper/2019/file/5103c3584b063c431bd1268e9b5e76fb-Paper.pdf" target="_blank" rel="noreferrer">共形分位回归</a><a href="https://arxiv.org/abs/1704.02030" target="_blank" rel="noreferrer">预测分布 stacking</a><a href="https://kaybrodersen.github.io/publications/Brodersen_2015_AOAS.pdf" target="_blank" rel="noreferrer">事件的结构时序建模</a><a href="https://otext.robjhyndman.com/publications/mint/" target="_blank" rel="noreferrer">分组预测协调</a></div>
          </section>
        </TabsContent>
      </Tabs>

      <footer><span>公开研究原型 v0.2 · 仅用于风险比较，不构成录取保证</span><span>目标：正常统考录取初试成绩 P10（当前多数为透明代理）</span></footer>
    </main>
  );
}
