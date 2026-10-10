import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = path.join(root, "outputs", "01a0fff7-637c-7f00-84ac-e158b4fb55ac");
const previewDir = path.join(outputDir, "workbook_previews");
const outputPath = path.join(outputDir, "应用统计择校模型_数据模板与审计.xlsx");
await fs.mkdir(previewDir, { recursive: true });

const COLORS = {
  navy: "#0B1F33",
  navy2: "#16324F",
  teal: "#0F766E",
  cyan: "#0891B2",
  amber: "#D97706",
  red: "#B91C1C",
  green: "#15803D",
  paleBlue: "#EAF2F8",
  paleTeal: "#E7F5F3",
  paleAmber: "#FFF7E6",
  paleRed: "#FDECEC",
  light: "#F5F7FA",
  border: "#D6DEE7",
  text: "#17202A",
  muted: "#5F6B76",
  white: "#FFFFFF",
};

const fontName = "Arial";

async function csvMatrix(relativePath) {
  const text = (await fs.readFile(path.join(root, relativePath), "utf8")).replace(/^\uFEFF/, "");
  const csvBook = await Workbook.fromCSV(text, { sheetName: "Imported" });
  return csvBook.worksheets.getItemAt(0).getUsedRange().values;
}

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : value;
}

function coerceColumns(matrix, numericHeaders = [], booleanHeaders = []) {
  const [headers, ...rows] = matrix;
  const numeric = new Set(numericHeaders);
  const boolean = new Set(booleanHeaders);
  return [
    headers,
    ...rows.map((row) => row.map((value, index) => {
      const header = headers[index];
      if (numeric.has(header)) return asNumber(value);
      if (boolean.has(header)) return String(value).toLowerCase() === "true" || value === "1";
      return value === "" ? null : value;
    })),
  ];
}

function pickColumns(matrix, fields) {
  const headers = matrix[0];
  const indexes = fields.map((field) => headers.indexOf(field));
  if (indexes.some((index) => index < 0)) {
    throw new Error(`Missing fields: ${fields.filter((_, i) => indexes[i] < 0).join(", ")}`);
  }
  return matrix.map((row) => indexes.map((index) => row[index]));
}

function applyBase(sheet) {
  sheet.showGridLines = false;
}

function styleTitle(sheet, title, context) {
  sheet.getRange("A2").values = [[title]];
  sheet.getRange("A2").format.font = { name: fontName, size: 16, bold: true, color: COLORS.navy };
  sheet.getRange("A3").values = [[context]];
  sheet.getRange("A3").format.font = { name: fontName, size: 10, italic: true, color: COLORS.muted };
  sheet.getRange("A4:N4").format.borders = { bottom: { style: "thin", color: COLORS.border } };
}

