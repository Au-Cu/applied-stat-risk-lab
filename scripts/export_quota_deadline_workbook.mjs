// Run a copied instance from a task-specific directory linked to bundled deps.
import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

process.on('uncaughtException',error=>{console.error(error.stack||String(error));process.exitCode=1;});
process.on('unhandledRejection',error=>{console.error(error?.stack||String(error));process.exitCode=1;});

const root = process.argv[2];
if (!root) throw new Error('Pass the repository root as the first argument.');
const expanded=process.argv.includes('--expanded');
const batch=expanded?'quota_deadline_20261023_r2':'quota_deadline_20261023';
const input = JSON.parse(await fs.readFile(path.join(root, `output/research/${batch}/quota_deadline_dataset.json`), 'utf8'));
const reviewRecords=expanded?input.records.filter(r=>r.review_status?.startsWith('规则')):[];
if(expanded) input.records=input.records.filter(r=>!r.review_status?.startsWith('规则'));
const outputDir = path.join(root, 'outputs/01a0fff7-637c-7f00-84ac-e158b4fb55ac');
const qaDir = path.join(root, 'work/quota-deadline-workbook-20261023');
await fs.mkdir(outputDir, {recursive: true});

const wb = Workbook.create();
const main = wb.worksheets.add('名额记录');
const calendar = wb.worksheets.add('年度报名截止');
const gaps = wb.worksheets.add('覆盖缺口');
const navy = '#253B53';
const muted = '#F1F4F7';

const dateValue = (value) => value ? new Date(value.replace(/\+08:00$/, '') + (value.endsWith('Z') ? '' : 'Z')) : null;
const firstData = 8;
const lastData = firstData + input.records.length - 1;
const headers = ['学校','培养单位','入学年','记录性质','原文统考计划（人）','同口径总计划（人）','已接收推免（人）','拟接收推免（人）','总计划减已接推免（人）','专项口径','信息齐备日期','日期精度','总计划发布日','实际推免数发布日','净计划发布日','报名截止（北京时间）','相对截止时间','可用性说明','口径备注','官方公告或附件','配套证据URL','原文定位','证据ID','快照SHA256'];
if(expanded){
  headers[8]='算术差额（非核定净额）';
  headers[10]='本次值公开证据日';
  headers[19]='来源公告或附件';
  headers.push('复核状态','来源等级','学习形式','原件采集时间（北京）','截止前可见性','可见性依据','原公告日期（版本另核）','公开/版本时间依据','统计截至时点（非发布）');
}
const endCol=expanded?'AG':'X';
main.showGridLines = false;
main.tabColor = navy;
main.getRange('A2').values = [['应用统计硕士名额证据台账']];
main.getRange('A2').format.font = {name:'Arial', size:14, bold:true, color:navy};
main.getRange('A3').values = [[expanded?`2022—2027入学年；81校×6年完整列出缺口；采集截至${input.summary.as_of_date}，不代表名额已收齐。`:'2022—2027入学年；以报名截止日22:00为信息边界；首批采集截至2026-10-23。']];
main.getRange('A3').format.font = {name:'Arial', size:10, color:'#5A6876'};
main.getRange('A4').values = [['记录数']];
main.getRange('B4').formulas = [[`=COUNTA(A${firstData}:A${lastData})`]];
main.getRange('D4').values = [[expanded?'截止前推免后公告':'截止前直接净计划']];
main.getRange('E4').formulas = [[`=COUNTIFS(D${firstData}:D${lastData},"推免后统考公告",Q${firstData}:Q${lastData},"截止前")`]];
main.getRange('G4').values = [['截止后记录']];
main.getRange('H4').formulas = [[`=COUNTIFS(Q${firstData}:Q${lastData},"截止后")`]];
main.getRange('J4').values = [['日期待核记录']];
main.getRange('K4').formulas = [[`=COUNTIFS(Q${firstData}:Q${lastData},"时间待核")`]];
main.getRange('A5').values = [['空白不是零。I列仅为算术差额，须结合J列专项口径；拟接收推免不参与该差额计算。']];
main.getRange('A5').format.font = {name:'Arial', size:10, color:'#7A4D18'};
if(expanded){
  main.getRange('A6').values=[['候选机读值另表；日期为空不等于截止后，原图抓取只证明当次可见；2027尚未到报名截止，未改正式模型。']];
  main.getRange('A6').format.font={name:'Arial',size:10,color:'#5A6876'};
}
main.getRange(`A7:${endCol}7`).values = [headers];
const values = input.records.map(row => [row.school,row.unit,row.year,row.record_kind,row.reported_exam_quota,
    row.total_plan_same_scope,row.accepted_recommended,row.planned_recommended,null,row.special_scope,
    dateValue(row.effective_publish_date),row.publication_precision==='minute'?'时分':'日期',
    dateValue(row.total_plan_publish_date),dateValue(row.accepted_recommended_publish_date),dateValue(row.exam_quota_publish_date),
    dateValue(row.registration_deadline),null,row.usability,row.notes,row.primary_source_url,
    row.supporting_urls.join('\n'),row.source_locator,row.source_ids.join('; '),row.source_sha256.join('; '),
    ...(expanded?[row.review_status,row.source_grade,row.study_mode,dateValue(row.capture_time),row.available_by_deadline===true?'当次抓取或公告时间支持':row.available_by_deadline===false?'截止后':'仍待核定',row.availability_basis,dateValue(row.nominal_notice_publish_date),row.publication_date_basis,dateValue(row.observation_as_of)]:[])]);
