"""Extend the frozen first batch with auditable aggregate observations.

Rules read explicit column labels only. Search hits, unknown counts and planned
recommendation are never promoted to verified post-recommendation net quotas.
The production model and its frozen numerical files are not touched.
"""
from __future__ import annotations
import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
RESEARCH=ROOT/'data/research/quota_deadline_20261023_r2'
OUT=ROOT/'output/research/quota_deadline_20261023_r2'
SNAP=OUT/'snapshots'
BASE=ROOT/'output/research/quota_deadline_20261023/quota_deadline_dataset.json'
TZ=ZoneInfo('Asia/Shanghai')
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(ROOT/'scripts'))
from build_quota_deadline_dataset import timing,export_csv as _export_csv
from public_quota_urls import public_url,public_error


def export_csv(path,rows,fields=None):
    _export_csv(path,rows,fields)
    # Quoted source/error fields may themselves contain LF. Use consistent LF
    # record endings so Git does not retain a mixed CRLF/LF file as whitespace.
    path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))


def count(value):
    text=re.sub(r'\s+','',str(value))
    return int(text) if re.fullmatch(r'\d{1,4}',text) and int(text)<=2000 else None


def compact(text):
    return re.sub(r'[ \t\xa0]+',' ',text)


def intake_year(meta,text):
    # The main document title outranks a navigation menu containing this year's
    # links. An explicitly old article must not become a 2027 observation.
    for candidate in [str(meta.get('document_title') or ''),str(meta.get('title') or '')]:
        article_years=re.findall(r'(20\d{2})\s*[年级]',candidate)
        if article_years:
            year=int(article_years[0])
            return year if 2022<=year<=2027 else None
    for candidate in [text[:1400]]:
        hits=re.findall(r'(202[2-7])\s*[年级](?!\s*\d+\s*月)[^\n。；]{0,22}(?:硕士|研究生|统考|推免)',candidate)
        if hits:
            return int(hits[0])
    match=re.search(r'/(?:sszs_|sszyml/|zyml/|sszsml/(?:index/)?)(202[2-7])(?:/|_)',meta['url'])
    if match:
        return int(match.group(1))
    # The manifest hint came from an explicit notice title, not a URL date.
    if meta.get('year') in range(2022,2028) and re.search(r'202[2-7]',str(meta.get('title',''))):
        return meta['year']
    return None


def publication(meta,meta_by_id,text):
    match=re.search(r'(?:发布时间|发布日期|发文时间|发布于|(?:^|\n)\s*时间)\s*[：:]?\s*(20\d{2})[年/.-]\s*(\d{1,2})[月/.-]\s*(\d{1,2})日?(?:\s+(\d{1,2}):(\d{2}))?',text[:5000])
    if match:
        year,month,day,hour,minute=match.groups()
        try:
            stamp=datetime(int(year),int(month),int(day),int(hour or 0),int(minute or 0))
            return stamp.isoformat(timespec='minutes') if hour else stamp.date().isoformat(),'minute' if hour else 'date','正文明确发布时间'
        except ValueError:
            pass
    parent=meta_by_id.get(meta.get('parent_id'))
    if parent and re.search(r'\.(?:pdf|xlsx?)($|\?)',meta['url'],re.I):
        if re.search(r'硕士|推免|统考|目录|计划',str(parent.get('title',''))) and not re.search(r'首页|列表|通知公告|信息公开$',str(parent.get('title',''))):
            parent_text_path=SNAP/f"{parent['id']}.txt"
            if parent_text_path.exists():
                value=publication({**parent,'parent_id':None},meta_by_id,compact(parent_text_path.read_text(encoding='utf-8')))
                if value[0]:
                    # A catalogue attachment explicitly named 20240226上网 is
                    # a later version even if its parent notice dates to Oct.
                    version=re.search(r'(20\d{2})([01]\d)([0-3]\d)[^\n]{0,15}(?:上网|版|更新|修订)',str(meta.get('title','')))
                    if version:
                        try:
                            version_date=datetime(*map(int,version.groups())).date().isoformat()
                            if version_date>value[0][:10]:
                                return version_date,'date','附件名称明确的较晚版本日期；不能沿用旧公告日期'
                        except ValueError:
                            pass
                    return value[0],value[1],'配套官方公告明确发布时间；附件版本仍待复核'
    return None,'date','未确认，不使用抓取时间或URL日期冒充发布日期'


