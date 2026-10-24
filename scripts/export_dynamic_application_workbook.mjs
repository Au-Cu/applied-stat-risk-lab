// Execute a copy from a task-specific directory linked to the bundled runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const root=process.argv[2];
if(!root) throw new Error('Pass repository root');
const batch='dynamic_applications_20261024';
const data=JSON.parse(await fs.readFile(path.join(root,`output/research/${batch}/dynamic_application_ratios.json`),'utf8'));
const rawCsv=await fs.readFile(path.join(root,`output/research/${batch}/all_screenshot_rows.csv`),'utf8');
// CSV contains no quoted newlines in these source observations.
function csvLine(line){
  const fields=[];let value='',quoted=false;
  for(let i=0;i<line.length;i++){
    const c=line[i];
    if(c==='"'){if(quoted&&line[i+1]==='"'){value+='"';i++;}else quoted=!quoted;}
    else if(c===','&&!quoted){fields.push(value);value='';}else value+=c;
  }
  fields.push(value);return fields;
}
const [csvHeader,...csvBody]=rawCsv.replace(/^\uFEFF/,'').trimEnd().split(/\r?\n/).map(csvLine);
const raw=csvBody.map(row=>Object.fromEntries(csvHeader.map((h,i)=>[h,row[i]])));
const outputDir=path.join(root,'outputs/01a16d0a-2259-7f81-83bd-386bf6febbfb');
const qaDir=path.join(root,'work/dynamic-applications-workbook-20261024');
await fs.mkdir(outputDir,{recursive:true});await fs.mkdir(qaDir,{recursive:true});
const wb=Workbook.create();
const main=wb.worksheets.add('动态样本报录比');
const cover=wb.worksheets.add('81校覆盖');
const quotas=wb.worksheets.add('统考名额来源');
const observations=wb.worksheets.add('截图原始记录');
const navy='#293F58', ink='#243448', muted='#F0F3F7', amber='#FFF2D5';
const first=8,last=first+data.records.length-1,qFirst=5,qLast=qFirst+data.quotas.length-1,rawLast=raw.length+1;
const qRange=col=>`'统考名额来源'!$${col}$${qFirst}:$${col}$${qLast}`;
const date=v=>v?new Date(v.replace(/\+08:00$/,'').replace(/Z$/,'')+(v.includes('T')?'':'T00:00:00')+'Z'):null;
const basis={post_recommendation_notice:'原文单列统考',explicit_exam_catalogue:'目录拟统考',
  total_less_actual_recommended:'总计划减已接收推免',official_fixed_difference:'官方固定差额'};

function table(sheet,headers,rows,top,name,widths){
  const end=String.fromCharCode(64+headers.length),bottom=top+rows.length;
  sheet.showGridLines=false;
  sheet.getRange(`A${top}:${end}${bottom}`).values=[headers,...rows];
  sheet.getRange(`A${top}:${end}${bottom}`).format={font:{name:'Arial',size:10,color:ink},rowHeight:30,verticalAlignment:'center'};
  sheet.getRange(`A${top}:${end}${top}`).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:40,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
  widths.forEach((width,i)=>sheet.getRange(`${String.fromCharCode(65+i)}${top}:${String.fromCharCode(65+i)}${bottom}`).format.columnWidth=width);
  sheet.tables.add(`A${top}:${end}${bottom}`,true,name).showFilterButton=true;
  sheet.freezePanes.freezeRows(top);
  return bottom;
}
function title(sheet,text){
  sheet.getRange('A2').values=[[text]];
  sheet.getRange('A2').format={font:{name:'Arial',size:14,bold:true,color:navy},rowHeight:24};
}

// Original observations stay separate from the selected unit results.
table(observations,['原排名','学校原文','院系/方向原文','平台人数（人）','截图页','目标81校','重复单位标签','截图SHA256'],
  raw.map(r=>[Number(r.rank),r.school_raw,r.unit_raw,Number(r.observed_applicants),Number(r.screenshot_page),r.is_target_school==='True'?'是':'否',r.duplicate_unit_label==='True'?'是':'否',r.screenshot_sha256]),1,
  'ScreenshotObservations',[10,25,45,15,10,13,16,73]);
observations.getRange(`A2:A${rawLast}`).setNumberFormat('0');
observations.getRange(`D2:E${rawLast}`).setNumberFormat('0');
observations.freezePanes.freezeColumns(2);
observations.getRange('J1').values=[['截图时钟16:30，日期按用户2026-10-24提交日登记。原图另存，公开哈希。']];
observations.getRange('J1:J8').format={font:{name:'Arial',size:10,color:'#5C6877'},columnWidth:120,wrapText:false};
observations.getRange('J3').values=[['原始重复标签照录：东北财经大学统计学院在排名6、89各有一条，不合并。']];
observations.getRange(`G2:G${rawLast}`).conditionalFormats.add('containsText',{text:'是',format:{fill:amber}});

