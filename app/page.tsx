"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUpRight,
  BarChart3,
  BookOpenCheck,
  Calculator,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Database,
  FileSearch,
  Gauge,
  GitBranch,
  Info,
  Layers3,
  MapPinned,
  Network,
  Search,
  Scale,
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
import { SchoolCoordinateMap } from "@/components/school-coordinate-map";
import forecastData from "./data/forecast.json";
import modelV5Audit from "./data/model-v5-audit.json";

type EventScenario = {
  type: string;
  name: string;
  severity: string;
  source: string;
  status: string;
  scenarios: { withdrawal: number; neutral: number; crowd: number };
};

type QuotaInfo = {
  regular: number | null;
  lower: number | null;
  upper: number | null;
  age: number | null;
  quality: number | null;
  sourceYear: number | null;
  status: string;
  sourceUrl: string | null;
  sourceTitle: string | null;
};

type Prediction = {
  school: string;
  is985: boolean;
  zone: string;
  faction: string;
  factionSource: string;
  unit: string | null;
  english: string | null;
  math: string | null;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  locationMatchedName: string | null;
  locationPrecision: string | null;
  locationSource: string | null;
  locationSourceUrl: string | null;
  locationReviewStatus: string | null;
  officeHub: string | null;
  officeHubLatitude: number | null;
  officeHubLongitude: number | null;
  officeHubDefinition: string | null;
  officeHubReviewStatus: string | null;
  transitMode: string | null;
  transitLines: string | null;
  transitSummary: string | null;
  transitReviewStatus: string | null;
  liveRouteUrl: string | null;
  routeSource: string | null;
  latestCutoff: number | null;
  latestQ10Proxy: number | null;
  quota: QuotaInfo;
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
  rawQ50: number;
  rawQ90: number;
  rawUpperWidth: number;
  robustUpperWidth: number;
  upperWidthStatus: "information_limited" | "decision_informative";
  upperWidthWarning: string | null;
  calibrationScale: number;
  nationalLineMedian: number;
  nationalLineQ90: number;
  lagSurpriseZ: number | null;
  peerPressure: number | null;
  events: EventScenario[];
  eventCoverage: string;
  selectedModel: string;
  decomposition: Record<string, number>;
};

type BacktestRow = {
  school: string;
  year: number;
  actual: number;
  pred_q50: number;
  pred_q80: number;
  pred_q90: number;
  pred_q95: number;
  weight: number;
};

type NationalLinePoint = { A: number; B: number };

type NationalLineHistory = {
  values: Record<string, NationalLinePoint>;
  sources: Record<string, string>;
};

const predictions = forecastData.predictions as Prediction[];
const meta = forecastData.meta;
const backtestRows = forecastData.backtestRows as BacktestRow[];
const nationalLineHistory = forecastData.nationalLineHistory as NationalLineHistory;
const v5 = modelV5Audit;

const factionOptions = ["纯贾", "纯茆", "贾茆", "茆Pro", "贾茆Pro", "待核实"];

function factionTone(value: string) {
  return {
    "纯贾": "pure-jia",
    "纯茆": "pure-mao",
    "贾茆": "jia-mao",
    "茆Pro": "mao-pro",
    "贾茆Pro": "jia-mao-pro",
  }[value] ?? "pending";
}

const pipelineSteps = [
  {
    id: "collect",
    code: "01",
    title: "收集证据",
    short: "官网与历史结果",
    plain: "先把每所学校过去发生过什么收齐：复试线、逐人名单、招生人数、考试科目和官方公告。每个数字都要能追溯到来源。",
    technical: "抓取并标准化院校—年份面板；公开材料保留字段级 URL 与图像审计记录，逐人原表只留在本地私有层，不把网页文本直接当成可训练数值。",
    input: "招生目录、复试名单、拟录取名单、学院公告",
    output: "带年份、口径和来源链接的原始记录",
    guardrail: "只使用报名开始前已经公开的信息",
  },
  {
    id: "audit",
    code: "02",
    title: "统一口径",
    short: "排除混入样本",
    plain: "把专项计划、非全日制、调剂生等不属于目标人群的记录排除；其余成绩按“精确、软证据、诊断”分工，而不是一删了之。",
    technical: "定义正常统考全日制025200样本；执行名单人数、最低分、中位数、最高分与图例一致性规则。对账通过者形成精确 Q10，内部一致但未闭环者只降权进入形状敏感性，状态不明者仅描述复试队列。",
    input: "原始记录与招生口径",
    output: "精确标签、软证据、诊断数据和人工复核队列",
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
    technical: "比较稳健边际分锚点、上一年锚点、部分池化动态回归与梯度提升分位数；逐人层另外比较全国池化形状、同校滞后形状和软证据混合形状。",
    input: "同一套无泄漏特征",
    output: "多个候选点预测和概率分布",
    guardrail: "点预测与分布形状分别过门禁；微小增益落入简约等价带时选择更简单模型",
  },
  {
    id: "backtest",
    code: "05",
    title: "逐年回测",
    short: "模拟真实报名时点",
    plain: "假装自己回到2024、2025、2026年报名之前，只用更早的数据预测，再和后来真实结果比较。",
    technical: "采用 expanding-window rolling origin；逐人数量只改善校年内分布，不冒充独立时间起点。中心看 MAE，形状看分位损失，概率同时看覆盖率、WIS 与区间宽度。",
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
    output: "原始分布、事件情景与稳健安全上界",
    guardrail: "未发现公告不等于确认没有事件",
  },
  {
    id: "decision",
    code: "07",
    title: "个人决策",
    short: "把分布翻译成冲稳保",
    plain: "最后才把你的估分放进学校的预测分布，计算达到目标所需分数的把握度，并按统一阈值给出冲、观察、稳、保。",
    technical: "对分位锚点分段插值形成个人覆盖概率；稳≥90%、保≥95%，同时展示证据完备度与主要不确定性来源。",
    input: "你的悲观估分与学校概率分布",
    output: "P50/P80/P90/P95、把握度和风险标签",
    guardrail: "这是学校间风险比较，不是个人录取保证",
  },
] as const;