main.getRange(`A${firstData}:${endCol}${lastData}`).values = values;
main.getRange(`A7:${endCol}${lastData}`).format.font = {name:'Arial', size:10, color:'#223044'};
main.getRange(`A7:${endCol}${lastData}`).format.verticalAlignment = 'center';
main.getRange(`A7:${endCol}${lastData}`).format.rowHeight = 30;
main.getRange(`A7:${endCol}7`).format = {fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:42};
main.getRange(`E${firstData}:I${lastData}`).setNumberFormat('#,##0');
main.getRange(`C${firstData}:C${lastData}`).setNumberFormat('0');
for (const col of ['K','M','N','O']) main.getRange(`${col}${firstData}:${col}${lastData}`).setNumberFormat('yyyy-mm-dd');
main.getRange(`P${firstData}:P${lastData}`).setNumberFormat('yyyy-mm-dd hh:mm');
for (let index=0; index<input.records.length; index++) {
  const r=firstData+index;
  main.getRange(`I${r}`).formulas = [[`=IF(AND(ISNUMBER(F${r}),ISNUMBER(G${r})),F${r}-G${r},"")`]];
  main.getRange(`Q${r}`).formulas = [[`=IF(K${r}="","时间待核",IF(INT(K${r})<INT(P${r}),"截止前",IF(INT(K${r})>INT(P${r}),"截止后",IF(L${r}="时分",IF(K${r}<=P${r},"截止前","截止后"),"截止当日时刻待核"))))`]];
  if (input.records[index].publication_precision==='minute') main.getRange(`K${r}`).setNumberFormat('yyyy-mm-dd hh:mm');
}
const widths={A:23,B:37,C:9,D:29,E:17,F:17,G:17,H:17,I:21,J:36,K:22,L:11,M:17,N:19,O:19,P:24,Q:24,R:50,S:75,T:90,U:100,V:90,W:50,X:90};
if(expanded) Object.assign(widths,{Y:43,Z:17,AA:14,AB:27,AC:34,AD:65,AE:23,AF:80,AG:27});
for (const [col,width] of Object.entries(widths)) main.getRange(`${col}7:${col}${lastData}`).format.columnWidth=width;
main.getRange(`A${firstData}:D${lastData}`).format.wrapText=true;
main.getRange(`J${firstData}:J${lastData}`).format.wrapText=true;
main.getRange(`R${firstData}:S${lastData}`).format.wrapText=true;
main.getRange(`A${firstData}:${endCol}${lastData}`).format.rowHeight=expanded?60:46;
if(expanded){
  main.getRange(`Y${firstData}:AG${lastData}`).format.wrapText=true;
  main.getRange(`AB${firstData}:AB${lastData}`).setNumberFormat('yyyy-mm-dd hh:mm');
  main.getRange(`AE${firstData}:AE${lastData}`).setNumberFormat('yyyy-mm-dd');
  main.getRange(`AG${firstData}:AG${lastData}`).setNumberFormat('yyyy-mm-dd hh:mm');
}
main.getRange(`I${firstData}:I${lastData}`).format.fill=muted;
main.getRange(`Q${firstData}:Q${lastData}`).conditionalFormats.add('containsText',{text:'截止后',format:{fill:'#FCE9E6',font:{color:'#9B2C2C'}}});
main.getRange(`Q${firstData}:Q${lastData}`).conditionalFormats.add('containsText',{text:'待核',format:{fill:'#FFF2D5',font:{color:'#845B15'}}});
main.getRange(`H${firstData}:H${lastData}`).conditionalFormats.add('cellIs',{operator:'greaterThanOrEqual',formula:0,format:{fill:'#FFF2D5'}});
main.freezePanes.freezeRows(7); main.freezePanes.freezeColumns(2);
const mainTable=main.tables.add(`A7:${endCol}${lastData}`,true,'QuotaEvidence');
mainTable.showFilterButton=true;