title(quotas,'统考名额与可审计来源');
quotas.getRange('A3').values=[['实际已接收推免与拟推免分列。原文已列统考计划的，不再扣推免。']];
quotas.getRange('A3').format.font={name:'Arial',size:10,color:'#5C6877'};
table(quotas,['名额证据ID','学校','对应招生单位','入学年','总计划（人）','已接收推免（人）','拟推免（人）','原文统考列（人）','采用分母（人）','计算方式','发布时间（北京）','采集可见时间（北京）','专项/项目范围','原文定位','名额阶段','日期说明'],
  data.quotas.map(q=>[q.quota_id,q.school,q.unit,q.year,q.total_plan,q.accepted_recommended,q.planned_recommended,
    q.quota_basis==='official_fixed_difference'?null:q.stated_exam_quota,null,basis[q.quota_basis],date(q.publication_date),date(q.captured_at),q.ordinary_scope,q.source_locator,q.quota_stage,q.publication_date_basis]),qFirst-1,
  'RecommendationExcludedQuotas',[34,24,40,10,13,17,15,17,15,28,24,27,55,115,43,100]);
for(let i=0;i<data.quotas.length;i++){
  const r=qFirst+i;
  quotas.getRange(`I${r}`).formulas=[[
    `=IF(J${r}="官方固定差额",IF(AND(ISNUMBER(E${r}),ISNUMBER(G${r})),E${r}-G${r},""),IF(ISNUMBER(H${r}),H${r},IF(AND(J${r}="总计划减已接收推免",ISNUMBER(E${r}),ISNUMBER(F${r})),E${r}-F${r},"")))`
  ]];
}
quotas.getRange(`D${qFirst}:I${qLast}`).setNumberFormat('0');
quotas.getRange(`K${qFirst}:L${qLast}`).setNumberFormat('yyyy-mm-dd hh:mm');
data.quotas.forEach((q,i)=>{if(q.publication_date&&!q.publication_date.includes('T'))quotas.getRange(`K${qFirst+i}`).setNumberFormat('yyyy-mm-dd');});
quotas.getRange(`I${qFirst}:I${qLast}`).format.fill=muted;
quotas.getRange(`G${qFirst}:G${qLast}`).format.font.color='#8A5B10';
quotas.freezePanes.freezeColumns(2);
quotas.getRange('R4:U4').values=[['官方来源URL','配套证据URL','原件SHA256','备注']];
quotas.getRange(`R4:U${qLast}`).format={font:{name:'Arial',size:10,color:'#5C6877'},wrapText:false,rowHeight:30};
quotas.getRange(`R${qFirst}:U${qLast}`).values=data.quotas.map(q=>[q.source_urls[0],q.source_urls.slice(1).join(' '),q.source_sha256.join(' '),q.notes]);
for(const [c,w] of [['R',130],['S',130],['T',130],['U',165]])quotas.getRange(`${c}4:${c}${qLast}`).format.columnWidth=w;

title(main,'应用统计动态样本报录比');main.tabColor=navy;
main.getRange('A3').values=[['2026-10-24提交的25页截图，显示时钟16:30。分母优先2027，缺失时标注回退2026。']];
main.getRange('A3').format.font={name:'Arial',size:10,color:'#5C6877'};
main.getRange('A4:H4').values=[['目标记录',null,'可计算',null,'2027名额',null,'2026回退',null]];
main.getRange('B4').formulas=[[`=COUNTA(A${first}:A${last})`]];
main.getRange('D4').formulas=[[`=COUNT(G${first}:G${last})`]];
main.getRange('F4').formulas=[[`=COUNTIFS(F${first}:F${last},2027,G${first}:G${last},">=0",G${first}:G${last},"<>")`]];
main.getRange('H4').formulas=[[`=COUNTIFS(F${first}:F${last},2026,G${first}:G${last},">=0",G${first}:G${last},"<>")`]];
main.getRange('A4:H4').format={font:{name:'Arial',size:10,bold:true,color:ink},rowHeight:25};
main.getRange('A5').values=[['比值=平台人数÷排除推免的统考计划。各校漏报比例相同尚待验证，不能换算录取概率。']];
main.getRange('A5').format.font={name:'Arial',size:10,color:'#865F20'};
table(main,['学校','院系/方向/校区','派系','平台人数（人）','统考分母（人）','名额年份','样本报录比（∶1）','名额状态','分母证据性质','专项/项目口径','名额证据ID','截图页','截图原排名'],
  data.records.map(r=>[r.school,r.unit,r.faction,null,null,null,null,null,r.denominator_evidence,r.quota_scope,r.quota_id, r.screenshot_page,r.source_rank]),first-1,
  'DynamicSampleApplicationRatios',[24,38,11,14,14,11,16,25,38,55,34,11,14]);