def normalise_unit(value):
    return re.sub(r'\s+','',str(value)).lstrip('0123456789')


def infer_columns(headers,row,context,document_title=''):
    """Do not align ragged rows by guessing missing rowspan positions."""
    if len(headers)!=len(row) or any(len(str(cell))>80 for cell in headers):
        return {}
    values={}
    post_recommended=bool(re.search(r'扣除.{0,16}推免.{0,12}(?:计划|招生)',context))
    actual_recommended=bool(re.search(r'已接收推免|推免.{0,15}接收情况|拟录取.{0,8}推免|推免.{0,6}拟录取|接收推免硕士研究生人数统计',document_title))
    for header,cell in zip(headers,row):
        number=count(cell)
        if number is None:
            continue
        label=re.sub(r'\s+','',header)
        if re.search(r'代码|学费|单科|分数|总分|分值|最低分|最高分|成绩|学制|比例|年份|直博|博士',label):
            continue
        if re.search(r'报名|报考',label):
            continue
        quantity_label=bool(re.search(r'招生人数|拟招生人数|拟招人数|拟招收人数|拟招生数|招生规模|招生计划|总人数|总计划',label))
        if quantity_label and re.search(r'(?:不含|不包括|已扣除|扣除).{0,8}推免',label):
            values['reported_exam_quota']=number
            continue
        if quantity_label and re.search(r'(?:含|包含|包括).{0,8}推免',label):
            values['total_plan_same_scope']=number
            continue
        if re.search(r'录取.{0,6}(?:含|包括)推免',label):
            values['actual_all_admitted_count']=number
            continue
        if actual_recommended and re.search(r'录取|接收人数',label) and not re.search(r'计划|预计|报名|报考',label):
            values['accepted_recommended']=number
            continue
        if re.search(r'录取',label) and not re.search(r'推免',label):
            values['actual_exam_admitted_count']=number
            continue
        if re.search(r'统考|统招|公招|公开招考',label) and (re.search(r'计划|人数|名额|公招',label) or label in ['统考','统招','公开招考']):
            values['reported_exam_quota']=number
        elif re.search(r'推免',label):
            if re.search(r'拟接收|拟招|预计|计划',label) and not re.search(r'拟录取|已接收',label):
                values['planned_recommended']=number
            elif re.search(r'已接收|拟录取|推免录取',label) or actual_recommended:
                values['accepted_recommended']=number
            else:
                values['unclassified_recommended_count']=number
        elif re.search(r'总计划|招生总数|拟招总|总人数|拟招生人数|拟招人数|拟招收人数|拟招生数|招生人数|招生数|招生规模|拟招数|招生计划|计划招生|招生名额',label):
            if re.search(r'招生总|总计划|总人数|拟招总|合计|总计',label):
                values['total_plan_same_scope']=number
            elif post_recommended or re.search(r'(?:不含|不包括|已扣除).{0,8}推免',context):
                values['reported_exam_quota']=number
            elif re.search(r'(?:含|包含|包括).{0,14}推免',context) or ('推免录取' in ''.join(headers) and '统考计划' in ''.join(headers)):
                values['total_plan_same_scope']=number
            else:
                values['unclassified_plan_count']=number
    return values


def table_headers(table,before_row):
    """Prefer expanded multi-level headers over repeated parent labels."""
    result=[]
    for idx,header in enumerate(table[:min(8,before_row+1)]):
        if idx+1<min(8,before_row) and len(header)==len(table[idx+1]):
            child=table[idx+1]
            looks_like_header=re.search(r'代码|名称|人数|统考|推免|硕士|直博|备注|合计|总计',' '.join(child)) and not any(re.fullmatch(r'\d{3,6}',c.strip()) for c in child)
            if looks_like_header:
                result.append([' / '.join(dict.fromkeys([a,b])) for a,b in zip(header,child)])
        result.append(header)
    return result