function flatTable(sheet, header, rows, name, columnWidths) {
  sheet.showGridLines=false;
  const end=String.fromCharCode(64+header.length);
  sheet.getRange(`A1:${end}${rows.length+1}`).values=[header,...rows];
  sheet.getRange(`A1:${end}${rows.length+1}`).format.font={name:'Arial',size:10,color:'#223044'};
  sheet.getRange(`A1:${end}${rows.length+1}`).format.verticalAlignment='center';
  sheet.getRange(`A1:${end}${rows.length+1}`).format.rowHeight=27;
  sheet.getRange(`A1:${end}1`).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:40};
  columnWidths.forEach((width,index)=>sheet.getRange(`${String.fromCharCode(65+index)}1:${String.fromCharCode(65+index)}${rows.length+1}`).format.columnWidth=width);
  sheet.freezePanes.freezeRows(1);
  sheet.tables.add(`A1:${end}${rows.length+1}`,true,name).showFilterButton=true;
}
flatTable(calendar,['入学年','正式报名开始','正式报名截止（北京时间）','预报名开始','预报名结束','官方时间来源','来源SHA256'],
    input.calendars.map(row=>[row.year,dateValue(row.registration_start),dateValue(row.registration_deadline),dateValue(row.pre_registration_start),dateValue(row.pre_registration_end),row.source_url,row.source_sha256]),
    'RegistrationDeadlines',[11,25,30,19,19,105,80]);
calendar.getRange('B2:C7').setNumberFormat('yyyy-mm-dd hh:mm');
calendar.getRange('D2:E7').setNumberFormat('yyyy-mm-dd');
if(!expanded) flatTable(gaps,['学校','入学年','本轮证据记录数','截止前直接净计划记录数','缺口状态','报名截止（北京时间）'],
    input.coverage.map(row=>[row.school,row.year,row.reviewed_records,row.before_deadline_net_records,row.coverage_status,dateValue(row.registration_deadline)]),
    'QuotaCoverageGaps',[25,11,22,28,65,28]);
if(!expanded) gaps.getRange(`F2:F${input.coverage.length+1}`).setNumberFormat('yyyy-mm-dd hh:mm');
if(expanded){
  flatTable(gaps,['学校','入学年','已登记核对记录数','机读候选记录数','全日制总计划记录数','全日制实际推免记录数','全日制直接公招记录数','截止前核对记录数','严格普通净额记录数','仍缺字段','覆盖状态','报名截止（北京）'],input.coverage.map(r=>[r.school,r.year,r.checked_records,r.rule_extracted_records,r.fulltime_total_plan_records,r.fulltime_actual_recommended_records,r.fulltime_direct_exam_plan_records,r.before_deadline_checked_records,r.strict_ordinary_net_records,r.missing_fields,r.coverage_status,dateValue(r.registration_deadline)]),'QuotaCoverageGaps',[24,10,21,21,22,24,24,23,22,110,62,27]);
  gaps.getRange(`L2:L${input.coverage.length+1}`).setNumberFormat('yyyy-mm-dd hh:mm');
  gaps.getRange(`J2:K${input.coverage.length+1}`).format.wrapText=true;
  const review=wb.worksheets.add('机读待核候选');
  flatTable(review,['学校','入学年','单位线索（未汇总）','机读类型','统考列读值','总计划列读值','实际推免列读值','拟推免列读值','未分类计划数','未分类推免数','未分类数字','同一行原文数字列','公开证据日','报名截止','相对截止时间','复核状态','来源URL','原文定位','证据ID','原件SHA256'],reviewRecords.map(r=>[r.school,r.year,r.unit,r.record_kind,r.reported_exam_quota,r.total_plan_same_scope,r.accepted_recommended,r.planned_recommended,r.unclassified_plan_count,r.unclassified_recommended_count,r.unclassified_numeric_count,(r.raw_numeric_cells||[]).join(' / '),dateValue(r.effective_publish_date),dateValue(r.registration_deadline),r.deadline_timing,r.review_status,r.primary_source_url,r.source_locator,r.source_ids.join('; '),r.source_sha256.join('; ')]),'QuotaReaderCandidates',[23,10,43,44,16,18,22,20,20,20,18,28,22,27,27,43,105,110,48,90]);
  review.getRange(`M2:M${reviewRecords.length+1}`).setNumberFormat('yyyy-mm-dd');
  review.getRange(`N2:N${reviewRecords.length+1}`).setNumberFormat('yyyy-mm-dd hh:mm');
  review.getRange(`A2:D${reviewRecords.length+1}`).format.wrapText=true;
  review.getRange(`O2:P${reviewRecords.length+1}`).format.wrapText=true;
  review.getRange(`A2:T${reviewRecords.length+1}`).format.rowHeight=44;
  const roster=wb.worksheets.add('名录脱敏计数');
  const rosterRows=JSON.parse(await fs.readFile(path.join(root,`output/research/${batch}/recommended_roster_counts.json`),'utf8'));
  flatTable(roster,['学校','入学年','025200跨单位计数','逐行明确全日制计数','学习形式未明计数','未取得同一行编号的行数','公开证据日','复核状态','计数方法','汇总口径（勿直接扣减）','来源URL','原件SHA256'],rosterRows.map(r=>[r.school,r.year,r.all_modes_count,r.explicit_fulltime_count,r.mode_unknown_count,r.target_rows_without_same_row_identifier,dateValue(r.effective_publish_date),r.review_status,r.counting_method,r.aggregation_scope,r.source_url,r.source_sha256]),'RecommendationRosterCounts',[24,11,25,27,26,33,22,70,70,80,105,90]);
  roster.getRange(`G2:G${rosterRows.length+1}`).setNumberFormat('yyyy-mm-dd');
  roster.getRange(`H2:J${rosterRows.length+1}`).format.wrapText=true;
  roster.getRange(`A2:L${rosterRows.length+1}`).format.rowHeight=48;
}
gaps.freezePanes.freezeColumns(1);