for(let i=0;i<data.records.length;i++){
  const r=first+i;
  main.getRange(`D${r}`).formulas=[[`=IF(COUNTIF('截图原始记录'!$A$2:$A$${rawLast},M${r})=1,INDEX('截图原始记录'!$D$2:$D$${rawLast},MATCH(M${r},'截图原始记录'!$A$2:$A$${rawLast},0)),NA())`]];
  main.getRange(`E${r}`).formulas=[[`=IF(K${r}="","",IF(COUNTIF(${qRange('A')},K${r})=1,INDEX(${qRange('I')},MATCH(K${r},${qRange('A')},0)),NA()))`]];
  main.getRange(`F${r}`).formulas=[[`=IF(K${r}="","",INDEX(${qRange('D')},MATCH(K${r},${qRange('A')},0)))`]];
  main.getRange(`G${r}`).formulas=[[`=IF(AND(ISNUMBER(D${r}),ISNUMBER(E${r}),E${r}>0),D${r}/E${r},"")`]];
  main.getRange(`H${r}`).formulas=[[`=IF(K${r}="","缺少统考分母",IF(ISNUMBER(E${r}),IF(E${r}>0,IF(F${r}=2027,"2027名额","2026回退"),"统考计划为零，无法比"),"待核统考分母"))`]];
}
main.getRange(`D${first}:F${last}`).setNumberFormat('0');
main.getRange(`G${first}:G${last}`).setNumberFormat('0.00');
main.getRange(`D${first}:G${last}`).format.horizontalAlignment='right';
main.getRange(`E${first}:G${last}`).format.fill=muted;
main.getRange(`H${first}:H${last}`).conditionalFormats.add('containsText',{text:'回退',format:{fill:amber,font:{color:'#865F20'}}});
main.getRange(`H${first}:H${last}`).conditionalFormats.add('containsText',{text:'缺少',format:{fill:'#F8E8E5',font:{color:'#925044'}}});
main.getRange(`I${first}:I${last}`).conditionalFormats.add('containsText',{text:'预计',format:{fill:amber}});
main.freezePanes.freezeColumns(2);
main.getRange('O7').values=[['口径说明']];
main.getRange(`O7:O${last}`).format={font:{name:'Arial',size:10,color:'#5C6877'},columnWidth:170,wrapText:false};
main.getRange(`O${first}:O${last}`).values=data.records.map(r=>[r.notes]);

title(cover,'原表81所目标院校的覆盖情况');
cover.getRange('A3').values=[['观察单元为0表示截图未出现，不表示该校零报名。各学院分母不能重复套用全校合计。']];
cover.getRange('A3').format.font={name:'Arial',size:10,color:'#5C6877'};
const cFirst=6,cLast=cFirst+data.school_coverage.length-1;
table(cover,['学校','派系','截图观察单元数','2027分母单元数','2026回退单元数','可计算单元数','仍缺分母单元数','覆盖情况'],
  data.school_coverage.map(r=>[r.school,r.faction,null,null,null,null,null,null]),cFirst-1,
  'TargetSchoolCoverage',[26,12,19,20,20,18,21,50]);
for(let i=0;i<data.school_coverage.length;i++){
  const r=cFirst+i,schools=`'动态样本报录比'!$A$${first}:$A$${last}`,years=`'动态样本报录比'!$F$${first}:$F$${last}`,ratios=`'动态样本报录比'!$G$${first}:$G$${last}`;
  cover.getRange(`C${r}`).formulas=[[`=COUNTIF(${schools},A${r})`]];
  cover.getRange(`D${r}`).formulas=[[`=COUNTIFS(${schools},A${r},${years},2027,${ratios},">=0",${ratios},"<>")`]];
  cover.getRange(`E${r}`).formulas=[[`=COUNTIFS(${schools},A${r},${years},2026,${ratios},">=0",${ratios},"<>")`]];
  cover.getRange(`F${r}`).formulas=[[`=D${r}+E${r}`]];
  cover.getRange(`G${r}`).formulas=[[`=C${r}-F${r}`]];
  cover.getRange(`H${r}`).formulas=[[`=IF(C${r}=0,"本次未观察到，不能记零",IF(G${r}=0,"全部观察单元有可用分母","仍缺部分或全部分母"))`]];
}
cover.getRange(`C${cFirst}:G${cLast}`).setNumberFormat('0');
cover.freezePanes.freezeColumns(1);