function styleHeader(range, fill = COLORS.navy) {
  range.format = {
    fill,
    font: { name: fontName, size: 10, bold: true, color: COLORS.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { insideVertical: { style: "thin", color: COLORS.white } },
  };
  range.format.rowHeight = 28;
}

function styleBody(range, { wrap = false, size = 9 } = {}) {
  range.format.font = { name: fontName, size, color: COLORS.text };
  range.format.verticalAlignment = "center";
  range.format.wrapText = wrap;
  range.format.borders = { insideHorizontal: { style: "thin", color: COLORS.border } };
}

function addTable(sheet, address, name, style = "TableStyleMedium2") {
  const table = sheet.tables.add(address, true, name);
  table.style = style;
  table.showBandedRows = true;
  table.showFilterButton = true;
  return table;
}

const program = coerceColumns(await csvMatrix("data/processed/program_year.csv"), [
  "year", "national_line", "cutoff", "cutoff_weight", "admitted_count", "admitted_min",
  "admitted_median", "admitted_max", "retest_count", "retest_ratio_reported",
  "retest_ratio_calculated", "q10_value", "q10_weight", "target_value", "target_weight",
  "margin_cutoff", "margin_q10", "admission_official_url_present", "issue_count", "source_row",
  "lag1_cutoff", "lag1_q10", "lag1_margin_q10", "lag1_admitted_count", "lag1_cutoff_change",
  "lag1_margin_change", "trailing_margin_median", "lag1_surprise_z", "peer_lag1_surprise_mean",
]);
const review = coerceColumns(await csvMatrix("data/processed/review_queue.csv"), ["year", "source_row"]);
const sources = coerceColumns(await csvMatrix("data/processed/source_registry.csv"), ["url_count", "source_row"]);
const events = coerceColumns(await csvMatrix("data/processed/events_2027.csv"), [
  "forecast_year", "withdrawal_adjustment", "neutral_adjustment", "crowd_adjustment",
  "withdrawal_weight", "neutral_weight", "crowd_weight",
]);
const forecastRaw = coerceColumns(await csvMatrix("data/processed/forecast_2027.csv"), [
  "latestCutoff", "latestQ10Proxy", "historyCount", "confidenceScore", "q05", "q10", "q20",
  "q50", "q80", "q90", "q95", "nationalLineMedian", "nationalLineQ90", "lagSurpriseZ",
  "peerPressure", "sourceRow", "latitude", "longitude", "officeHubLatitude", "officeHubLongitude",
], ["is985"]);
const backtestFull = coerceColumns(await csvMatrix("data/processed/rolling_backtest.csv"), [
  "year", "actual", "pred_q50", "pred_q80", "pred_q90", "pred_q95", "complex_q50", "weight", "baseline",
]);
const backtest = pickColumns(backtestFull, [
  "school", "year", "actual", "pred_q50", "pred_q80", "pred_q90", "pred_q95",
  "complex_q50", "selected_model", "weight", "baseline", "robust_baseline",
]);
const modelRun = JSON.parse(await fs.readFile(path.join(root, "data/audit/model_run.json"), "utf8"));
const sourceAudit = JSON.parse(await fs.readFile(path.join(root, "data/audit/source_audit.json"), "utf8"));
const nationalLines = JSON.parse(await fs.readFile(path.join(root, "data/processed/national_lines.json"), "utf8"));
const v5Audit = JSON.parse(await fs.readFile(path.join(root, "app/data/model-v5-audit.json"), "utf8"));

const forecastFields = [
  "school", "faction", "is985", "zone", "unit", "q50", "q80", "q90", "q95", "confidence",
  "confidenceScore", "latestCutoff", "latestQ10Proxy", "historyCount", "lagSurpriseZ", "peerPressure",
  "locationMatchedName", "latitude", "longitude", "locationPrecision", "officeHub", "officeHubLatitude",
  "officeHubLongitude", "transitMode", "transitLines", "transitReviewStatus", "liveRouteUrl",
  "eventCoverage", "selectedModel", "factionSource",
];
const forecast = pickColumns(forecastRaw, forecastFields);

const workbook = Workbook.create();
const summary = workbook.worksheets.add("审计总览");
const predictionsSheet = workbook.worksheets.add("预测结果");
const reviewSheet = workbook.worksheets.add("复核队列");
const templateSheet = workbook.worksheets.add("年度数据模板");
const eventSheet = workbook.worksheets.add("事件模板");
const backtestSheet = workbook.worksheets.add("回测明细");
const dictionarySheet = workbook.worksheets.add("字段字典");
const sourceSheet = workbook.worksheets.add("来源台账");
const dataSheet = workbook.worksheets.add("院校年度数据");

for (const sheet of [summary, predictionsSheet, reviewSheet, templateSheet, eventSheet, backtestSheet, dictionarySheet, sourceSheet, dataSheet]) applyBase(sheet);
summary.tabColor = COLORS.navy;
predictionsSheet.tabColor = COLORS.cyan;
reviewSheet.tabColor = COLORS.amber;
templateSheet.tabColor = COLORS.teal;
eventSheet.tabColor = COLORS.teal;
backtestSheet.tabColor = COLORS.navy2;
dictionarySheet.tabColor = "#64748B";

// Summary
styleTitle(summary, "应用统计择校模型：数据审计与回测", "2027 生产预测冻结于 2026-10-08；V5 逐人分布研究层更新至 2026-10-09");
summary.getRange("A6:B6").values = [["数据覆盖", "结果"]];
summary.getRange("A7:A13").values = [["覆盖院校"], ["院校年度记录"], ["核心字段有公开URL"], ["逐人成绩原始行"], ["去重后有效行"], ["精确录取成绩"], ["精确P10校年"]];
summary.getRange("B7:B13").values = [
  [sourceAudit.school_count],
  [program.length - 1],
  [`${v5Audit.sourceAudit.coreValuesWithPublicUrl}/${v5Audit.sourceAudit.coreValues}`],
  [v5Audit.scoreRows.raw],
  [v5Audit.scoreRows.uniqueValid],
  [v5Audit.scoreRows.exactAdmitted],
  [v5Audit.scoreRows.exactProgramYears],
];
styleHeader(summary.getRange("A6:B6"));
styleBody(summary.getRange("A7:B13"));
summary.getRange("B7:B13").format.numberFormat = "#,##0";
summary.getRange("A7:A13").format.fill = COLORS.light;

summary.getRange("D6:F6").values = [["成绩数据角色", "行数", "进入模型的方式"]];
summary.getRange("D7:F12").values = [
  ["精确录取层", v5Audit.scoreRows.exactAdmitted, "主标签、抽样误差和分布形状"],
  ["软录取证据", v5Audit.scoreRows.softAdmitted, "敏感性分析；未自动升级主模型"],
  ["诊断性录取行", v5Audit.scoreRows.diagnosticAdmitted, "质量审计，不转换为精确标签"],
  ["明确未录取", v5Audit.scoreRows.notAdmitted, "复试选择梯度诊断"],
  ["结果未知", v5Audit.scoreRows.unknownOutcome, "复试池分布敏感性，不伪造结局"],
  ["重复行", v5Audit.scoreRows.duplicatesNotDoubleCounted, "保留审计痕迹但不重复计数"],
];
styleHeader(summary.getRange("D6:F6"), COLORS.teal);
styleBody(summary.getRange("D7:F12"), { wrap: true });
summary.getRange("E7:E12").format.numberFormat = "#,##0";

summary.getRange("A15:B15").values = [["滚动回测（2024—2026）", "结果"]];
summary.getRange("A16:A22").values = [["回测样本"], ["主预测加权MAE"], ["稳健边际分锚点MAE"], ["上一年锚点加权MAE"], ["复杂候选模型加权MAE"], ["低估率"], ["90%原始区间覆盖率"]];
summary.getRange("B16:B22").formulas = [
  ["=COUNTA('回测明细'!$A$2:$A$227)"],
  ["=SUMPRODUCT('回测明细'!$M$2:$M$227,'回测明细'!$J$2:$J$227)/SUM('回测明细'!$J$2:$J$227)"],
  ["=SUMPRODUCT('回测明细'!$Q$2:$Q$227,'回测明细'!$J$2:$J$227)/SUMIFS('回测明细'!$J$2:$J$227,'回测明细'!$L$2:$L$227,\"<>\")"],
  ["=SUMPRODUCT('回测明细'!$P$2:$P$227,'回测明细'!$J$2:$J$227)/SUMIFS('回测明细'!$J$2:$J$227,'回测明细'!$K$2:$K$227,\"<>\")"],
  ["=SUMPRODUCT('回测明细'!$R$2:$R$227,'回测明细'!$J$2:$J$227)/SUM('回测明细'!$J$2:$J$227)"],
  ["=SUMPRODUCT('回测明细'!$N$2:$N$227,'回测明细'!$J$2:$J$227)/SUM('回测明细'!$J$2:$J$227)"],
  ["=SUMPRODUCT('回测明细'!$O$2:$O$227,'回测明细'!$J$2:$J$227)/SUM('回测明细'!$J$2:$J$227)"],
];
styleHeader(summary.getRange("A15:B15"));
styleBody(summary.getRange("A16:B22"));
summary.getRange("A16:A22").format.fill = COLORS.light;
summary.getRange("B17:B20").format.numberFormat = "0.00";
summary.getRange("B21:B22").format.numberFormat = "0.0%";

summary.getRange("D15:F15").values = [["V5研究闸门", "结果", "时间外证据"]];
summary.getRange("D16:F20").values = [
  ["精确标签替换代理", "通过", `${v5Audit.exactLabelBacktest.frozenBaselineMae.toFixed(2)} → ${v5Audit.exactLabelBacktest.exactEnhancedMae.toFixed(2)} MAE`],
  ["逐校滞后分布形状", "通过", `${v5Audit.shapeGate.pooledExactMae.toFixed(3)} → ${v5Audit.shapeGate.lagExactMae.toFixed(3)} 分位MAE`],
  ["软证据叠加形状", "保留研究", `仅改善 ${v5Audit.shapeGate.softIncrementalGain.toFixed(3)}，落在简约等价带内`],
  ["复试选择梯度入模", "拒绝", `${v5Audit.selectionGradient.anchorMae.toFixed(2)} → ${v5Audit.selectionGradient.candidateMae.toFixed(2)} MAE`],
  ["2027生产预测", "冻结不变", "新增结果仅属冻结后回溯研究层"],
];
styleHeader(summary.getRange("D15:F15"), COLORS.teal);
styleBody(summary.getRange("D16:F20"), { wrap: true });
summary.getRange("E16:E20").conditionalFormats.add("containsText", { text: "通过", format: { fill: COLORS.paleTeal, font: { color: COLORS.green, bold: true } } });
summary.getRange("E16:E20").conditionalFormats.add("containsText", { text: "拒绝", format: { fill: COLORS.paleRed, font: { color: COLORS.red, bold: true } } });
summary.getRange("E16:E20").conditionalFormats.add("containsText", { text: "保留", format: { fill: COLORS.paleAmber, font: { color: COLORS.amber, bold: true } } });

summary.getRange("A24:F24").values = [["关键限制", null, null, null, null, null]];
summary.getRange("A25:F30").values = [
  ["精确逐人成绩优先替代代理；尚无精确名单的校年继续保留代理并显式传播测量误差。", null, null, null, null, null],
  ["精确标签当前只有77个校年、44所学校；有效时间外起点仍少，不能把校年数误当独立年份数。", null, null, null, null, null],
  ["同年录取结果、最终人数和选择梯度属于事后信息；只允许以严格滞后或诊断方式使用。", null, null, null, null, null],
  ["候选人姓名、考号、哈希和逐行原文不进入公开工作簿、网页或Git仓库。", null, null, null, null, null],
  ["V5的研究改进没有覆盖已冻结的2027数值；重新生产发布必须另开版本并在结果发生前冻结。", null, null, null, null, null],
  ["未发现事件不等于确认无事件；报名截止前仍需逐校核验招生简章、计划名额和公告。", null, null, null, null, null],
];
styleHeader(summary.getRange("A24:F24"), COLORS.red);
summary.getRange("A25:F30").format = { fill: COLORS.paleRed, font: { name: fontName, size: 9, color: COLORS.red }, wrapText: true, verticalAlignment: "center" };
summary.getRange("A25:F30").format.rowHeight = 26;
summary.mergeCells("A24:F24");
for (const row of [25, 26, 27, 28, 29, 30]) summary.mergeCells(`A${row}:F${row}`);

summary.getRange("H6:I11").values = [
  ["逐人成绩角色", "行数"],
  ["精确录取", v5Audit.scoreRows.exactAdmitted],
  ["软录取证据", v5Audit.scoreRows.softAdmitted],
  ["诊断性录取", v5Audit.scoreRows.diagnosticAdmitted],
  ["明确未录取", v5Audit.scoreRows.notAdmitted],
  ["结果未知", v5Audit.scoreRows.unknownOutcome],
];
styleHeader(summary.getRange("H6:I6"), COLORS.amber);
styleBody(summary.getRange("H7:I11"));
const roleChart = summary.charts.add("bar", summary.getRange("H6:I11"));
roleChart.title = "14,317条成绩的证据分流";
roleChart.titleTextStyle.fontSize = 12;
roleChart.titleTextStyle.typeface = fontName;
roleChart.hasLegend = false;
roleChart.xAxis = { textStyle: { typeface: fontName, fontSize: 9 } };
roleChart.yAxis = { numberFormatCode: "0", numberFormatSourceLinked: false, textStyle: { typeface: fontName, fontSize: 9 } };
roleChart.setPosition("H13", "N25");
if (roleChart.series.items[0]) roleChart.series.items[0].fill = COLORS.amber;

summary.getRange("H27:I34").values = [
  ["派系", "院校数"],
  ["纯贾", sourceAudit.faction_counts["纯贾"]],
  ["纯茆", sourceAudit.faction_counts["纯茆"]],
  ["贾茆", sourceAudit.faction_counts["贾茆"]],
  ["茆Pro", sourceAudit.faction_counts["茆Pro"]],
  ["贾茆Pro", sourceAudit.faction_counts["贾茆Pro"]],
  ["待核实", sourceAudit.faction_counts["待核实"]],
  ["合计", sourceAudit.school_count],
];
styleHeader(summary.getRange("H27:I27"), COLORS.teal);
styleBody(summary.getRange("H28:I34"));
summary.getRange("I28:I34").format.numberFormat = "#,##0";

summary.getRange("A1:N34").format.font = { name: fontName, size: 10, color: COLORS.text };
summary.getRange("A1:A34").format.columnWidth = 28;
summary.getRange("B1:B34").format.columnWidth = 13;
summary.getRange("C1:C34").format.columnWidth = 3;
summary.getRange("D1:D34").format.columnWidth = 34;
summary.getRange("E1:E34").format.columnWidth = 11;
summary.getRange("F1:F34").format.columnWidth = 35;
summary.getRange("G1:G34").format.columnWidth = 3;
summary.getRange("H1:H34").format.columnWidth = 24;
summary.getRange("I1:I34").format.columnWidth = 10;

// Forecast output
predictionsSheet.getRangeByIndexes(0, 0, forecast.length, forecast[0].length).values = forecast;
styleHeader(predictionsSheet.getRange(`A1:AD1`), COLORS.cyan);
styleBody(predictionsSheet.getRange(`A2:AD${forecast.length}`));
addTable(predictionsSheet, `A1:AD${forecast.length}`, "ForecastTable", "TableStyleMedium2");
predictionsSheet.freezePanes.freezeRows(1);
predictionsSheet.freezePanes.freezeColumns(2);
predictionsSheet.getRange(`F2:I${forecast.length}`).format.numberFormat = "0.0";
predictionsSheet.getRange(`K2:K${forecast.length}`).format.numberFormat = "0";
predictionsSheet.getRange(`L2:M${forecast.length}`).format.numberFormat = "0.0";
predictionsSheet.getRange(`N2:N${forecast.length}`).format.numberFormat = "0";
predictionsSheet.getRange(`O2:P${forecast.length}`).format.numberFormat = "0.00";
predictionsSheet.getRange(`R2:S${forecast.length}`).format.numberFormat = "0.00000";
predictionsSheet.getRange(`V2:W${forecast.length}`).format.numberFormat = "0.00000";
predictionsSheet.getRange(`K2:K${forecast.length}`).conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"], thresholds: ["min", { type: "percentile", value: 50 }, "max"] });
predictionsSheet.getRange(`H2:H${forecast.length}`).conditionalFormats.add("dataBar", { color: COLORS.cyan, thresholds: ["min", "max"], gradient: false });
for (const [label, fill, color] of [
  ["纯贾", "#E0F2FE", "#075985"], ["纯茆", "#DCFCE7", "#166534"], ["贾茆", "#FEF3C7", "#92400E"],
  ["茆Pro", "#EDE9FE", "#5B21B6"], ["贾茆Pro", "#FFEDD5", "#9A3412"], ["待核实", "#F1F5F9", "#475569"],
]) predictionsSheet.getRange(`B2:B${forecast.length}`).conditionalFormats.addCustom(`=$B2="${label}"`, { fill, font: { color, bold: true } });
predictionsSheet.getRange(`A1:A${forecast.length}`).format.columnWidth = 18;
predictionsSheet.getRange(`B1:B${forecast.length}`).format.columnWidth = 12;
predictionsSheet.getRange(`C1:D${forecast.length}`).format.columnWidth = 8;
predictionsSheet.getRange(`E1:E${forecast.length}`).format.columnWidth = 24;
predictionsSheet.getRange(`F1:P${forecast.length}`).format.columnWidth = 12;
predictionsSheet.getRange(`Q1:Q${forecast.length}`).format.columnWidth = 40;
predictionsSheet.getRange(`R1:T${forecast.length}`).format.columnWidth = 14;
predictionsSheet.getRange(`U1:U${forecast.length}`).format.columnWidth = 28;
predictionsSheet.getRange(`V1:X${forecast.length}`).format.columnWidth = 14;
predictionsSheet.getRange(`Y1:Y${forecast.length}`).format.columnWidth = 28;
predictionsSheet.getRange(`Z1:Z${forecast.length}`).format.columnWidth = 26;
predictionsSheet.getRange(`AA1:AA${forecast.length}`).format.columnWidth = 56;
predictionsSheet.getRange(`AB1:AB${forecast.length}`).format.columnWidth = 26;
predictionsSheet.getRange(`AC1:AC${forecast.length}`).format.columnWidth = 34;
predictionsSheet.getRange(`AD1:AD${forecast.length}`).format.columnWidth = 28;

// Review queue
reviewSheet.getRangeByIndexes(0, 0, review.length, review[0].length).values = review;
styleHeader(reviewSheet.getRange("A1:G1"), COLORS.amber);
styleBody(reviewSheet.getRange(`A2:G${review.length}`));
addTable(reviewSheet, `A1:G${review.length}`, "ReviewQueueTable", "TableStyleMedium9");
reviewSheet.freezePanes.freezeRows(1);
reviewSheet.getRange(`F2:F${review.length}`).dataValidation = { rule: { type: "list", values: ["high", "medium", "low"] } };
reviewSheet.getRange(`G2:G${review.length}`).dataValidation = { rule: { type: "list", values: ["待人工复核", "核验中", "已核实", "已排除"] } };
reviewSheet.getRange(`F2:F${review.length}`).conditionalFormats.add("containsText", { text: "high", format: { fill: COLORS.paleRed, font: { color: COLORS.red, bold: true } } });
reviewSheet.getRange(`G2:G${review.length}`).conditionalFormats.add("containsText", { text: "待人工复核", format: { fill: COLORS.paleAmber, font: { color: COLORS.amber, bold: true } } });
reviewSheet.getRange(`A1:A${review.length}`).format.columnWidth = 18;
reviewSheet.getRange(`B1:B${review.length}`).format.columnWidth = 9;
reviewSheet.getRange(`C1:C${review.length}`).format.columnWidth = 18;
reviewSheet.getRange(`D1:D${review.length}`).format.columnWidth = 11;
reviewSheet.getRange(`E1:E${review.length}`).format.columnWidth = 38;
reviewSheet.getRange(`F1:G${review.length}`).format.columnWidth = 16;

// Standard annual data-entry template
styleTitle(templateSheet, "院校年度数据标准模板", "一行代表一所学校一个招生年份。黄色列为优先必填；不要把专项计划、非全日制或调剂样本混入普通统考口径。");
const templateHeaders = [
  "school", "year", "national_zone", "national_line", "cutoff", "cutoff_source", "cutoff_evidence_class",
  "admitted_count", "admitted_min", "admitted_median", "admitted_max", "retest_count", "q10_value",
  "q10_method", "special_plan_excluded", "admission_source_url", "review_status",
];
templateSheet.getRangeByIndexes(5, 0, 1, templateHeaders.length).values = [templateHeaders];
templateSheet.getRangeByIndexes(6, 0, 100, templateHeaders.length).values = Array.from({ length: 100 }, () => Array(templateHeaders.length).fill(null));
styleHeader(templateSheet.getRange("A6:Q6"), COLORS.teal);
styleBody(templateSheet.getRange("A7:Q106"));
templateSheet.getRange("A7:F106").format.fill = COLORS.paleAmber;
addTable(templateSheet, "A6:Q106", "AnnualDataTemplate", "TableStyleMedium4");
templateSheet.freezePanes.freezeRows(6);
templateSheet.freezePanes.freezeColumns(1);
templateSheet.getRange("B7:B106").dataValidation = { rule: { type: "whole", operator: "between", formula1: 2017, formula2: 2100 } };
templateSheet.getRange("C7:C106").dataValidation = { rule: { type: "list", values: ["A", "B"] } };
templateSheet.getRange("G7:G106").dataValidation = { rule: { type: "list", values: ["official", "official_secondary", "third_party", "unclassified", "national_floor_only"] } };
templateSheet.getRange("N7:N106").dataValidation = { rule: { type: "list", values: ["exact_candidate_quantile", "order_stat_interpolation", "small_n_minimum", "minimum_only", "missing"] } };
templateSheet.getRange("O7:O106").dataValidation = { rule: { type: "list", values: ["是", "否", "不明确"] } };
templateSheet.getRange("Q7:Q106").dataValidation = { rule: { type: "list", values: ["待人工复核", "核验中", "已核实", "已排除"] } };
templateSheet.getRange("A1:A106").format.columnWidth = 18;
templateSheet.getRange("B1:E106").format.columnWidth = 12;
templateSheet.getRange("F1:G106").format.columnWidth = 24;
templateSheet.getRange("H1:M106").format.columnWidth = 13;
templateSheet.getRange("N1:N106").format.columnWidth = 26;
templateSheet.getRange("O1:O106").format.columnWidth = 18;
templateSheet.getRange("P1:P106").format.columnWidth = 42;
templateSheet.getRange("Q1:Q106").format.columnWidth = 16;

// Event template with audited rows and reserved input rows
styleTitle(eventSheet, "招生事件与市场行为模板", "事件值是情景先验，不是已识别的因果效应。官方原文必须保留，场景权重之和应为 1。");
const eventRows = events.slice(1);
const eventHeaders = events[0];
const reservedEvents = [...eventRows, ...Array.from({ length: 15 }, () => Array(eventHeaders.length).fill(null))];
eventSheet.getRangeByIndexes(5, 0, 1, eventHeaders.length).values = [eventHeaders];
eventSheet.getRangeByIndexes(6, 0, reservedEvents.length, eventHeaders.length).values = reservedEvents;
styleHeader(eventSheet.getRange("A6:P6"), COLORS.teal);
styleBody(eventSheet.getRange(`A7:P${6 + reservedEvents.length}`), { wrap: true, size: 9 });
addTable(eventSheet, `A6:P${6 + reservedEvents.length}`, "EventTemplate", "TableStyleMedium4");
eventSheet.freezePanes.freezeRows(6);
eventSheet.freezePanes.freezeColumns(1);
eventSheet.getRange(`G7:G${6 + reservedEvents.length}`).dataValidation = { rule: { type: "list", values: ["minor", "moderate", "major", "persistent"] } };
eventSheet.getRange(`O7:O${6 + reservedEvents.length}`).dataValidation = { rule: { type: "list", values: ["待检索", "已机器核验待人工复核", "已人工核验", "已失效"] } };
eventSheet.getRange(`H7:M${6 + reservedEvents.length}`).format.numberFormat = "0.00";
eventSheet.getRange(`K7:M${6 + reservedEvents.length}`).conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"], thresholds: ["min", { type: "percentile", value: 50 }, "max"] });
eventSheet.getRange(`A1:A${6 + reservedEvents.length}`).format.columnWidth = 18;
eventSheet.getRange(`B1:G${6 + reservedEvents.length}`).format.columnWidth = 18;
eventSheet.getRange(`H1:M${6 + reservedEvents.length}`).format.columnWidth = 15;
eventSheet.getRange(`N1:N${6 + reservedEvents.length}`).format.columnWidth = 48;
eventSheet.getRange(`O1:O${6 + reservedEvents.length}`).format.columnWidth = 24;
eventSheet.getRange(`P1:P${6 + reservedEvents.length}`).format.columnWidth = 45;

// Backtest detail and auditable calculations
const backtestHeaders = [...backtest[0], "absolute_error", "underpredicted", "q90_covered", "baseline_abs_error", "robust_baseline_abs_error", "complex_abs_error", "asymmetric_loss_3x"];
backtestSheet.getRangeByIndexes(0, 0, 1, backtestHeaders.length).values = [backtestHeaders];
backtestSheet.getRangeByIndexes(1, 0, backtest.length - 1, backtest[0].length).values = backtest.slice(1);
const lastBacktestRow = backtest.length;
backtestSheet.getRange("M2").formulas = [["=ABS(C2-D2)"]];
backtestSheet.getRange(`M2:M${lastBacktestRow}`).fillDown();
backtestSheet.getRange("N2").formulas = [["=IF(C2>D2,1,0)"]];
backtestSheet.getRange(`N2:N${lastBacktestRow}`).fillDown();
backtestSheet.getRange("O2").formulas = [["=IF(C2<=F2,1,0)"]];
backtestSheet.getRange(`O2:O${lastBacktestRow}`).fillDown();
backtestSheet.getRange("P2").formulas = [["=IF(K2=\"\",\"\",ABS(C2-K2))"]];
backtestSheet.getRange(`P2:P${lastBacktestRow}`).fillDown();
backtestSheet.getRange("Q2").formulas = [["=IF(L2=\"\",\"\",ABS(C2-L2))"]];
backtestSheet.getRange(`Q2:Q${lastBacktestRow}`).fillDown();
backtestSheet.getRange("R2").formulas = [["=ABS(C2-H2)"]];
backtestSheet.getRange(`R2:R${lastBacktestRow}`).fillDown();
backtestSheet.getRange("S2").formulas = [["=IF(C2>D2,3*(C2-D2),D2-C2)"]];
backtestSheet.getRange(`S2:S${lastBacktestRow}`).fillDown();
styleHeader(backtestSheet.getRange("A1:S1"), COLORS.navy2);
styleBody(backtestSheet.getRange(`A2:S${lastBacktestRow}`));
addTable(backtestSheet, `A1:S${lastBacktestRow}`, "BacktestTable", "TableStyleMedium2");
backtestSheet.freezePanes.freezeRows(1);
backtestSheet.freezePanes.freezeColumns(2);
backtestSheet.getRange(`C2:S${lastBacktestRow}`).format.numberFormat = "0.00";
backtestSheet.getRange(`N2:O${lastBacktestRow}`).format.numberFormat = "0";
backtestSheet.getRange(`M2:M${lastBacktestRow}`).conditionalFormats.add("colorScale", { colors: ["#DCFCE7", "#FEF3C7", "#FEE2E2"], thresholds: ["min", { type: "percentile", value: 50 }, "max"] });
backtestSheet.getRange(`A1:A${lastBacktestRow}`).format.columnWidth = 18;
backtestSheet.getRange(`B1:B${lastBacktestRow}`).format.columnWidth = 9;
backtestSheet.getRange(`C1:S${lastBacktestRow}`).format.columnWidth = 14;
backtestSheet.getRange(`I1:I${lastBacktestRow}`).format.columnWidth = 28;

// Field dictionary
styleTitle(dictionarySheet, "字段字典", "字段按观测时点、单位和缺失处理定义。模型只使用报名开始前可获得或严格滞后的信息。");
const dictionaryHeaders = ["数据表", "字段", "中文名", "类型", "单位/取值", "是否必填", "定义与口径", "缺失处理"];
const dictionaryRows = [
  ["年度数据", "school", "学校", "文本", "教育部传统985/211校名", "是", "预测与审核的院校主键", "不得缺失"],
  ["院校主表", "faction", "派系", "分类", "纯贾/纯茆/贾茆/茆Pro/贾茆Pro/待核实", "是", "原工作簿的机构课程结构分类，并非院校官方分类", "未覆盖时标为待核实"],
  ["院校主表", "faction_source", "派系来源", "文本", "原表标签/填色/合并规则", "是", "记录派系判定来自文字、填色或合并校区规则", "不得用猜测补齐"],
  ["院校主表", "latitude/longitude", "培养校区坐标", "数值", "WGS84十进制度", "是", "按当前应用统计培养单位所在主要校区定位", "公开地图匹配后待人工复核"],
  ["院校主表", "location_precision", "坐标精度", "分类", "campus/campus_area/campus_entrance", "是", "区分校区面、校区片区和校门点位", "缺失则不在地图显示"],
  ["通勤参考", "office_hub", "代表性办公集聚区", "文本", "研究用节点", "是", "用于比较学校与本市代表性公司办公区的空间关系，不等同就业排名", "待人工复核"],
  ["通勤参考", "transit_lines", "候选公共交通线路", "文本", "地铁/轨道/公交线路", "是", "静态候选方案，便于初筛通勤结构", "必须通过实时规划复核"],
  ["通勤参考", "live_route_url", "实时公交规划", "URL", "高德地图URI API", "是", "按校区和办公区坐标打开当前公交规划", "路网变化由地图平台实时处理"],
  ["年度数据", "year", "招生年份", "整数", "YYYY", "是", "该年报名并参加初试的招生年度", "不得缺失"],
  ["年度数据", "national_zone", "国家线分区", "分类", "A/B", "是", "按学校所在地确定的国家线分区", "不得缺失"],
  ["年度数据", "national_line", "经管类国家线", "数值", "总分", "是", "对应年度、分区的经济学门类国家线", "官方来源优先"],
  ["年度数据", "cutoff", "复试线数值", "数值", "总分", "条件必填", "普通全日制025200适用的校/院/专业复试线；多方向保守取最高普通线", "保留空值，不用国家线冒充"],
  ["年度数据", "cutoff_source", "复试线来源", "URL", "网页或PDF", "条件必填", "支持cutoff的原始或二次来源", "缺失则进入复核队列"],
  ["年度数据", "cutoff_evidence_class", "复试线证据等级", "分类", "official等", "是", "官方、官方二次、第三方、未分类或仅国家线", "按等级降权"],
  ["年度数据", "admitted_count", "普通统考拟录取人数", "整数", "人", "否", "排除专项计划、非全日制、调剂后的普通统考人数", "保留空值"],
  ["年度数据", "admitted_min", "拟录取最低分", "数值", "总分", "否", "普通统考样本最低初试总分", "保留空值"],
  ["年度数据", "admitted_median", "拟录取中位数", "数值", "总分", "否", "普通统考样本初试总分中位数", "保留空值"],
  ["年度数据", "admitted_max", "拟录取最高分", "数值", "总分", "否", "普通统考样本最高初试总分", "保留空值"],
  ["年度数据", "retest_count", "复试人数", "整数", "人", "否", "与拟录取口径一致的普通统考复试人数", "口径不闭合则留空"],
  ["年度数据", "q10_value", "录取初试P10", "数值", "总分", "目标", "普通统考拟录取样本初试总分10%分位数", "无逐人成绩时才用透明代理"],
  ["年度数据", "q10_method", "P10取得方法", "分类", "exact/interpolation/minimum", "是", "区分精确候选人分位数与代理算法", "不得用颜色代替"],
  ["年度数据", "q10_weight", "P10标签权重", "数值", "0—1", "是", "由取得方法与来源可靠性共同决定", "缺失标签权重为0"],
  ["逐人成绩审计", "row_role", "证据角色", "分类", "exact/soft/diagnostic", "是", "依据名单图例、分组一致性、排除规则和来源质量分配角色", "不得因读取方便而混用"],
  ["逐人成绩审计", "outcome_status", "录取结局", "分类", "admitted/not_admitted/unknown", "是", "仅在名单图例或结构明确时赋予录取结局", "unknown不得伪造为未录取"],
  ["逐人成绩审计", "duplicate_status", "重复状态", "分类", "unique/exact_duplicate/conflict", "是", "相同来源与内容哈希不重复计数，冲突另行复核", "保留审计痕迹"],
  ["逐人成绩审计", "privacy_scope", "公开边界", "分类", "private/aggregate_public", "是", "逐人原文、姓名、考号和哈希保留私有；仅校年聚合公开", "不得上传候选人逐行数据"],
  ["年度数据", "special_plan_excluded", "专项计划已排除", "分类", "是/否/不明确", "是", "是否排除少干、士兵、援藏等专项计划", "不明确则进入复核队列"],
  ["年度数据", "lag1_q10", "上一年P10", "数值", "总分", "模型生成", "严格滞后一年的目标代理", "无历史时回退到分层模型"],
  ["年度数据", "lag1_surprise_z", "上一年热冷异常", "数值", "标准差", "模型生成", "上一年相对更早历史的标准化偏离", "历史不足则留空"],
  ["年度数据", "peer_lag1_surprise_mean", "竞校热度", "数值", "标准差", "模型生成", "同层次、相近历史难度院校上一年异常均值", "候选不足时用同层均值"],
  ["事件", "event_type", "事件类型", "分类", "科目/考纲/名额/新停招等", "是", "报名时点前已公开且可能改变报考与分数分布的事件", "未发现不等于无事件"],
  ["事件", "withdrawal_adjustment", "退潮情景冲击", "数值", "分", "是", "考生退出情景下对所需分数的调整", "人工复核后使用"],
  ["事件", "neutral_adjustment", "中性情景冲击", "数值", "分", "是", "信息被市场正常吸收时的调整", "人工复核后使用"],
  ["事件", "crowd_adjustment", "涌入情景冲击", "数值", "分", "是", "考生集中涌入情景下的调整", "人工复核后使用"],
  ["事件", "withdrawal_weight", "退潮权重", "数值", "0—1", "是", "退潮情景先验概率", "三项权重和必须为1"],
  ["事件", "neutral_weight", "中性权重", "数值", "0—1", "是", "中性情景先验概率", "三项权重和必须为1"],
  ["事件", "crowd_weight", "涌入权重", "数值", "0—1", "是", "涌入情景先验概率", "三项权重和必须为1"],
  ["预测", "q50", "预测中位数", "数值", "总分", "输出", "所需分数预测分布的50%分位", "不是保证线"],
  ["预测", "q80", "80%上界", "数值", "总分", "输出", "按模型有80%概率覆盖真实P10的上界", "需结合校准表现"],
  ["预测", "q90", "90%稳妥线", "数值", "总分", "输出", "按约定的稳标准使用的保守上界", "尾部仍受未知事件影响"],
  ["预测", "q95", "95%保守线", "数值", "总分", "输出", "更保守的预测上界", "不等于录取保证"],
  ["回测", "selected_model", "选中点预测模型", "分类", "anchor/fallback", "输出", "滚动回测优先选择历史边际分中位数锚点，无锚点时依次回退上一年或复杂模型", "按时间切分决定"],
  ["回测", "weight", "样本权重", "数值", "0—1", "输出", "目标代理与来源可靠性权重", "不可解释为样本概率"],
];
dictionarySheet.getRangeByIndexes(5, 0, 1, dictionaryHeaders.length).values = [dictionaryHeaders];
dictionarySheet.getRangeByIndexes(6, 0, dictionaryRows.length, dictionaryHeaders.length).values = dictionaryRows;
styleHeader(dictionarySheet.getRange("A6:H6"), "#64748B");
styleBody(dictionarySheet.getRange(`A7:H${6 + dictionaryRows.length}`), { wrap: true });
addTable(dictionarySheet, `A6:H${6 + dictionaryRows.length}`, "DictionaryTable", "TableStyleMedium2");
dictionarySheet.freezePanes.freezeRows(6);
dictionarySheet.getRange(`A1:A${6 + dictionaryRows.length}`).format.columnWidth = 14;
dictionarySheet.getRange(`B1:B${6 + dictionaryRows.length}`).format.columnWidth = 28;
dictionarySheet.getRange(`C1:C${6 + dictionaryRows.length}`).format.columnWidth = 20;
dictionarySheet.getRange(`D1:F${6 + dictionaryRows.length}`).format.columnWidth = 14;
dictionarySheet.getRange(`G1:H${6 + dictionaryRows.length}`).format.columnWidth = 42;

// Source ledger. Existing source registry remains intact, with official national-line sources appended.
const sourceHeaders = sources[0];
const sourceRows = sources.slice(1);
for (const [year, url] of Object.entries(nationalLines.sources)) {
  sourceRows.push([`教育部${year}年国家线`, "官方", "经济学A/B区国家线", url, 1, "教育部公布的全国硕士研究生招生考试考生进入复试初试成绩基本要求", "补充核验", null]);
}
sourceSheet.getRangeByIndexes(0, 0, 1, sourceHeaders.length).values = [sourceHeaders];
sourceSheet.getRangeByIndexes(1, 0, sourceRows.length, sourceHeaders.length).values = sourceRows;
styleHeader(sourceSheet.getRange("A1:H1"), "#64748B");
styleBody(sourceSheet.getRange(`A2:H${1 + sourceRows.length}`), { wrap: true });
addTable(sourceSheet, `A1:H${1 + sourceRows.length}`, "SourceLedger", "TableStyleMedium2");
sourceSheet.freezePanes.freezeRows(1);
sourceSheet.getRange(`A1:A${1 + sourceRows.length}`).format.columnWidth = 26;
sourceSheet.getRange(`B1:C${1 + sourceRows.length}`).format.columnWidth = 18;
sourceSheet.getRange(`D1:D${1 + sourceRows.length}`).format.columnWidth = 58;
sourceSheet.getRange(`E1:E${1 + sourceRows.length}`).format.columnWidth = 10;
sourceSheet.getRange(`F1:F${1 + sourceRows.length}`).format.columnWidth = 44;
sourceSheet.getRange(`G1:G${1 + sourceRows.length}`).format.columnWidth = 18;
sourceSheet.getRange(`H1:H${1 + sourceRows.length}`).format.columnWidth = 10;

// Full processed school-year data
dataSheet.getRangeByIndexes(0, 0, program.length, program[0].length).values = program;
const programLastColumn = "AO";
styleHeader(dataSheet.getRange(`A1:${programLastColumn}1`), "#475569");
styleBody(dataSheet.getRange(`A2:${programLastColumn}${program.length}`), { size: 8 });
addTable(dataSheet, `A1:${programLastColumn}${program.length}`, "ProgramYearData", "TableStyleMedium2");
dataSheet.freezePanes.freezeRows(1);
dataSheet.freezePanes.freezeColumns(2);
dataSheet.getRange(`A1:A${program.length}`).format.columnWidth = 18;
dataSheet.getRange(`B1:B${program.length}`).format.columnWidth = 9;
dataSheet.getRange(`C1:E${program.length}`).format.columnWidth = 12;
dataSheet.getRange(`F1:K${program.length}`).format.columnWidth = 28;
dataSheet.getRange(`L1:AO${program.length}`).format.columnWidth = 14;
dataSheet.getRange(`S2:S${program.length}`).conditionalFormats.add("dataBar", { color: COLORS.cyan, thresholds: ["min", "max"], gradient: false });

workbook.recalculate();

const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "审计总览!A1:N34",
  include: "values,formulas",
  tableMaxRows: 30,
  tableMaxCols: 14,
  maxChars: 16000,
});
console.log(summaryCheck.ndjson);
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 8000,
});
console.log(errorCheck.ndjson);

const previews = [
  ["审计总览", "A1:N34"],
  ["预测结果", "A1:AD20"],
  ["复核队列", "A1:G25"],
  ["年度数据模板", "A1:Q24"],
  ["事件模板", "A1:P18"],
  ["回测明细", "A1:S22"],
  ["字段字典", `A1:H${Math.min(38, 6 + dictionaryRows.length)}`],
  ["来源台账", "A1:H20"],
  ["院校年度数据", "A1:Q22"],
];
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({
  outputPath,
  previewDir,
  sheets: previews.map(([sheetName]) => sheetName),
  sourceAudit,
  modelMetrics: modelRun.backtest,
}, null, 2));