def auto_records(metas):
    result=[]
    by_id={row['id']:row for row in metas}
    for meta in metas:
        if meta.get('status')!='ok':
            continue
        text_path=SNAP/f"{meta['id']}.txt"
        if not text_path.exists():
            continue
        text=compact(text_path.read_text(encoding='utf-8'))
        if str(meta.get('snapshot','')).endswith('.html'):
            raw=(ROOT/meta['snapshot']).read_bytes()
            charset=re.search(br'charset\s*=\s*[\x27\x22]?([\w-]+)',raw[:20000],re.I)
            encoding=charset[1].decode('ascii') if charset else 'utf-8'
            document=raw.decode(encoding,errors='replace')
            title=re.search(r'<title[^>]*>(.*?)</title>',document,re.S|re.I)
            if title:
                meta={**meta,'document_title':html.unescape(re.sub('<[^>]+>','',title[1])).strip()}
        if not re.search(r'025200|应用统计',text):
            continue
        # Do not turn individual candidate scores into seat counts.
        if re.search(r'考生编号|准考证号|身份证号|考生姓名',text[:2200]) or re.search(r'名单',str(meta.get('title',''))):
            continue
        year=intake_year(meta,text)
        if year is None and meta.get('parent_id'):
            parent=by_id.get(meta['parent_id'],{})
            # A specific official notice, not a navigation/list page, can
            # identify the intake of a generic attachment title.
            if re.search(r'202[2-7]\s*[年级].{0,18}(?:硕士|研究生|推免|统考)',str(parent.get('title',''))):
                year=intake_year(parent,'')
        if year is None:
            continue
        document_title=str(meta.get('document_title') or meta.get('title') or '')
        # Hosting/reposting a different university's catalogue does not make
        # that university's quotas belong to the hosting target school.
        named_school=re.search(r'([\u4e00-\u9fff]{2,16}大学)\s*202[2-7]\s*年',text[:500])
        if named_school and meta['school'] not in named_school[1] and named_school[1] not in meta['school']:
            continue
        published,precision,date_basis=publication(meta,by_id,text)
        shared={'school':meta['school'],'year':year,'source_ids':[meta['id']],
                'effective_publish_date':published,'publication_precision':precision,
                'publication_date_basis':date_basis,'review_status':'规则读取，待原文复核（未入模）',
                'special_scope':'未逐专业核定专项口径','notes':'保留原文明确列值，不以计划推免冒充实际接收推免；历史值版本另待核。'}
        grids=meta.get('expanded_target_tables',meta.get('target_tables',[]))
        grids+= [t['rows'] for t in meta.get('spreadsheet_target_tables',[])]
        for table_idx,table in enumerate(grids):
            for row_idx,row in enumerate(table):
                joined=' '.join(row)
                if not re.search(r'025200',joined) or '应用统计' not in joined or '非全日制' in joined:
                    continue
                row_values={}
                unit='培养单位待核（未汇总）'
                # CQ explicitly labels all three planned partitions in one cell.
                cq=re.search(r'普通计划\s*[：:]\s*(\d+).*?公招\s*[：:]\s*(\d+).*?推免\s*[：:]\s*(\d+)',joined)
                if cq and meta['school']=='重庆大学':
                    row_values={'total_plan_same_scope':int(cq[1]),'reported_exam_quota':int(cq[2]),'planned_recommended':int(cq[3])}
                    unit='数学与统计学院'
                # USTC's leading seven columns are complete even when the later
                # school-wide direct-PhD cell uses rowspan. Never read that as MAS.
                elif meta['school']=='中国科学技术大学' and len(row)>=7 and '拟接收统考' in ' '.join(table[0]):
                    if count(row[5]) is not None:
                        row_values['reported_exam_quota']=count(row[5])
                    if count(row[6]) is not None:
                        row_values['planned_recommended']=count(row[6])
                    unit=normalise_unit(row[0])
                elif meta['school']=='东华大学' and '已接收推免' in document_title and len(row)>=5:
                    # Official DHU aggregate notice calls its sub-column
                    # 拟招收人数/硕士 even though the notice states 已接收.
                    # This adapter must not be applied to a planned catalogue.
                    if count(row[4]) is not None:
                        row_values={'accepted_recommended':count(row[4])}
                        unit=normalise_unit(row[1])
                else:
                    for header in table_headers(table,row_idx):
                        if re.search(r'人数|计划|名额|拟录取', ' '.join(header)) and re.search(r'专业|代码|名称', ' '.join(header)):
                            row_values=infer_columns(header,row,text[:18000],document_title)
                            if row_values:
                                if header and re.search(r'院系|学院|单位',header[0]) and row and not re.search(r'025200',row[0]):
                                    unit=normalise_unit(row[0]) or unit
                                    if re.search(r'代码',header[0]) and len(row)>1 and re.search(r'学院|学系|研究院|中心|系',row[1]):
                                        unit=normalise_unit(row[1])
                                break
                if unit=='培养单位待核（未汇总）':
                    prior_units=[r[0] for r in table[:row_idx] if r and re.search(r'■\[\d{3}\].{1,30}(?:学院|学系|系)',r[0])]
                    if prior_units:
                        unit=re.sub(r'^.*?\]','',prior_units[-1]).strip()
                if not row_values:
                    continue
                kind='目录明确列值（推免结算状态待核）'
                if any(k in row_values for k in ['actual_exam_admitted_count','actual_all_admitted_count']) and 'reported_exam_quota' not in row_values:
                    kind='事后录取人数对照，非当年招生计划'
                if 'accepted_recommended' in row_values:
                    kind='实际接收推免统计（规则读取待复核）'
                elif 'reported_exam_quota' not in row_values and 'planned_recommended' in row_values:
                    kind='拟接收推免计划，非实际'
                result.append({**shared,**row_values,'unit':unit,'record_kind':kind,
                               'study_mode':'全日制' if '全日制' in joined or ('全日制' in document_title and '非全日制' not in document_title) else '待核',
                               'source_locator':f'HTML表{table_idx+1}行{row_idx+1}：025200应用统计；明确读取列值{json.dumps(row_values,ensure_ascii=False)}'})
        # A high-specificity rule for official school-wide post-recommendation
        # PDFs with complete unit-code, unit-name, major-code and count columns.
        if re.search(r'扣除.{0,16}推免.{0,12}(?:计划|招生)',text[:1800]) and '全日制' in text[:1800]:
            pattern=r'^\s*(\d{3})\s+([^\n\d]{2,40}?)\s+025200\s+应用统计\s+(\d{1,3})(?!\d)'
            for match in re.finditer(pattern,text,re.M):
                result.append({**shared,'unit_code':match[1],'unit':match[2].strip(),
                               'record_kind':'推免后统考公告（规则读取待复核）','reported_exam_quota':int(match[3]),
                               'source_locator':re.sub(r'\s+',' ',match[0]).strip(),
                               'notes':'原文明确扣除拟录取推免后且为全日制；专项及历史发布时间仍待复核，不合并不同学院。'})
        # A conservative transcription layer for PDF catalogues. A number is
        # retained as an UNCLASSIFIED published plan, not silently called a net
        # quota, when the complete table's total/recommendation columns remain
        # ambiguous. This does not read direction 01 or exam subject 101 as seats.
        if str(meta.get('snapshot','')).endswith('.pdf'):
            heading=text[:2600]+' '+str(meta.get('title',''))
            if not re.search(r'招生.{0,8}目录|招生.{0,8}计划|拟招.{0,6}人数|统考.{0,8}计划',heading):
                continue
            if re.search(r'培养方案|年度报告|质量报告|自评报告|工作总结|毕业生招聘|专业评估|复试分数线|初试成绩|复试成绩|复试录取工作|报录统计',heading[:1000]):
                continue
            if re.search(r'港澳台|港、澳、台|外国留学生|国际学生|来华留学|学费|学制标准',document_title):
                continue
            position_path=SNAP/f"{meta['id']}.position.json"
            if position_path.exists():
                positioned=json.loads(position_path.read_text(encoding='utf-8'))
                if positioned['source_sha256']!=meta['sha256']:
                    raise ValueError('Positional derivative has a different original hash')
                for page in positioned['pages']:
                    lines=page['rows']
                    for line_idx,entry in enumerate(lines):
                        line=entry['text']
                        if not re.search(r'025200',line) or '非全' in line:
                            continue
                        cells=[re.sub(r'\s+','',part) for part in line.split(' | ')]
                        target_idx=next((i for i,c in enumerate(cells) if '025200' in c),None)
                        if target_idx is None or not re.search(r'应用统计',''.join(cells[target_idx:target_idx+3])):
                            continue
                        numbers=[int(c) for c in cells[target_idx+1:] if re.fullmatch(r'0|[1-9]\d{0,2}',c) and c not in {'101','201','204','301','303','432'}]
                        if not numbers:
                            continue
                        # These are literal cells, not automatically identified
                        # quota columns. Keep them in a separate review layer.
                        result.append({**shared,'unit':f"PDF第{page['page']}页第{line_idx+1}行培养单位待核",
                                       'record_kind':'坐标恢复待核候选（非名额结论）',
                                       'unclassified_numeric_count':numbers[0], 'raw_numeric_cells':numbers,
                                       'study_mode':'全日制' if '全日制' in re.sub(r'\s+','',line) else '待核',
                                       'source_locator':f"坐标恢复PDF第{page['page']}页第{line_idx+1}行："+line[:650],
                                       'notes':'字符坐标恢复的原文数字单元格；未认定哪列是招生名额，不可直接进入模型。'})
            seen_lines=set()
            for line_number,line in enumerate(text.splitlines(),start=1):
                line=line.strip()
                if not re.search(r'(?<!\d)025200\s*应用统计',line) or '非全日制' in line:
                    continue
                if len(line)>1500:
                    # Font encoding can collapse a whole page into one line.
                    # Keep the source for positional/OCR review, do not guess.
                    continue
                match=re.search(r'(?<!\d)025200\s*应用统计(?:\s*[△▲★*])?(?:\s*[（(]专业学位[）)])?\s+(0|[1-9]\d{0,2})(?=\s|$)',line)
                if not match or match[1] in {'101','201','204','301','303','432'}:
                    continue
                after=line[match.end():].strip()
                if after.startswith(('思想政治','政治理论','英语','数学','统计学')):
                    continue
                unit_match=re.search(r'(\d{3})\s+([^\d\n]{2,45}(?:学院|学系|研究院|中心|系))\s*$',line[:match.start()])
                unit=unit_match[2].strip() if unit_match else f'PDF第{line_number}行培养单位待核'
                literal=(unit,match[1],line)
                if literal in seen_lines:
                    continue
                seen_lines.add(literal)
                # The high-specificity post-recommendation rule already owns
                # this exact complete row; avoid a second, weaker observation.
                if unit_match and re.search(r'扣除.{0,16}推免.{0,12}(?:计划|招生)',heading):
                    continue
                result.append({**shared,'unit':unit,'unit_code':unit_match[1] if unit_match else None,
                               'record_kind':'PDF原文计划列值（总/净口径待核）','unclassified_plan_count':int(match[1]),
                               'source_locator':f'文本转录第{line_number}行：'+line[:650],
                               'notes':'原文计划数转录；未完成全表列头与全日制范围复核，不认作已扣实际推免的统考名额。'})
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    base=json.loads(BASE.read_text(encoding='utf-8'))
    metas=[]
    for path in sorted(SNAP.glob('*.json')):
        if path.name.endswith('.ocr.json'):
            continue
        row=json.loads(path.read_text(encoding='utf-8'))
        if row.get('id'):
            metas.append(row)
    source_map={row['id']:row for row in metas}
    records=[]
    base_sources={source['id']:source for source in base['sources']}
    for old in base['records']:
        row=dict(old)
        row['source_ids']=['r1:'+key for key in row['source_ids']]
        row['evidence_batch']='r1'
        row['review_status']=row['human_review_status']
        row['unclassified_plan_count']=None
        row['unclassified_recommended_count']=None
        row['source_grade']='A-official'
        row['model_eligible']=False
        captures=[base_sources[key]['collected_at'] for key in old['source_ids'] if base_sources.get(key,{}).get('collected_at')]
        row['capture_time']=max(captures) if captures else None
        row['observed_before_deadline']=bool(captures) and all(datetime.fromisoformat(v)<=datetime.fromisoformat(row['registration_deadline']) for v in captures)
        row['available_by_deadline']=True if row['observed_before_deadline'] or row['deadline_timing']=='截止前' else False if row['deadline_timing']=='截止后' else None
        row['availability_basis']='原批次截止前抓取' if row['observed_before_deadline'] else '原批次公告明确日期，历史附件版本仍需审计'
        if '待核' in str(row.get('unit','')) or row.get('unit','').startswith('方向：'):
            row['legacy_unit_parse_raw']=row.get('unit')
            row['unit']='培养单位待核（旧解析需纠正）'
            row['review_status']='历史批次培养单位标记异常，待重新核对（不入模）'
            row['usability']='历史批次原值保留；单位未核定，不纳入全日制项目变量'
        elif (row.get('reported_exam_quota') is not None and row.get('total_less_accepted') is not None
              and row['reported_exam_quota']!=row['total_less_accepted']):
            row['review_status']='历史批次总减推免与直接计划不一致，版本口径待核（不入模）'
            row['usability']='保留两个原文值，不强行使其相等；不视作同版本同口径'
        if row['school']=='中央财经大学' or (row['school']=='厦门大学' and row['year']==2027):
            # Explicit ordinary/special exclusion already audited in frozen R1.
            row['ordinary_scope_verified']=True
        records.append(row)
    curated=json.loads((RESEARCH/'curated_records.json').read_text(encoding='utf-8'))
    candidates=curated+auto_records(metas)
    calendars={row['year']:row for row in base['calendars']}
    seen=set()
    for candidate in candidates:
        ids=candidate['source_ids']
        sources=[source_map[key] for key in ids]
        for source in sources:
            if source['status']!='ok' or hashlib.sha256((ROOT/source['snapshot']).read_bytes()).hexdigest()!=source['sha256']:
                raise ValueError(f"Unusable source capture: {source['id']}")
        row={key:None for key in ['reported_exam_quota','total_plan_same_scope','accepted_recommended','planned_recommended','unclassified_plan_count','unclassified_recommended_count','unclassified_numeric_count','actual_exam_admitted_count','actual_all_admitted_count']}
        row.update(candidate)
        key=(row['school'],row['year'],normalise_unit(row['unit']),row['record_kind'],
             *(row[column] for column in ['reported_exam_quota','total_plan_same_scope','accepted_recommended','planned_recommended','unclassified_plan_count','unclassified_recommended_count']), sources[0]['sha256'],row.get('source_locator'))
        if key in seen:
            continue
        seen.add(key)
        row['record_id']=hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:14]
        row.setdefault('study_mode','全日制')
        row.update({'major_code':'025200','evidence_batch':'r2',
                    'source_grade':sources[0].get('source_grade') or ('A-official' if re.search(r'^https?://[^/]+\.edu\.cn/',sources[0]['url']) else 'B-reprint'),
                    'source_ids':['r2:'+source['id'] for source in sources],
                    'primary_source_url':public_url(sources[0]['url']),'supporting_urls':[public_url(source['url']) for source in sources[1:]],
                    'source_sha256':[source['sha256'] for source in sources],
                    'capture_time':sources[0]['collected_at'],'model_eligible':False,
                    'historical_snapshot_limitation':'现存官方值与日期不等于取得了当年的网页存档；规则读取尚未终审'})
        total,accepted=row['total_plan_same_scope'],row['accepted_recommended']
        row['total_less_accepted']=total-accepted if total is not None and accepted is not None else None
        row['registration_start']=calendars[row['year']]['registration_start']
        row['registration_deadline']=calendars[row['year']]['registration_deadline']
        row['deadline_timing']=timing(row.get('effective_publish_date'),row['registration_deadline'],row.get('publication_precision','date'))
        observed=all(datetime.fromisoformat(source['collected_at'])<=datetime.fromisoformat(row['registration_deadline']) for source in sources)
        row['observed_before_deadline']=observed
        row['available_by_deadline']=True if observed or row['deadline_timing']=='截止前' else False if row['deadline_timing']=='截止后' else None
        row['availability_basis']='本次原文抓取早于截止；不冒充发布日期' if observed else '官方明确发布日期' if row['deadline_timing'] in ['截止前','截止后'] else '历史可见性尚未确认'
        row['total_plan_publish_date']=row.get('total_plan_publish_date') or (row.get('effective_publish_date') if total is not None else None)
        row['accepted_recommended_publish_date']=row.get('accepted_recommended_publish_date') or (row.get('effective_publish_date') if accepted is not None else None)
        row['exam_quota_publish_date']=row.get('exam_quota_publish_date') or (row.get('effective_publish_date') if row.get('reported_exam_quota') is not None else None)
        if row['review_status'].startswith('规则'):
            row['usability']='规则读取未终审，不直接入模'
        elif row.get('study_mode')!='全日制':
            row['usability']='数字已核对，学习形式仍待核定；不作全日制净额'
        elif row['deadline_timing']=='截止后':
            row['usability']='截止后公开或修订版本；不能用于该年报名前回测'
        elif row['available_by_deadline'] is not True:
            row['usability']='公开或附件版本时间未核定；暂不纳入报名截止信息集'
        elif row.get('source_grade')!='A-official':
            row['usability']='转载数值已转录，仍待官网交叉核对，不直接入模'
        else:
            row['usability']='原文数值及可见时点可审计；专项口径与用户终审仍待完成'
        if total is not None and accepted is not None and accepted>total:
            row['notes']+=' 实际推免大于该总计划，存在版本或口径冲突，差额不可当作净名额。'
        records.append(row)
    schools=[row['school'] for row in csv.DictReader((ROOT/'data/processed/schools.csv').open(encoding='utf-8-sig'))]
    coverage=[]
    for school in schools:
        for year in range(2022,2028):
            rows=[row for row in records if row['school']==school and row['year']==year]
            checked=[row for row in rows if not row.get('review_status','').startswith('规则')]
            actual=[row for row in checked if row.get('accepted_recommended') is not None]
            fulltime=[row for row in checked if row.get('study_mode')=='全日制']
            directly_published=[row for row in fulltime if row.get('reported_exam_quota') is not None]
            totals=[row for row in fulltime if row.get('total_plan_same_scope') is not None]
            visible=[row for row in fulltime if row.get('available_by_deadline') is True or row.get('deadline_timing')=='截止前']
            strict_net=[row for row in visible if row.get('record_kind')=='推免后统考公告'
                        and row.get('reported_exam_quota') is not None
                        and (row.get('ordinary_scope_verified') is True or re.search(r'明确不含专项|不含专项计划|已剔除专项',str(row.get('special_scope',''))))
                        and '待核' not in row.get('review_status','')]
            pending=[]
            if not totals: pending.append('缺同口径全日制总计划')
            if not any(row.get('accepted_recommended') is not None for row in fulltime): pending.append('缺全日制实际接收推免')
            if not directly_published: pending.append('缺已核对的直接统考计划')
            if not visible: pending.append('缺截止前可见时间证据或仍待核定学习形式')
            if not strict_net: pending.append('未形成专项口径已核的截止前普通净额')
            coverage.append({'school':school,'year':year,'records':len(rows),'checked_records':len(checked),
                             'actual_recommended_records':len(actual),'rule_extracted_records':len(rows)-len(checked),
                             'fulltime_total_plan_records':len(totals),'fulltime_direct_exam_plan_records':len(directly_published),
                             'fulltime_actual_recommended_records':sum(r.get('accepted_recommended') is not None for r in fulltime),
                             'before_deadline_checked_records':len(visible),'strict_ordinary_net_records':len(strict_net),
                             'missing_fields':'; '.join(pending),
                             'search_status':'已完成本轮逐年官网检索，不代表所有字段已取得',
                             'coverage_status':'已有原文核对数据，口径见明细' if checked else '仅有规则读取数据，尚待原文复核' if rows else '本轮未核到可登记数值，不代表无公开数据',
                             'registration_deadline':calendars[year]['registration_deadline']})
    source_rows=[]
    for source in base['sources']:
        source_rows.append({**source,'id':'r1:'+source['id'],'evidence_batch':'r1'})
        if source.get('parent_id'):
            source_rows[-1]['parent_id']='r1:'+source['parent_id']
    for source in metas:
        source_rows.append({key:source.get(key) for key in ['id','school','year','url','title','parent_id','status','error','sha256','bytes','snapshot','collected_at','pdf_page_count','pdf_target_pages','pdf_extraction_backend','privacy_scope','public_raw_release_allowed']})
        source_rows[-1]['id']='r2:'+source['id']
        source_rows[-1]['evidence_batch']='r2'
        source_rows[-1]['title']=str(source_rows[-1].get('title') or '')[:220]
        source_rows[-1]['url']=public_url(source['url'])
        if source_rows[-1].get('error'):
            source_rows[-1]['error']=public_error(source_rows[-1]['error']) if source_rows[-1]['url'] else 'Non-HTTP link in original page; no publicly retrievable original'
        if source.get('parent_id'):
            source_rows[-1]['parent_id']='r2:'+source['parent_id']
    checked=[r for r in records if not r.get('review_status','').startswith('规则')]
    candidates=[r for r in records if r.get('review_status','').startswith('规则')]
    summary={'as_of_date':max(s.get('collected_at','') for s in source_rows)[:10],'version':'r2-research','target_schools':81,'target_school_years':486,
             'records':len(records),'schools_with_any_registered_value':len({r['school'] for r in records}),
             'school_years_with_any_registered_value':len({(r['school'],r['year']) for r in records}),
             'checked_records':sum(not r.get('review_status','').startswith('规则') for r in records),
             'checked_schools':len({r['school'] for r in checked}),
             'checked_school_years':len({(r['school'],r['year']) for r in checked}),
             'school_years_with_strict_before_deadline_ordinary_net':sum(r['strict_ordinary_net_records']>0 for r in coverage),
             'school_years_missing_strict_ordinary_net':sum(r['strict_ordinary_net_records']==0 for r in coverage),
             'rule_extracted_pending_review':sum(r.get('review_status','').startswith('规则') for r in records),
             'source_status':dict(Counter(r['status'] for r in source_rows)),
             'unique_successful_source_urls':len({s['url'] for s in source_rows if s['status']=='ok'}),
             'unique_successful_source_sha256':len({s.get('sha256') for s in source_rows if s['status']=='ok' and s.get('sha256')}),
             'user_final_review_completed_records':0,
             'frozen_model_changed':False,'note':'检索、原文提及、规则读取及核定净名额是不同层级；不宣称486校年齐全。'}
    payload={'summary':summary,'records':records,'calendars':base['calendars'],'coverage':coverage,'sources':source_rows}
    (OUT/'quota_deadline_dataset.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=list(dict.fromkeys(key for row in records for key in row))
    export_csv(OUT/'quota_records.csv',records,fields)
    export_csv(OUT/'quota_checked_records.csv',checked,fields)
    export_csv(OUT/'quota_review_candidates.csv',candidates,fields)
    export_csv(OUT/'coverage_gaps.csv',coverage)
    export_csv(OUT/'source_snapshot_index.csv',source_rows,list(dict.fromkeys(key for row in source_rows for key in row)))
    export_csv(OUT/'registration_calendar.csv',base['calendars'])
    (OUT/'collection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