// Recalculation tests temporarily edit sources, then restore every original value.
const eq=(actual,expected,label)=>{if(expected===null? !['',null].includes(actual): typeof actual==='number'&&typeof expected==='number'?Math.abs(actual-expected)>1e-9:actual!==expected)throw new Error(`${label}: ${actual} != ${expected}`);};
const ecnuQ=qFirst+data.quotas.findIndex(q=>q.quota_id==='ecnu_2027_ordinary');
const ecnuR=first+data.records.findIndex(r=>r.source_rank===29);
const rawEcnuRow=30;
const get=(s,cell)=>s.getRange(cell).values[0][0];
wb.recalculate();
eq(get(main,`G${ecnuR}`),85/38,'ECNU initial');
quotas.getRange(`G${ecnuQ}`).values=[[60]];wb.recalculate();
eq(get(main,`G${ecnuR}`),85/37,'Changed recommendation plan under fixed official difference');
quotas.getRange(`G${ecnuQ}`).values=[[59]];
observations.getRange(`D${rawEcnuRow}`).values=[[90]];wb.recalculate();
eq(get(main,`G${ecnuR}`),90/38,'Changed platform count');
observations.getRange(`D${rawEcnuRow}`).values=[[85]];
const simpleQ=qFirst+data.quotas.findIndex(q=>q.quota_id==='uibe_2027_ordinary');
const simpleR=first+data.records.findIndex(r=>r.source_rank===12);
quotas.getRange(`H${simpleQ}`).values=[[0]];wb.recalculate();
eq(get(main,`G${simpleR}`),null,'Zero denominator stays unavailable');
eq(get(main,'D4'),data.summary.ratio_records-1,'Summary reacts to zero denominator');
quotas.getRange(`H${simpleQ}`).values=[[null]];wb.recalculate();
eq(get(main,`E${simpleR}`),null,'Blank input remains blank');
eq(get(main,`G${simpleR}`),null,'Blank denominator stays unavailable');
quotas.getRange(`H${simpleQ}`).values=[[52]];wb.recalculate();
const savedKey=main.getRange(`K${simpleR}`).values;
main.getRange(`K${simpleR}`).values=[['missing-quota-key']];wb.recalculate();
eq(get(main,`E${simpleR}`),'#N/A','Invalid key remains visible');
main.getRange(`K${simpleR}`).values=savedKey;wb.recalculate();
data.records.forEach((r,i)=>{eq(get(main,`D${first+i}`),r.observed_applicants,`Count rank ${r.source_rank}`);eq(get(main,`E${first+i}`),r.net_exam_quota,`Denominator rank ${r.source_rank}`);eq(get(main,`G${first+i}`),r.sample_dynamic_ratio,`Ratio rank ${r.source_rank}`);});
data.school_coverage.forEach((r,i)=>{eq(get(cover,`C${cFirst+i}`),r.observed_units,`Coverage ${r.school}`);eq(get(cover,`F${cFirst+i}`),r.units_with_ratio,`Ratio coverage ${r.school}`);});
eq(get(main,'D4'),data.summary.ratio_records,'Total calculated');
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'final formula error scan'});
await fs.writeFile(path.join(qaDir,'formula-scan.ndjson'),errors.ndjson);
console.log(errors.ndjson);
const target=path.join(outputDir,'应用统计_985211动态样本报录比_20261024_1630.xlsx');
await(await SpreadsheetFile.exportXlsx(wb)).save(target);
await fs.writeFile(path.join(qaDir,'calculation-qa.json'),JSON.stringify({status:'passed',ratios:data.summary.ratio_records,all_target_records:data.records.length,engine:'artifact-tool',native_excel_automation_tested:false,tests:['source numerator update','fixed difference recommendation update','zero denominator','blank denominator','invalid key','all Python/Excel ratios','all school coverage'],output:target},null,2));
console.log(JSON.stringify({output:target,calculationQA:'passed'}));
if(process.argv.includes('--skip-native-render'))process.exit(0);
for(const [sheetName,range,file] of [['动态样本报录比','A1:I15','ratios.png'],['统考名额来源','B1:J13','quota-sources.png'],['截图原始记录','A1:G13','raw.png'],['81校覆盖','A1:H17','coverage.png']]){
  const png=await wb.render({sheetName,range,scale:1.4,format:'png'});
  await fs.writeFile(path.join(qaDir,file),new Uint8Array(await png.arrayBuffer()));
  console.log('Rendered '+file);
}
