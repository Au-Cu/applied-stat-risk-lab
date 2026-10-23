"""Count public incoming-recommendation rows locally, never expose people.

These are review candidates. A count across all departments/modes must not be
subtracted from a single department's full-time plan. No absent major becomes 0.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'output/research/quota_deadline_20261023_r2/snapshots'
OUT=ROOT/'output/research/quota_deadline_20261023_r2'
sys.stdout.reconfigure(encoding='utf-8')
from build_expanded_quota_dataset import intake_year, publication, compact


def count_rows(lines,allow_serial_only=False,require_row_recommendation=False):
    """Require target code and a candidate identifier on the same row.

    Do not count catalogue headings, programme totals, or an academic major
    with the same Chinese name but another code. Ambiguous wrapped rows stay
    uncounted and are reported, not guessed or silently assigned to zero.
    """
    identities={}
    unmatched=0
    for line in lines:
        if not re.search(r'(?<!\d)025200(?!\d)',line):
            continue
        if require_row_recommendation and not re.search(r'推免|推荐免试',line):
            unmatched+=1
            continue
        clean=re.sub(r'(?<=\d)[ \t]+(?=\d)','',line)
        identifiers=re.findall(r'(?<!\d)\d{8,18}(?!\d)',clean)
        serial=re.match(r'^\s*([1-9]\d{0,4})\s*(?:\||[ \t])',line)
        if not identifiers and not (allow_serial_only and serial):
            unmatched+=1
            continue
        # A published serial number is accepted only when the actual roster
        # header explicitly labels 序号 and 姓名. Unit code 007 is not a serial.
        key=hashlib.sha256((identifiers[0] if identifiers else 'serial:'+serial[1]).encode()).hexdigest()
        mode='nonfulltime' if re.search(r'非\s*全\s*日\s*制',line) else 'fulltime' if re.search(r'全\s*日\s*制',line) else 'unknown'
        special=bool(re.search(r'少数民族骨干|少干|支教|士兵|退役大学生|强基|专项',line))
        current={'mode':mode,'special':special,'ordinary_explicit':bool(re.search(r'普通计划|一般计划',line))}
        if key in identities and identities[key]!=current:
            raise ValueError('Same applicant has conflicting modes or plan types; manual review required')
        identities[key]=current
    counts=Counter(row['mode'] for row in identities.values())
    return {'all_modes_count':len(identities) if identities else None,
            'explicit_fulltime_count':counts['fulltime'] if identities else None,
            'explicit_nonfulltime_count':counts['nonfulltime'] if identities else None,
            'mode_unknown_count':counts['unknown'] if identities else None,
            'explicit_special_count':sum(row['special'] for row in identities.values()) if identities else None,
            'explicit_ordinary_count':sum(row['ordinary_explicit'] for row in identities.values()) if identities else None,
            'target_rows_without_same_row_identifier':unmatched,
            'private_dedup_identity_count':len(identities)}


def main():
    metas=[]
    for path in SNAP.glob('*.json'):
        if path.name.endswith(('.ocr.json','.position.json')):
            continue
        meta=json.loads(path.read_text(encoding='utf-8'))
        if meta.get('id'):
            metas.append(meta)
    by_id={m['id']:m for m in metas}
    records=[]
    audit=[]
    seen=set()
    for meta in metas:
        if meta.get('privacy_scope')!='public_incoming_recommendation_roster_aggregate_count_only' or meta['status']!='ok':
            continue
        title=meta.get('title','')
        if not re.search(r'名单|考生编号信息表|录取结果',title) or re.search(r'夏令营|候补|本科|推荐资格',title):
            continue
        if re.search(r'不含推免|不包括推免|不包含推免',title):
            continue
        exclusive=bool(re.search(r'推免.{0,25}(?:拟录取|预录取|录取名单)|(?:拟录取|接收).{0,12}推免',title)) and not re.search(r'含推免|包括推免',title)
        if meta.get('sha256') in seen:
            continue
        seen.add(meta.get('sha256'))
        original=ROOT/meta['snapshot']
        if hashlib.sha256(original.read_bytes()).hexdigest()!=meta['sha256']:
            raise ValueError('Original roster hash mismatch')
        text_path=SNAP/(meta['id']+'.txt')
        text=text_path.read_text(encoding='utf-8') if text_path.exists() else ''
        row={'source_id':'r2:'+meta['id'],'school':meta['school'],'source_url':meta['url'],'source_title':title[:160],
             'source_sha256':meta['sha256'],'review_status':'仅脱敏计数候选，未核定单位与模式，不入模'}
        if not re.search(r'姓名|考生编号|报名号|考生号',text[:10000]):
            audit.append({**row,'status':'未读取到名录表头；不能计数，更不能置零'})
            continue
        year=intake_year(meta,compact(text))
        if year is None and meta.get('parent_id'):
            year=intake_year(by_id[meta['parent_id']],'')
        if year is None:
            audit.append({**row,'status':'入学年度尚未核定，未登记数值'})
            continue
        position_path=SNAP/(meta['id']+'.position.json')
        if position_path.exists():
            positioned=json.loads(position_path.read_text(encoding='utf-8'))
            if positioned['source_sha256']!=meta['sha256']:
                raise ValueError('Roster coordinate derivative hash mismatch')
            lines=[r['text'] for p in positioned['pages'] for r in p['rows']]
            method='PDF目标页字符坐标逐行计数，按考生编号本地去重'
        elif meta.get('expanded_target_tables') or meta.get('target_tables'):
            grids=meta.get('expanded_target_tables',meta.get('target_tables',[]))
            lines=[' | '.join(r) for t in grids for r in t]
            method='HTML逐行计数，按考生编号本地去重'
        else:
            lines=text.splitlines()
            method='原文文本逐行计数，按考生编号本地去重'
        counted=count_rows(lines,allow_serial_only=bool('序号' in text[:10000] and '姓名' in text[:10000]),require_row_recommendation=not exclusive)
        published,precision,basis=publication(meta,by_id,compact(text))
        row.update({'year':year,**counted,'effective_publish_date':published,'publication_precision':precision,
                    'publication_date_basis':basis,'capture_time':meta['collected_at'],
                    'counting_method':method,'aggregation_scope':'同校025200跨培养单位合计，单位尚待逐列核对',
                    'roster_population':'推免专门名录' if exclusive else '混合名录仅计逐行明确推免者',
                    'model_eligible':False,'public_contains_individual_rows':False})
        if counted['all_modes_count'] is None:
            audit.append({**row,'status':'未取得可按行去重的目标专业名录；不是推免人数0'})
        else:
            records.append(row)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'recommended_roster_counts.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    private=ROOT/'work/quota-r2-inventory'
    private.mkdir(parents=True,exist_ok=True)
    (private/'roster_count_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'aggregate_count_candidates':len(records),'schools':len({r['school'] for r in records}),
                      'unresolved_roster_sources':len(audit),'individual_rows_published':0},ensure_ascii=False))


if __name__=='__main__':
    main()
