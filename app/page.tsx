"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUpRight,
  BarChart3,
  BookOpenCheck,
  Database,
  Gauge,
  Info,
  Search,
  ShieldCheck,
  Sparkles,
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

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><BarChart3 size={18} /></div>
        <div className="brand-copy">
          <strong>应用统计择校风险实验室</strong>
          <span>025200 · 全日制 · 985/211 首版</span>
        </div>
        <div className="topbar-meta">
          <Badge className="live-badge">2027 预测</Badge>
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
          <TabsTrigger value="method">模型方法</TabsTrigger>
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
            <div className="panel-head"><div><span className="eyebrow">ROLLING ORIGIN · 2024—2026</span><h2>复杂模型没有战胜简单基准，所以让回测决定权重</h2></div><BookOpenCheck size={28} /></div>
            <div className="metric-row">
              <Metric label="主模型 MAE" value={`${backtest.mae} 分`} note={`${backtest.rows} 条逐年外推`} />
              <Metric label="上一年基准 MAE" value={`${backtest.last_year_baseline_mae} 分`} note="当前点预测锚点" />
              <Metric label="复杂候选 MAE" value={`${backtest.complex_candidate_mae} 分`} note="未取得领先" />
              <Metric label="低估率" value={`${Math.round(backtest.underprediction_rate * 100)}%`} note="低估代价按 3×" />
            </div>
            <div className="evidence-grid">
              <div className="method-card"><span>01</span><h3>严格时间切分</h3><p>预测某一年时只使用此前年份的数据；动态特征全部滞后，避免把当年结果偷渡进输入。</p></div>
              <div className="method-card"><span>02</span><h3>点预测服从证据</h3><p>上一年 Q10 代理经国家线平移后的误差更小，因此点预测权重为 1；复杂模型保留在尾部与解释层。</p></div>
              <div className="method-card"><span>03</span><h3>保守上界再校准</h3><p>用滚动残差的 80/90/95 分位校准上界；本版 90% 残差加成约 {meta.calibrationOffsets.q90} 分。</p></div>
            </div>
            <div className="warning-line"><AlertTriangle size={16} /> 当前 P10 多为代理标签，回测评估的是“代理目标可预测性”，不是最终录取概率的临床式校准。</div>
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
            <div className="panel-head"><div><span className="eyebrow">MODEL CARD</span><h2>基本面、事件冲击、市场反转、竞校溢出</h2></div><BarChart3 size={28} /></div>
            <div className="flow-grid">
              <div><span>输入层</span><strong>国家线 · 历史线 · 招生人数 · 热冷异常 · 竞校</strong><p>所有报名时点不可见字段均滞后或移除。</p></div>
              <ArrowDown className="flow-arrow" />
              <div><span>结构层</span><strong>分层贝叶斯动态模型 + 梯度提升分位数</strong><p>院校层级部分池化，树模型捕捉非线性。</p></div>
              <ArrowDown className="flow-arrow" />
              <div><span>决策层</span><strong>回测择优锚点 + 三情景事件 + 保守校准</strong><p>输出 P50/P80/P90/P95 和冲稳保标签。</p></div>
            </div>
            <div className="formula-card"><code>所需分数 = 国家线 + 院校层级 + 动态基本面 + 市场反转 + 竞校溢出 + 事件冲击 + ε</code><p>事件冲击不是拍成单点，而是“退潮 / 中性 / 涌入”离散分布；尚未发现公告的学校额外加入未知事件厚尾噪声。</p></div>
          </section>
        </TabsContent>
      </Tabs>

      <footer><span>研究原型 v1 · 仅用于风险比较，不构成录取保证</span><span>目标：正常统考录取初试成绩 P10（第一版为透明代理）</span></footer>
    </main>
  );
}