const accuracyRoadmap = [
  { priority: "已完成", title: "考生级精确 Q10", impact: "已验证", status: "77 个校年 · 2,312 人", why: "逐人名单通过人口口径与汇总对账后替代代理标签；54 个精确回测校年的 MAE 从 15.83 降至 14.90 分。" },
  { priority: "已完成", title: "分布形状门禁", impact: "已验证", status: "同校滞后形状胜出", why: "同校上一期分布把形状 MAE 从 6.05 降至 5.73；软证据只再改善约 0.001 分，落入简约等价带，未被强行晋级。" },
  { priority: "P0", title: "报名时可见的统考名额", impact: "最高", status: "候选已接入 · 覆盖不足暂不上线", why: "区分总计划、推免和普通统考名额，避免用最终录取人数造成信息泄漏；当前严格名额只覆盖2.21%的滚动回测行。" },
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
  // The fitted distribution is only supported between P05 and P95.  Do not
  // manufacture 1%-99% probabilities with an arbitrary 180-point tail scale.
  if (score <= anchors[0][0]) return 0.05;
  if (score >= anchors.at(-1)![0]) return 0.95;
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

function probabilityLabel(item: Prediction, score: number, probability: number) {
  if (item.upperWidthStatus === "information_limited") return "不宜精算";
  if (score <= item.q05) return "≤5%";
  if (score >= item.q95) return "≥95%";
  return `约${Math.round(probability * 100)}%`;
}

function riskLabel(probability: number, informationLimited = false) {
  if (informationLimited) return { label: "证据不足", tone: "watch" };
  if (probability >= 0.95) return { label: "保", tone: "safe" };
  if (probability >= 0.9) return { label: "稳", tone: "steady" };
  if (probability >= 0.6) return { label: "观察", tone: "watch" };
  return { label: "冲", tone: "reach" };
}

function signed(value: number | null) {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function weightedMean(values: Array<{ value: number; weight: number }>) {
  const denominator = values.reduce((sum, item) => sum + item.weight, 0);
  return denominator ? values.reduce((sum, item) => sum + item.value * item.weight, 0) / denominator : 0;
}

function yearlyBacktestSummary(rows: BacktestRow[]) {
  return Array.from(new Set(rows.map((row) => row.year))).sort().map((year) => {
    const group = rows.filter((row) => row.year === year);
    const mae = weightedMean(group.map((row) => ({ value: Math.abs(row.actual - row.pred_q50), weight: row.weight || 1 })));
    const q90 = weightedMean(group.map((row) => ({ value: row.actual <= row.pred_q90 ? 1 : 0, weight: row.weight || 1 })));
    const q95 = weightedMean(group.map((row) => ({ value: row.actual <= row.pred_q95 ? 1 : 0, weight: row.weight || 1 })));
    return { year, mae, q90, q95, rows: group.length };
  });
}

function linePoints(values: number[], width: number, height: number, min: number, max: number) {
  const x = (index: number) => (values.length === 1 ? width / 2 : (index / (values.length - 1)) * width);
  const y = (value: number) => height - ((value - min) / Math.max(1, max - min)) * height;
  return values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
}

function NationalLineChart() {
  const years = Object.keys(nationalLineHistory.values).map(Number).sort((a, b) => a - b);
  const historicalA = years.map((year) => nationalLineHistory.values[String(year)].A);
  const historicalB = years.map((year) => nationalLineHistory.values[String(year)].B);
  const forecastA = meta.nationalLineForecast.A;
  const forecastB = meta.nationalLineForecast.B;
  const allValues = [...historicalA, ...historicalB, forecastA.q90, forecastB.q90];
  const min = Math.floor((Math.min(...allValues) - 8) / 10) * 10;
  const max = Math.ceil((Math.max(...allValues) + 8) / 10) * 10;
  const chartWidth = 720;
  const chartHeight = 220;
  const step = chartWidth / years.length;
  const xAt = (index: number) => index * step;
  const yAt = (value: number) => chartHeight - ((value - min) / Math.max(1, max - min)) * chartHeight;
  const ticks = [min, Math.round((min + max) / 2 / 10) * 10, max];

  return (
    <div className="theory-chart-card">
      <div className="theory-chart-head">
        <div><span className="eyebrow">共同波动 · 2017—2027</span><h3>先把国家线从学校差异中剥离</h3></div>
        <span className="chart-question">回答：为什么不能直接平均历年总分？</span>
      </div>
      <p className="chart-explanation">A/B 区国家线是所有学校共同受到的年度冲击。模型先预测它，再在相对边际分上学习学校之间的差异；虚线是 2027 年预测，阴影区表示国家线自身的不确定性。</p>
      <div className="line-chart-wrap">
        <svg viewBox={`0 0 ${chartWidth + 56} ${chartHeight + 54}`} role="img" aria-label="2017至2027年应用统计国家线A区和B区历史及预测">
          <title>国家线共同波动：历史实线，2027 年虚线与预测区间</title>
          <g transform="translate(46,10)">
            {ticks.map((tick) => <g key={tick}><line x1="0" x2={chartWidth} y1={yAt(tick)} y2={yAt(tick)} className="chart-grid" /><text x="-10" y={yAt(tick) + 4} className="chart-axis-label" textAnchor="end">{tick}</text></g>)}
            <polygon points={`${xAt(years.length - 1)},${yAt(forecastA.q90)} ${chartWidth},${yAt(forecastA.q90)} ${chartWidth},${yAt(forecastA.q50)} ${xAt(years.length - 1)},${yAt(forecastA.q50)}`} className="forecast-band" />
            <polygon points={`${xAt(years.length - 1)},${yAt(forecastB.q90)} ${chartWidth},${yAt(forecastB.q90)} ${chartWidth},${yAt(forecastB.q50)} ${xAt(years.length - 1)},${yAt(forecastB.q50)}`} className="forecast-band-b" />
            <polyline points={linePoints(historicalA, chartWidth - step, chartHeight, min, max)} className="line-a" transform={`translate(0,0)`} />
            <polyline points={linePoints(historicalB, chartWidth - step, chartHeight, min, max)} className="line-b" transform={`translate(0,0)`} />
            <line x1={xAt(years.length - 1)} x2={chartWidth} y1={yAt(historicalA.at(-1) ?? 0)} y2={yAt(forecastA.q50)} className="forecast-line-a" />
            <line x1={xAt(years.length - 1)} x2={chartWidth} y1={yAt(historicalB.at(-1) ?? 0)} y2={yAt(forecastB.q50)} className="forecast-line-b" />
            {historicalA.map((value, index) => <circle key={`a-${years[index]}`} cx={xAt(index)} cy={yAt(value)} r="3.5" className="dot-a"><title>{years[index]} A区：{value}分</title></circle>)}
            {historicalB.map((value, index) => <circle key={`b-${years[index]}`} cx={xAt(index)} cy={yAt(value)} r="3.5" className="dot-b"><title>{years[index]} B区：{value}分</title></circle>)}
            <circle cx={chartWidth} cy={yAt(forecastA.q50)} r="4.5" className="forecast-dot-a"><title>2027 A区中位预测：{forecastA.q50.toFixed(1)}分，P90：{forecastA.q90.toFixed(1)}分</title></circle>
            <circle cx={chartWidth} cy={yAt(forecastB.q50)} r="4.5" className="forecast-dot-b"><title>2027 B区中位预测：{forecastB.q50.toFixed(1)}分，P90：{forecastB.q90.toFixed(1)}分</title></circle>
            {years.filter((year, index) => index === 0 || index === years.length - 1).map((year) => <text key={year} x={xAt(years.indexOf(year))} y={chartHeight + 25} className="chart-axis-label" textAnchor="middle">{year}</text>)}
            <text x={chartWidth} y={chartHeight + 25} className="chart-axis-label forecast-year" textAnchor="middle">2027 预测</text>
          </g>
        </svg>
      </div>
      <div className="chart-legend"><span><i className="legend-line a" />A区历史</span><span><i className="legend-line b" />B区历史</span><span><i className="legend-line forecast" />2027 中心</span><small>阴影为各区 P50—P90；国家线来源：教育部历年官方发布；预测标准差 {meta.nationalLineForecast.A.sigma.toFixed(1)} 分</small></div>
    </div>
  );
}

function DecompositionChart({ item }: { item: Prediction }) {
  const labels: Array<{ key: string; label: string; detail: string }> = [
    { key: "national_line", label: "国家线", detail: "共同波动" },
    { key: "school_and_static", label: "学校/静态", detail: "985、分区、科目" },
    { key: "dynamic_baseline", label: "历史动态", detail: "历史边际分" },
    { key: "market_reversal", label: "市场反转", detail: "上一年冷热" },
    { key: "peer_spillover", label: "竞校溢出", detail: "相近学校" },
    { key: "quota_supply", label: "名额", detail: "严格时点" },
    { key: "event_expected", label: "事件", detail: "三情景期望" },
    { key: "ensemble_delta", label: "尾部/回退", detail: "复杂模型差异" },
  ];
  const values = labels.map((entry) => item.decomposition[entry.key] ?? 0);
  let running = values[0];
  const steps = [{ ...labels[0], value: values[0], from: 0, to: values[0], anchor: true }];
  labels.slice(1).forEach((entry, index) => {
    const value = values[index + 1];
    const from = running;
    running += value;
    steps.push({ ...entry, value, from, to: running, anchor: false });
  });
  const finalValue = item.q50;
  const all = [0, ...steps.flatMap((step) => [step.from, step.to]), finalValue];
  const min = Math.floor((Math.min(...all) - 6) / 10) * 10;
  const max = Math.ceil((Math.max(...all) + 6) / 10) * 10;
  const width = 760;
  const height = 245;
  const plotTop = 22;
  const plotHeight = 154;
  const y = (value: number) => plotTop + (1 - (value - min) / Math.max(1, max - min)) * plotHeight;
  const baseline = y(0);
  const slot = width / (steps.length + 1);

  return (
    <div className="theory-chart-card">
      <div className="theory-chart-head">
        <div><span className="eyebrow">选中院校 · 加法分解</span><h3>{item.school} 的 P50 是怎样拼出来的？</h3></div>
        <span className="chart-question">回答：每一项信号改变了多少分？</span>
      </div>
      <p className="chart-explanation">从国家线开始，沿着每一个已定义的模型项累加到最终 P50。正值把门槛推高，负值把门槛拉低；这是一张“解释预测组成”的桥图，不是因果效应证明。</p>
      <div className="waterfall-wrap">
        <svg viewBox={`0 0 ${width} ${height + 48}`} role="img" aria-label={`${item.school}预测中位数的分解桥图`}>
          <title>{item.school}：国家线、历史动态、市场反转、竞校溢出、名额、事件和尾部回退共同组成 P50</title>
          <line x1="0" x2={width} y1={baseline} y2={baseline} className="chart-zero" />
          <text x="0" y={baseline - 6} className="chart-axis-label">0</text>
          {[min, Math.round((min + max) / 2 / 10) * 10, max].map((tick) => <g key={tick}><line x1="0" x2={width} y1={y(tick)} y2={y(tick)} className="chart-grid" /><text x="-7" y={y(tick) + 4} className="chart-axis-label" textAnchor="end">{tick}</text></g>)}
          {steps.map((step, index) => {
            const center = slot * (index + 0.72);
            const barWidth = Math.min(52, slot * 0.58);
            const top = step.anchor ? y(step.to) : y(Math.max(step.from, step.to));
            const bottom = step.anchor ? baseline : y(Math.min(step.from, step.to));
            return <g key={step.key}>
              <rect x={center - barWidth / 2} y={top} width={barWidth} height={Math.max(2, bottom - top)} rx="4" className={step.anchor ? "bridge-anchor" : step.value >= 0 ? "bridge-positive" : "bridge-negative"}>
                <title>{step.label}：{step.value >= 0 ? "+" : ""}{step.value.toFixed(1)} 分；{step.detail}</title>
              </rect>
              {!step.anchor && <line x1={center - slot * 0.5} x2={center - barWidth / 2} y1={y(step.from)} y2={y(step.from)} className="bridge-connector" />}
              <text x={center} y={top - 7} className="bridge-value" textAnchor="middle">{step.anchor ? step.value.toFixed(1) : `${step.value >= 0 ? "+" : ""}${step.value.toFixed(1)}`}</text>
              <text x={center} y={height - 20} className="bridge-label" textAnchor="middle">{step.label}</text>
              <text x={center} y={height - 6} className="bridge-detail" textAnchor="middle">{step.detail}</text>
            </g>;
          })}
          <g>
            <rect x={width - slot * 0.28} y={y(finalValue)} width={Math.min(56, slot * 0.62)} height={Math.max(2, baseline - y(finalValue))} rx="4" className="bridge-final" />
            <text x={width - slot * 0.28 + Math.min(56, slot * 0.62) / 2} y={y(finalValue) - 7} className="bridge-value" textAnchor="middle">P50 {Math.round(finalValue)}</text>
            <text x={width - slot * 0.28 + Math.min(56, slot * 0.62) / 2} y={height - 20} className="bridge-label" textAnchor="middle">最终门槛</text>
            <text x={width - slot * 0.28 + Math.min(56, slot * 0.62) / 2} y={height - 6} className="bridge-detail" textAnchor="middle">{item.selectedModel.includes("锚") ? "稳健锚点" : "复杂回退"}</text>
          </g>
        </svg>
      </div>
      <div className="chart-legend"><span><i className="legend-box anchor" />起点/终点</span><span><i className="legend-box positive" />推高门槛</span><span><i className="legend-box negative" />拉低门槛</span><small>分解和约等于 P50（四舍五入可能有 0.1 分差异）</small></div>
    </div>
  );
}

function BacktestEvidenceChart() {
  const summary = yearlyBacktestSummary(backtestRows);
  const maxMae = Math.max(...summary.map((row) => row.mae), 1);
  return (
    <div className="backtest-evidence">
      <div className="backtest-evidence-head"><div><span className="eyebrow">样本外验证 · expanding window</span><h3>每一年都只用当时已经知道的资料</h3></div><span className="chart-question">回答：复杂模型真的更好吗？</span></div>
      <p className="chart-explanation">2024 预测只看更早年份，2025 再向前扩展，2026 继续扩展。下图同时展示中位数预测误差和 P90 覆盖率；上线不看某一个漂亮指标，而看误差、覆盖和稳定性是否一起过线。</p>
      <div className="backtest-years">
        {summary.map((row) => <div className="backtest-year" key={row.year}>
          <div className="backtest-year-head"><strong>{row.year}</strong><span>{row.rows} 条</span></div>
          <div className="backtest-bar-line"><span>MAE</span><div className="backtest-bar-track"><i style={{ width: `${(row.mae / maxMae) * 100}%` }} /></div><b>{row.mae.toFixed(1)}</b></div>
          <div className="backtest-bar-line coverage"><span>P90</span><div className="backtest-bar-track"><i style={{ width: `${row.q90 * 100}%` }} /></div><b>{Math.round(row.q90 * 100)}%</b></div>
          <small>P95 覆盖 {Math.round(row.q95 * 100)}%</small>
        </div>)}
      </div>
      <div className="backtest-callout"><Scale size={16} /><span><strong>当前生产选择：</strong>稳健边际锚点 MAE {meta.backtest.robust_margin_anchor_mae} 分，优于上一年锚点 {meta.backtest.last_year_baseline_mae} 分和复杂候选 {meta.backtest.complex_candidate_mae} 分；因此复杂模型暂不替代透明基线。</span></div>
    </div>
  );
}

function EvidenceUtilisationChart() {
  const scoreRows = v5.scoreRows;
  const outcomeRows = [
    { label: "已录取", value: scoreRows.admitted, tone: "admitted", note: "进入拟录取分布分层" },
    { label: "明确未录取", value: scoreRows.notAdmitted, tone: "rejected", note: "用于复试选择梯度" },
    { label: "结果未知", value: scoreRows.unknownOutcome, tone: "unknown", note: "只描述复试池，不伪造标签" },
  ];
  const admittedRows = [
    { label: "精确层", value: scoreRows.exactAdmitted, tone: "exact", note: "直接计算校年 Q10" },
    { label: "软证据层", value: scoreRows.softAdmitted, tone: "soft", note: "只进入形状敏感性" },
    { label: "诊断层", value: scoreRows.diagnosticAdmitted, tone: "diagnostic", note: "口径复核与异常发现" },
  ];

  return (
    <div className="evidence-utilisation">
      <div className="evidence-utilisation-head">
        <div><span className="eyebrow">14,317 条可读成绩如何被使用</span><h3>不是“通过就留、失败就扔”，而是按证据强度分配统计角色</h3></div>
        <span className="chart-question">60 条完全重复记录只计一次；逐人原表不公开</span>
      </div>
      <div className="evidence-source-node"><Database size={18} /><div><strong>{scoreRows.raw.toLocaleString("zh-CN")}</strong><span>原始可读初试总分</span></div><small>{scoreRows.uniqueValid.toLocaleString("zh-CN")} 条去重有效记录</small></div>
      <ArrowDown className="evidence-down" aria-hidden="true" />
      <div className="evidence-outcome-grid">
        {outcomeRows.map((row) => (
          <div className={`evidence-outcome ${row.tone}`} key={row.label}>
            <span>{row.label}</span><strong>{row.value.toLocaleString("zh-CN")}</strong><small>{row.note}</small>
            <i style={{ width: `${(row.value / scoreRows.raw) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="evidence-branch-label"><span>已录取 9,073 条继续按可审计程度分层</span><i /></div>
      <div className="evidence-tier-grid">
        {admittedRows.map((row) => (
          <div className={`evidence-tier ${row.tone}`} key={row.label}>
            <div><span>{row.label}</span><strong>{row.value.toLocaleString("zh-CN")}</strong></div><small>{row.note}</small>
          </div>
        ))}
      </div>
      <p className="evidence-utilisation-note">同一条记录可承担不同但不冲突的角色：已录取成绩描述拟录取分布；图例明确的录取与未录取成绩还可描述复试选择梯度。任何报名后结果都不能作为同年报名前预测特征。</p>
    </div>
  );
}

function EstimandAndVarianceDiagram() {
  const shares = v5.varianceShares;
  return (
    <div className="estimand-panel">
      <div className="estimand-flow" role="list" aria-label="已实现分布、低位分位数与未来门槛分布的区别">
        <article role="listitem"><span>校年内部样本</span><strong>F<sup>adm</sup><sub>s,t</sub></strong><p>某校某年已经录取者的逐人初试分分布。逐人数据直接改善这一层。</p></article>
        <ChevronRight aria-hidden="true" />
        <article role="listitem"><span>研究目标</span><strong>T<sub>s,t</sub> = Q<sub>0.10</sub>(F<sup>adm</sup><sub>s,t</sub>)</strong><p>从该分布提取低位分数。77 个精确校年仍有有限样本误差。</p></article>
        <ChevronRight aria-hidden="true" />
        <article role="listitem"><span>报名前未知量</span><strong>G<sub>s,t</sub> = P(T<sub>s,t</sub> ≤ x | I<sub>t−</sub>)</strong><p>未来门槛的预测分布。它的独立信息单位仍是校年，而不是考生人数。</p></article>
      </div>
      <div className="variance-panel">
        <div className="variance-copy"><span className="eyebrow">三层方差分解</span><h4>全国混合分布的差异从哪里来？</h4><p>逐人数据同时揭示“同一校年内学生不同”“同校跨年变化”和“学校之间不同”。三者不能混成一个全国标准差。</p></div>
        <div className="variance-visual" aria-label="校年内46.1%，同校跨年10.9%，学校间43.0%">
          <div className="variance-bar"><i className="within" style={{ width: `${shares.withinSchoolYear * 100}%` }} /><i className="across" style={{ width: `${shares.sameSchoolAcrossYears * 100}%` }} /><i className="between" style={{ width: `${shares.betweenSchools * 100}%` }} /></div>
          <div className="variance-legend"><span><i className="within" />校年内个体差异 <b>46.1%</b></span><span><i className="across" />同校跨年 <b>10.9%</b></span><span><i className="between" />院校间 <b>43.0%</b></span></div>
        </div>
      </div>
    </div>
  );
}

function V5ResearchGatePanel() {
  const exact = v5.exactLabelBacktest;
  const shape = v5.shapeGate;
  const selection = v5.selectionGradient;
  return (
    <div className="research-gates">
      <article className="research-gate pass"><div><CheckCircle2 size={17} /><span>通过 · 标签替换</span></div><strong>{exact.frozenBaselineMae.toFixed(2)} → {exact.exactEnhancedMae.toFixed(2)}</strong><p>54 个精确校年 P50 MAE；年份等权差 {exact.yearBlockDifference.toFixed(2)} 分，90% 年份分块区间 [{exact.bootstrapP05.toFixed(2)}, {exact.bootstrapP95.toFixed(2)}]。</p></article>
      <article className="research-gate pass"><div><CheckCircle2 size={17} /><span>通过 · 分布形状</span></div><strong>{shape.pooledExactMae.toFixed(2)} → {shape.lagExactMae.toFixed(2)}</strong><p>同校上一期形状优于全国池化形状，因此晋级为 V5 实验分布的形状来源。</p></article>
      <article className="research-gate hold"><div><Scale size={17} /><span>保留 · 软证据</span></div><strong>额外改善 {shape.softIncrementalGain.toFixed(3)} 分</strong><p>{shape.reason}</p></article>
      <article className="research-gate reject"><div><AlertTriangle size={17} /><span>拒绝 · 复试选择特征</span></div><strong>{selection.anchorMae.toFixed(2)} → {selection.candidateMae.toFixed(2)}</strong><p>{selection.reason}</p></article>
      <div className="research-freeze-note"><ShieldCheck size={17} /><span><strong>前瞻冻结没有被回溯实验覆盖。</strong>上述通过仅说明值得进入下一版独立前瞻候选；2027 网页排名与 P50/P90 数值仍来自 2026-10-08 冻结的 v0.2 基线。</span></div>
    </div>
  );
}

type TheoryPanelProps = {
  selected: Prediction;
  score: number;
  selectedProbability: number;
  selectedRisk: { label: string; tone: string };
  pipelineStepId: (typeof pipelineSteps)[number]["id"];
  onPipelineStepChange: (id: (typeof pipelineSteps)[number]["id"]) => void;
  liveExample: string;
};

function ModelTheoryPanel({ selected, score, selectedProbability, selectedRisk, pipelineStepId, onPipelineStepChange, liveExample }: TheoryPanelProps) {
  const activePipelineStep = pipelineSteps.find((step) => step.id === pipelineStepId) ?? pipelineSteps[0];
  const decisionThreshold = selectedProbability >= 0.95 ? "保" : selectedProbability >= 0.9 ? "稳" : selectedProbability >= 0.6 ? "观察" : "冲";
  const decompositionTotal = Object.values(selected.decomposition).reduce((sum, value) => sum + value, 0);
  const uncertaintyWidth = selected.q90 - selected.q50;

  return (
    <section className="wide-panel panel theory-panel">
      <div className="panel-head theory-hero-head">
        <div><span className="eyebrow">MODEL THEORY · PAPER TO PRODUCT</span><h2>模型原理：先预测门槛，再翻译成决策</h2><p className="theory-lead">这不是把一堆图放在网页上，而是把论文中的每一次数学变换都对应到一个可检查的问题：数据是什么、模型算了什么、结果能支持什么。</p></div>
        <div className="theory-status"><span>信息截点</span><strong>{meta.asOf}</strong><small>报名开始前可见信息</small></div>
      </div>

      <div className="theory-contract-grid">
        <article className="theory-contract target"><span className="contract-number">01</span><div><strong>预测对象</strong><h3>普通统考拟录取初试成绩 Q10</h3><p>不是复试线，也不是个人录取概率。77 个校年由逐名成绩直接计算，其余年份仍使用方法可追溯的代理标签。</p></div></article>
        <article className="theory-contract information"><span className="contract-number">02</span><div><strong>可用信息</strong><h3>报名开始前的时间截点</h3><p>所有动态变量至少滞后一年；当年最终录取人数、当年热度等报名后信息不能倒灌进输入。</p></div></article>
        <article className="theory-contract decision"><span className="contract-number">03</span><div><strong>决策输出</strong><h3>P50 / P80 / P90 / P95</h3><p>把估分放进门槛分布，得到“覆盖门槛”的概率；“稳”是概率标签，不是录取保证。</p></div></article>
      </div>

      <section className="theory-section">
        <div className="section-title-row"><div><span className="eyebrow">01 · 计算链</span><h3>从原始证据到一个可解释的 P90</h3></div><span className="section-note">每个箭头都是一次有约束的数据变换</span></div>
        <div className="model-flow" role="list" aria-label="模型从证据到决策的计算链">
          <div className="model-flow-node evidence" role="listitem"><span className="flow-index">A</span><strong>报名时可见证据</strong><small>成绩名单 · 国家线 · 目录 · 名额 · 公告</small></div>
          <ArrowDown className="flow-arrow" aria-hidden="true" />
          <div className="model-flow-node target" role="listitem"><span className="flow-index">B</span><strong>证据分层与目标</strong><small>精确 Q10 · 软证据 · 诊断数据 · 代理</small></div>
          <ArrowDown className="flow-arrow" aria-hidden="true" />
          <div className="model-flow-node feature" role="listitem"><span className="flow-index">C</span><strong>相对国家线特征</strong><small>边际分、冷热反转、竞校溢出、事件</small></div>
          <ArrowDown className="flow-arrow" aria-hidden="true" />
          <div className="model-flow-node inference" role="listitem"><span className="flow-index">D</span><strong>中心 + 不确定性</strong><small>稳健锚点 · 贝叶斯候选 · 分位数尾部</small></div>
          <ArrowDown className="flow-arrow" aria-hidden="true" />
          <div className="model-flow-node decision" role="listitem"><span className="flow-index">E</span><strong>个人决策</strong><small>覆盖概率 → 冲 / 观察 / 稳 / 保</small></div>
        </div>
      </section>

      <section className="theory-section math-section">
        <div className="section-title-row"><div><span className="eyebrow">02 · 逐人数据的统计角色</span><h3>先分清三个分布，再决定每条成绩能做什么</h3></div><span className="section-note">逐人样本增加校年内部信息，不增加独立年份</span></div>
        <EvidenceUtilisationChart />
        <EstimandAndVarianceDiagram />
      </section>

      <section className="theory-section math-section">
        <div className="section-title-row"><div><span className="eyebrow">03 · 数学原理</span><h3>五个公式分别解决五个不同问题</h3></div><span className="section-note">先看公式，再看它在页面哪一处产生结果</span></div>
        <div className="math-grid">
          <article className="math-card">
            <div className="math-card-head"><span>目标测量</span><CircleHelp size={15} /></div>
            <div className="math-display">Y<sub>s,t</sub> = Q<sub>0.10</sub>(A<sub>s,t</sub>)</div>
            <div className="math-mini">Q̂<sub>0.10</sub> = a + <span>(0.10 − 1/(n+1))</span>/<span>(0.50 − 1/(n+1))</span> · (b − a)</div>
            <p><b>Y</b> 是学校 s 在年份 t 的目标门槛；<b>A</b> 只保留普通统考、全日制拟录取初试成绩。缺少逐名数据时，用最低分与中位数插值，并把代理方法写进权重。</p>
            <div className="math-foot">网页对应：数据审计 → 标签观测误差与证据完备度</div>
          </article>
          <article className="math-card">
            <div className="math-card-head"><span>相对难度</span><CircleHelp size={15} /></div>
            <div className="math-display">m<sub>s,t</sub> = Y<sub>s,t</sub> − L<sub>z,t</sub></div>
            <p><b>L</b> 是学校所在 A/B 区国家线。先建模边际分 m，可以把“全国一起涨跌”和“学校自身竞争力”分开，避免把国家线变化误判成学校变热。</p>
            <div className="math-foot">网页对应：国家线共同波动图</div>
          </article>
          <article className="math-card wide">
            <div className="math-card-head"><span>中心预测</span><CircleHelp size={15} /></div>
            <div className="math-display compact">T̂<sub>s,t</sub> = L̂<sub>z,t</sub> + median(m<sub>s,k</sub>) + Δ<sub>dynamic</sub> + Δ<sub>event</sub> + Δ<sub>tail</sub></div>
            <p>生产中心优先采用历年边际分中位数的稳健锚点；动态项描述上一年冷热与竞校迁移，事件项保留退潮 / 中性 / 涌入三种状态，尾部项承接复杂模型形状和未知风险。</p>
            <div className="math-foot">网页对应：选中院校的加法分解桥图</div>
          </article>
          <article className="math-card">
            <div className="math-card-head"><span>决策概率</span><CircleHelp size={15} /></div>
            <div className="math-display">C<sub>s,t</sub>(S) = P(T<sub>s,t</sub> ≤ S)</div>
            <p>把个人估分 S 放进预测门槛分布，得到覆盖该门槛的概率。它不包含复试表现、单科线、主观题误差和最终排名。</p>
            <div className="math-foot">网页对应：顶部估分滑杆与“稳”标签</div>
          </article>
          <article className="math-card wide model-equation-card">
            <div className="math-card-head"><span>候选模型与分布集成</span><CircleHelp size={15} /></div>
            <div className="math-display compact">m<sub>s,t</sub> = β<sub>0</sub> + u<sub>s</sub> + X<sub>s,t−1</sub>β + ε<sub>s,t</sub>，　u<sub>s</sub> ~ N(0, 18²)</div>
            <div className="math-mini">ε<sub>s,t</sub> ~ t<sub>ν</sub>(0, σ² + X′Σ<sub>β</sub>X)</div>
            <p>分层贝叶斯候选让学校效应 <b>u<sub>s</sub></b> 在共同先验下部分池化；<b>X<sub>s,t−1</sub></b> 只放滞后特征，<b>ε</b> 使用厚尾预测误差承接爆冷爆热。梯度提升分位数模型分别拟合 P50/P80/P90/P95，但本版回测没有让它替代透明锚点。</p>
            <div className="math-display compact">T = center + 0.35·noise<sub>complex</sub> + η<sub>national</sub> + E<sub>event</sub> + ε<sub>unknown</sub></div>
            <div className="math-mini">F<sub>T</sub>(x) = Σ<sub>e∈&#123;退潮、中性、涌入&#125;</sub> π<sub>e</sub> · F<sub>e</sub>(x)</div>
            <p>最终不是输出单点，而是把国家线波动、复杂候选形状、事件三情景和未知事件厚尾叠加成分布；事件状态按退潮 / 中性 / 涌入的权重混合，而不是拍脑袋加固定分。</p>
            <div className="math-foot">网页对应：回测卡片、事件情景卡片与 P50—P95 区间</div>
          </article>
        </div>
        <div className="notation-strip"><span><b>s</b> 学校</span><span><b>t</b> 招生年份</span><span><b>z</b> A / B 区</span><span><b>T</b> 未来门槛随机变量</span><span><b>q<sub>90</sub></b> 门槛分布的 90% 上界</span></div>
      </section>

      <section className="theory-section chart-section">
        <div className="section-title-row"><div><span className="eyebrow">04 · 结果如何被解释</span><h3>两个图，分别看“共同波动”和“单校差异”</h3></div><span className="section-note">图形只呈现模型已经定义的量，不增加未经验证的故事</span></div>
        <div className="theory-chart-grid"><NationalLineChart /><DecompositionChart item={selected} /></div>
      </section>

      <section className="theory-section decision-section">
        <div className="section-title-row"><div><span className="eyebrow">05 · 从分布到报名选择</span><h3>同一个学校，为什么要同时看 P50 和 P90？</h3></div><span className="section-note">低估门槛的代价被设为高估的 3 倍</span></div>
        <div className="decision-explain-grid">
          <div className="decision-prob-card"><div className="decision-score"><Calculator size={17} /><span>当前估分</span><strong>{score} 分</strong></div><div className={`decision-result ${selectedRisk.tone}`}><span>{selected.school}</span><strong>{probabilityLabel(selected, score, selectedProbability)}</strong><small>覆盖门槛的区间估计 · {decisionThreshold}</small></div><div className="decision-rule"><span>稳健 P90* = {Math.round(selected.q90)} 分</span><span>稳健 P95* = {Math.round(selected.q95)} 分</span><b>{score >= selected.q90 ? "已达到稳健 P90* 安全线" : `还差 ${Math.round(selected.q90 - score)} 分到稳健 P90*`}</b></div></div>
          <div className="uncertainty-reading"><div className="uncertainty-head"><Scale size={17} /><strong>区间宽度不是“模型不好”，而是信息不足被显式保留</strong></div><div className="uncertainty-track"><i style={{ left: `${Math.max(0, Math.min(100, ((selected.q50 - selected.q05) / Math.max(1, selected.q95 - selected.q05)) * 100))}%`, width: `${Math.max(4, Math.min(100, ((selected.q90 - selected.q50) / Math.max(1, selected.q95 - selected.q05)) * 100))}%` }} /><span className="uncertainty-marker p50" style={{ left: `${((selected.q50 - selected.q05) / Math.max(1, selected.q95 - selected.q05)) * 100}%` }}>P50 {Math.round(selected.q50)}</span><span className="uncertainty-marker p90" style={{ left: `${((selected.q90 - selected.q05) / Math.max(1, selected.q95 - selected.q05)) * 100}%` }}>P90 {Math.round(selected.q90)}</span></div><ul><li>当前 P50—P90 跨度约 <b>{Math.round(uncertaintyWidth)} 分</b>。</li><li>它包含国家线波动、历史样本不足、事件情景和未知事件厚尾。</li><li>当前考生分数被当作固定输入，个人估分不确定性尚未传播。</li></ul></div>
        </div>
        <div className="decision-warning"><AlertTriangle size={15} /><span>“稳”按<b>稳健 P90* 安全上界</b>判定。当前严格嵌套验证只有两个外层年份，因此它不是已证明具有 90% 频率保证的录取概率，也不替代招生简章、单科线和复试规则。</span></div>
      </section>

      <section className="theory-section">
        <div className="section-title-row"><div><span className="eyebrow">06 · 样本外验证</span><h3>模型能不能上线，由回测而不是复杂度决定</h3></div><span className="section-note">生产版本保留透明基线，复杂模型暂作辅助</span></div>
        <BacktestEvidenceChart />
      </section>

      <section className="theory-section pipeline-section">
        <div className="section-title-row"><div><span className="eyebrow">07 · 可交互流程</span><h3>点击任一环节，查看它的输入、输出和防错闸门</h3></div><span className="section-note">当前选中：{activePipelineStep.title}</span></div>
        <div className="pipeline-group-labels" aria-hidden="true"><span className="evidence-layer"><FileSearch size={14} />证据层 · 收集与清洗</span><span className="inference-layer"><GitBranch size={14} />推断层 · 建模与验证</span><span className="decision-layer"><ShieldCheck size={14} />决策层</span></div>
        <div className="pipeline-graph" role="list" aria-label="从数据到择校决策的七步图形流程">
          {pipelineSteps.map((step, index) => { const StepIcon = pipelineIcons[step.id]; const active = step.id === pipelineStepId; return <div className="graph-step-wrap" role="listitem" key={step.id}><button type="button" className="graph-step" data-active={active} aria-pressed={active} aria-label={`${step.title}：${step.plain}`} onClick={() => onPipelineStepChange(step.id)}><span className="graph-orb"><StepIcon size={24} aria-hidden="true" /><i>{step.code}</i></span><strong>{step.title}</strong><small>{step.short}</small></button>{index < pipelineSteps.length - 1 && <ChevronRight className="graph-connector" size={19} aria-hidden="true" />}</div>; })}
        </div>
        <div className="pipeline-feedback"><span className="feedback-path" aria-hidden="true" /><TestTube2 size={17} aria-hidden="true" /><div><strong>回测不达标，就返回数据或特征层</strong><span>复杂度不是上线理由；只有报名时点的样本外表现能让模型进入下一环。</span></div></div>
        <div className="pipeline-explainer" aria-live="polite"><div className="explain-heading"><div><span className="eyebrow">{activePipelineStep.code} · 当前环节</span><h3>{activePipelineStep.title}</h3></div><span className="technical-badge">技术说明</span></div><p className="explain-copy">{activePipelineStep.technical}</p><div className="pipeline-facts"><div><span>进入这一环</span><strong>{activePipelineStep.input}</strong></div><div><span>离开这一环</span><strong>{activePipelineStep.output}</strong></div><div><span>防错闸门</span><strong>{activePipelineStep.guardrail}</strong></div></div><div className="live-example"><CheckCircle2 size={17} aria-hidden="true" /><div><span>用当前选中院校走一遍</span><strong>{liveExample}</strong></div></div></div>
      </section>

      <section className="theory-section">
        <div className="section-title-row"><div><span className="eyebrow">08 · V5 研究门禁</span><h3>有数据不等于一定进模型：四项候选逐一判定</h3></div><span className="section-note">晋级看时间外价值；被拒绝的数据仍保留描述与复核用途</span></div>
        <V5ResearchGatePanel />
      </section>

      <section className="theory-section roadmap-section">
        <div className="roadmap-head"><div><span className="eyebrow">09 · 精度升级边界</span><h3>下一步先补数据，再决定是否增加复杂度</h3></div><p>“影响”是预期优先级，不是未经验证的分数承诺。每项优化都必须重新通过逐年滚动回测。</p></div>
        <div className="roadmap-grid">{accuracyRoadmap.map((item) => <article className="roadmap-item" key={item.title}><div><span className="roadmap-priority">{item.priority}</span><span className="roadmap-impact">影响：{item.impact}</span></div><h4>{item.title}</h4><p>{item.why}</p><small>{item.status}</small></article>)}</div>
        <div className="research-links"><span>方法依据</span><a href="https://papers.neurips.cc/paper_files/paper/2019/file/5103c3584b063c431bd1268e9b5e76fb-Paper.pdf" target="_blank" rel="noreferrer">共形分位回归</a><a href="https://arxiv.org/abs/1704.02030" target="_blank" rel="noreferrer">预测分布 stacking</a><a href="https://kaybrodersen.github.io/publications/Brodersen_2015_AOAS.pdf" target="_blank" rel="noreferrer">事件的结构时序建模</a><a href="https://otext.robjhyndman.com/publications/mint/" target="_blank" rel="noreferrer">分组预测协调</a></div>
      </section>

      <div className="theory-source-note"><Database size={14} /><span>前瞻排名读取冻结的 <code>app/data/forecast.json</code>；V5 回溯统计读取去标识的 <code>app/data/model-v5-audit.json</code>。当前生产基线仍用 {meta.trainingRows} 条历史目标，研究层另确认 {v5.scoreRows.exactProgramYears} 个精确 Q10 校年、{v5.scoreRows.exactAdmitted.toLocaleString("zh-CN")} 名精确层拟录取者。桥图分解合计 {decompositionTotal.toFixed(1)} 分，四舍五入后与选中院校 P50 对齐。</span></div>
    </section>
  );
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
    { key: "P80*", value: item.q80, tone: "watch" },
    { key: "P90*", value: item.q90, tone: "steady" },
    { key: "P95*", value: item.q95, tone: "safe" },
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
  const [faction, setFaction] = useState("all");
  const [sortBy, setSortBy] = useState("q90");
  const [pipelineStepId, setPipelineStepId] = useState<(typeof pipelineSteps)[number]["id"]>("collect");
  const defaultSchool = predictions.find((item) => item.school === "华东师范大学")?.school ?? predictions[0].school;
  const [selectedSchool, setSelectedSchool] = useState(defaultSchool);

  const rows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return predictions
      .filter((item) => !normalized || item.school.toLowerCase().includes(normalized) || item.location?.toLowerCase().includes(normalized))
      .filter((item) => tier === "all" || (tier === "985" ? item.is985 : !item.is985))
      .filter((item) => faction === "all" || item.faction === faction)
      .map((item) => ({ ...item, probability: probabilityAtScore(item, score) }))
      .sort((a, b) => {
        if (sortBy === "probability") return b.probability - a.probability;
        if (sortBy === "confidence") return b.confidenceScore - a.confidenceScore;
        return a.q90 - b.q90;
      });
  }, [faction, query, score, sortBy, tier]);

  const selected = predictions.find((item) => item.school === selectedSchool) ?? rows[0] ?? predictions[0];
  const selectedProbability = probabilityAtScore(selected, score);
  const selectedRisk = riskLabel(selectedProbability, selected.upperWidthStatus === "information_limited");
  const backtest = meta.backtest;
  const liveExample = (() => {
    if (pipelineStepId === "collect") return `${selected.school}：已形成 ${selected.historyCount} 个历史目标标签，最新复试线 ${selected.latestCutoff ?? "待核验"} 分。`;
    if (pipelineStepId === "audit") return `${selected.school} 当前前瞻证据完备度 ${selected.confidenceScore}/100；逐人记录另按精确、软证据和诊断层分配用途。`;
    if (pipelineStepId === "features") return `最近一年冷热惊讶度 ${signed(selected.lagSurpriseZ)}σ，同层竞校压力 ${signed(selected.peerPressure)}σ。`;
    if (pipelineStepId === "models") return `冻结点预测采用“${selected.selectedModel}”；V5 回溯层另外用同校上一期逐人分布估计形状。`;
    if (pipelineStepId === "backtest") return `冻结主流程滚动 MAE ${backtest.mae} 分；精确标签回溯实验在 54 个校年上由 ${v5.exactLabelBacktest.frozenBaselineMae} 降至 ${v5.exactLabelBacktest.exactEnhancedMae} 分。`;
    if (pipelineStepId === "scenarios") return `${selected.events.length ? `${selected.events.length}条官方事件进入三情景` : "未检索到官方事件，已加入未知事件厚尾"}；P90* 采用跨历史年份最不利标准化残差校准。`;
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
          <Badge className="live-badge">2027 冻结预测 · v0.2</Badge>
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

      <Tabs defaultValue="ranking" className="workspace-tabs">
        <TabsList variant="line" className="main-tabs">
          <TabsTrigger value="ranking">风险排名</TabsTrigger>
          <TabsTrigger value="map">院校地图</TabsTrigger>
          <TabsTrigger value="backtest">回测与校准</TabsTrigger>
          <TabsTrigger value="audit">数据审计</TabsTrigger>
          <TabsTrigger value="method">模型原理</TabsTrigger>
        </TabsList>

        <TabsContent value="ranking" className="tab-panel">
          <div className="main-grid">
            <section className="ranking-panel panel">
              <div className="panel-head">
                <div><span className="eyebrow">RISK RANKING</span><h1>按你的分数筛学校</h1></div>
                <span className="row-count">{rows.length} / {predictions.length} 所</span>
              </div>
              <div className="filter-row">
                <div className="search-box"><Search size={15} /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学校或城市" /></div>
                <select value={tier} onChange={(event) => setTier(event.target.value)} aria-label="院校层次"><option value="all">全部层次</option><option value="985">985</option><option value="211">非985的211</option></select>
                <select value={faction} onChange={(event) => setFaction(event.target.value)} aria-label="院校派系"><option value="all">全部派系</option>{factionOptions.map((item) => <option value={item} key={item}>{item}</option>)}</select>
                <select value={sortBy} onChange={(event) => setSortBy(event.target.value)} aria-label="排序方式"><option value="q90">按稳妥线</option><option value="probability">按把握度</option><option value="confidence">按证据完备度</option></select>
              </div>

              <div className="table-wrap">
                <table>
                  <thead><tr><th>院校</th><th>中位预测</th><th>P90*稳妥线</th><th>当前把握</th><th>标签</th></tr></thead>
                  <tbody>
                    {rows.map((item) => {
                      const risk = riskLabel(item.probability, item.upperWidthStatus === "information_limited");
                      return (
                        <tr key={item.school} data-active={item.school === selected.school} onClick={() => setSelectedSchool(item.school)}>
                          <td><strong>{item.school}</strong><span className={`faction-badge ${factionTone(item.faction)}`}>{item.faction}</span>{item.upperWidthStatus === "information_limited" && <span className="width-warning-tag">上界极宽</span>}<span>{item.is985 ? "985" : "211"} · {item.zone}区 · 证据{item.confidence}</span></td>
                          <td className="mono">{Math.round(item.q50)}</td>
                          <td className="mono emphasis">{Math.round(item.q90)}</td>
                          <td><div className="prob-cell"><span>{probabilityLabel(item, score, item.probability)}</span><Progress value={item.probability * 100} /></div></td>
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
                <div><span className="eyebrow">SELECTED SCHOOL</span><h2>{selected.school}</h2><p>{selected.unit ?? "培养单位待核验"} · {selected.math ?? "数学科目待核验"}</p><span className={`faction-badge detail-faction ${factionTone(selected.faction)}`}>{selected.faction}</span></div>
                <span className={`risk-orb ${selectedRisk.tone}`}><strong>{selectedRisk.label}</strong><small>{Math.round(selectedProbability * 100)}%</small></span>
              </div>

              <div className="confidence-banner">
                <span>证据完备度</span><strong>{selected.confidence} · {selected.confidenceScore}/100</strong>
                <Progress value={selected.confidenceScore} />
              </div>

              <ScoreRail item={selected} score={score} />

              <div className="quantile-grid">
                <Metric label="中位预测" value={`${Math.round(selected.q50)}`} note="50% 情景" />
                <Metric label="P80* 安全上界" value={`${Math.round(selected.q80)}`} note="偏稳参考" />
                <Metric label="P90* 安全上界" value={`${Math.round(selected.q90)}`} note="暂定稳妥线" />
                <Metric label="P95* 安全上界" value={`${Math.round(selected.q95)}`} note="保守参考" />
              </div>

              {selected.upperWidthStatus === "information_limited" && (
                <div className="upper-width-warning">
                  <AlertTriangle size={17} />
                  <div>
                    <strong>证据不足：稳健安全上界极宽</strong>
                    <p>P90*-P50 为 {Math.round(selected.robustUpperWidth)} 分，超过本版预先声明的 Tukey 上围栏 {meta.upperWidthGuardrail.threshold.toFixed(1)} 分；原始 P90-P50 仅 {Math.round(selected.rawUpperWidth)} 分。宽度本身表示当前无法给出有信息量的保守比较，不等同于该校真实难度高于热门院校，也不会人为裁剪上界。</p>
                  </div>
                </div>
              )}

              <div className="signal-grid">
                <div><span>上年热/冷异常</span><strong>{signed(selected.lagSurpriseZ)}σ</strong><small>{(selected.lagSurpriseZ ?? 0) > 0.8 ? "偏热，警惕次年回撤" : (selected.lagSurpriseZ ?? 0) < -0.8 ? "偏冷，警惕考生涌入" : "接近常态"}</small></div>
                <div><span>同层竞校压力</span><strong>{signed(selected.peerPressure)}σ</strong><small>相近院校上一年共同热度</small></div>
              </div>

              <div className="event-card quota-card">
                <div className="card-title"><Database size={16} /><strong>报名时可见名额</strong><span>{selected.quota.regular == null ? "尚未覆盖" : `${selected.quota.regular} 个统考名额`}</span></div>
                <p className="muted-copy">{selected.quota.status}。名额特征目前只进入候选实验，不改变生产预测。</p>
                {selected.quota.sourceUrl && <a href={selected.quota.sourceUrl} target="_blank" rel="noreferrer">查看名额公告 <ArrowUpRight size={13} /></a>}
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

        <TabsContent value="map" className="tab-panel">
          <section className="wide-panel panel map-panel-shell">
            <div className="panel-head"><div><span className="eyebrow">CAMPUS · OFFICE · COMMUTE</span><h2>校区、办公集聚区与公共交通</h2></div><MapPinned size={28} /></div>
            <p className="map-intro">81 所学校均配置培养校区点位。办公集聚区是研究用代表性节点；候选线路必须在出发前通过实时规划复核。</p>
            <div className="filter-row map-filter-row">
              <div className="search-box"><Search size={15} /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学校或城市" /></div>
              <select value={tier} onChange={(event) => setTier(event.target.value)} aria-label="地图院校层次"><option value="all">全部层次</option><option value="985">985</option><option value="211">非985的211</option></select>
              <select value={faction} onChange={(event) => setFaction(event.target.value)} aria-label="地图院校派系"><option value="all">全部派系</option>{factionOptions.map((item) => <option value={item} key={item}>{item}</option>)}</select>
              <span className="row-count map-row-count">{rows.length} / {predictions.length} 所</span>
            </div>
            <SchoolCoordinateMap items={rows} selectedSchool={selected.school} onSelect={setSelectedSchool} />
          </section>
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
              <div className="method-card"><span>03</span><h3>保守上界再校准</h3><p>用跨历史预测年份的最不利标准化残差校准学校特异上界；严格嵌套检验中 P90* 覆盖 {Math.round(meta.robustUpperBacktest.q90_coverage * 100)}%，平均 P90*-P50 宽度 {meta.robustUpperBacktest.q90_minus_q50} 分。</p></div>
            </div>
            <div className="warning-line"><AlertTriangle size={16} /> 当前低估率为 {Math.round(backtest.underprediction_rate * 100)}%。P10 多为代理标签，因此回测评估的是“代理目标可预测性”，不是最终录取概率的临床式校准。</div>

            <div className="section-title-row backtest-v5-title"><div><span className="eyebrow">V5 · EXACT LABEL RETROSPECTIVE</span><h3>逐人精确标签提高了回溯精度，但没有改写冻结预测</h3></div><span className="section-note">54 个精确校年 · 仅 3 个外层日历年</span></div>
            <V5ResearchGatePanel />
          </section>
        </TabsContent>

        <TabsContent value="audit" className="tab-panel">
          <section className="wide-panel panel">
            <div className="panel-head"><div><span className="eyebrow">DATA PROVENANCE</span><h2>先区分“有数据”和“可用于决策的数据”</h2></div><Database size={28} /></div>
            <div className="metric-row"><Metric label="字段来源覆盖" value={`${v5.sourceAudit.coreValuesWithPublicUrl.toLocaleString("zh-CN")} / ${v5.sourceAudit.coreValues.toLocaleString("zh-CN")}`} note="非空核心值附公开URL" /><Metric label="公开来源记录" value={v5.sourceAudit.publicUrlRecords.toLocaleString("zh-CN")} note="逐字段目录可复核" /><Metric label="精确 Q10 校年" value={`${v5.scoreRows.exactProgramYears} 个`} note={`${v5.scoreRows.exactSchools} 所学校`} /><Metric label="逐人精确层" value={v5.scoreRows.exactAdmitted.toLocaleString("zh-CN")} note="普通统考全日制拟录取者" /></div>
            <div className="metric-row"><Metric label="名单图像" value={`${v5.sourceAudit.rosterImages} 张`} note={`${v5.sourceAudit.parsedImages} 张已结构化解析`} /><Metric label="审计后拟录取成绩" value={v5.scoreRows.auditedAdmittedRows.toLocaleString("zh-CN")} note={`${v5.scoreRows.auditedDistributions} 个校年分布`} /><Metric label="严格名额覆盖" value={`${((meta.quotaCoverage?.backtestCoverage ?? 0) * 100).toFixed(1)}%`} note={`${meta.quotaCoverage?.backtestRowsWithQuota ?? 0} / 226 条回测行`} /><Metric label="隐私边界" value="仅公开聚合" note="无姓名、考号或候选哈希" /></div>
            <EvidenceUtilisationChart />
            <div className="audit-layout">
              <div>
                <h3>关键审核结论</h3>
                <ul className="audit-list"><li><strong>73</strong><span>个精确—代理配对；插值代理 MAE 3.14 分，仅最低分代理 MAE 6.05 分，两类误差不能共用一个折扣。</span></li><li><strong>3.09</strong><span>分为精确 Q10 的 bootstrap 抽样标准差中位数；“精确”不等于无抽样误差。</span></li><li><strong>200</strong><span>个复试队列同时有录取与未录取样本；分数区分结果的 AUC 中位数为 0.876，但两组仍有重叠。</span></li><li><strong>+5.25</strong><span>分是选择梯度特征相对锚点的滞后回测 MAE 恶化量，因此该特征未晋级。</span></li></ul>
              </div>
              <div className="warning-stack"><p><ShieldCheck size={14} />工作簿是资料整理中间产物，不作为第一手公开文献；论文引用字段台账中的校方公告、研招目录与公开名单。</p><p><AlertTriangle size={14} />2027 冻结预测仍以原有 295 条历史目标为生产基线；V5 精确标签结果是冻结后回溯实验。</p><p><AlertTriangle size={14} />状态未知的 2,800 条成绩只用于复试池分布敏感性，不转换成录取标签。</p><p><AlertTriangle size={14} />严格报名时统考名额覆盖仍只有 {meta.quotaCoverage?.backtestRowsWithQuota ?? 0}/226，当前不改变生产预测。</p><p><Database size={14} />{v5.privacy}</p></div>
            </div>
          </section>
        </TabsContent>

        <TabsContent value="method" className="tab-panel">
          <ModelTheoryPanel
            selected={selected}
            score={score}
            selectedProbability={selectedProbability}
            selectedRisk={selectedRisk}
            pipelineStepId={pipelineStepId}
            onPipelineStepChange={setPipelineStepId}
            liveExample={liveExample}
          />
        </TabsContent>
      </Tabs>

      <footer><span>公开研究原型 v0.2 · V5 逐人分布研究层 · 仅用于风险比较</span><span>2027 数值已冻结；77 个精确 Q10 校年用于回溯验证，不构成录取保证</span></footer>
    </main>
  );
}