// Verify live boundary logic and missing-versus-zero behavior, restoring inputs.
const probe=firstData;
const savedDate=main.getRange(`K${probe}`).values;
const savedPrecision=main.getRange(`L${probe}`).values;
const savedDeadline=main.getRange(`P${probe}`).values;
main.getRange(`P${probe}`).values=[[dateValue('2026-10-24T22:00:00+08:00')]];
main.getRange(`L${probe}`).values=[['日期']];
main.getRange(`K${probe}`).values=[[dateValue('2026-10-24')]];
if(main.getRange(`Q${probe}`).values[0][0]!=='截止当日时刻待核') throw new Error('Same-day unknown-time guard failed');
main.getRange(`L${probe}`).values=[['时分']];
main.getRange(`K${probe}`).values=[[dateValue('2026-10-24T22:01:00')]];
if(main.getRange(`Q${probe}`).values[0][0]!=='截止后') throw new Error('After-22:00 guard failed');
main.getRange(`K${probe}`).values=savedDate;
main.getRange(`L${probe}`).values=savedPrecision;
main.getRange(`P${probe}`).values=savedDeadline;
wb.recalculate();
const actualTiming=main.getRange(`Q${firstData}:Q${lastData}`).values.flat();
for(let index=0;index<actualTiming.length;index++) {
  if(actualTiming[index]!==input.records[index].deadline_timing) throw new Error(`Python/Excel date boundary mismatch at ${index}`);
}
const actualDiffs=main.getRange(`I${firstData}:I${lastData}`).values.flat();
for(let index=0;index<actualDiffs.length;index++) {
  const expected=input.records[index].total_less_accepted;
  if(expected===null ? !['',null].includes(actualDiffs[index]) : actualDiffs[index]!==expected) throw new Error(`Quota subtraction mismatch at ${index}`);
}
console.log((await wb.inspect({kind:'table',range:'名额记录!A4:K4',include:'values,formulas',tableMaxRows:1,tableMaxCols:11,maxChars:1800})).ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'formula error scan'});
console.log(errors.ndjson);
console.log('Exporting verified workbook');
const result=await SpreadsheetFile.exportXlsx(wb);
const target=path.join(outputDir,expanded?'应用统计_报名截止可见名额_扩充审计版_20261023_r2.xlsx':'应用统计_历年推免后统考名额与报名截止时间_20261023.xlsx');
await result.save(target);
console.log(JSON.stringify({output:target,records:input.records.length,temporalChecks:'passed',subtractionChecks:'passed'}));
if(process.argv.includes('--skip-native-render')) process.exit(0);
for (const [sheetName,range,file] of [['名额记录','A1:J15','quota-main.png'],['年度报名截止','A1:E7','quota-calendar.png'],['覆盖缺口','A1:F15','quota-gaps.png']]) {
  console.log('Rendering '+sheetName+' '+range);
  try {
    const preview=await wb.render({sheetName,range,scale:1,format:'png'});
    await fs.writeFile(path.join(qaDir,file),new Uint8Array(await preview.arrayBuffer()));
    console.log('Rendered '+file);
  } catch(error) {
    console.error('Rendering failed: '+(error?.stack||String(error)));
    throw error;
  }
}
