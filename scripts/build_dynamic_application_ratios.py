"""Reproducible platform-count / recommendation-excluded quota snapshot.

This descriptive snapshot is separate from frozen forecasts and historical
backtests. Rank-specific reviewed joins prevent cross-college/campus pooling.
No sample expansion factor or admission probability is estimated here.
"""
from __future__ import annotations
import csv
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from public_quota_urls import public_url

ROOT=Path(__file__).resolve().parents[1]
BATCH='dynamic_applications_20261024'
INPUT=ROOT/'data/research'/BATCH
OUTPUT=ROOT/'output/research'/BATCH
sys.stdout.reconfigure(encoding='utf-8')

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as handle:
        return list(csv.DictReader(handle))

def dump_csv(path,rows,fields=None):
    fields=fields or list(rows[0])
    with path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v
                         for k,v in row.items()} for row in rows)

def normalise_school(value):
    return '华北电力大学' if value in ['华北电力大学（北京）','华北电力大学（保定）'] else value

def net_quota(row):
    """Never subtract a merely planned recommendation count, except an
    explicit official commitment to a fixed examination-quota difference.
    Stated examination quotas already exclude recommendations.
    """
    stated=row.get('stated_exam_quota')
    if stated is not None:
        if row['quota_basis'] not in ['post_recommendation_notice','explicit_exam_catalogue',
                                     'official_fixed_difference','total_less_actual_recommended']:
            return None
        value=float(stated)
        if not math.isfinite(value) or value<0:
            raise ValueError(f'Invalid stated net quota: {row["quota_id"]}')
        if row['quota_basis']=='official_fixed_difference':
            total,planned=row.get('total_plan'),row.get('planned_recommended')
            if total is None or planned is None or not math.isclose(value,total-planned):
                raise ValueError(f'Official fixed difference mismatch: {row["quota_id"]}')
        return value
    if row['quota_basis']=='total_less_actual_recommended':
        total,accepted=row.get('total_plan'),row.get('accepted_recommended')
        if total is not None and accepted is not None:
            if not all(math.isfinite(float(v)) and v>=0 for v in [total,accepted]) or accepted>total:
                raise ValueError(f'Negative or invalid net quota: {row["quota_id"]}')
            return float(total-accepted)
    return None

def ratio(count,quota):
    if count is None or quota is None or quota<=0:return None
    if not math.isfinite(count) or count<0 or not math.isfinite(quota):
        raise ValueError('Invalid count or denominator')
    return count/quota

def load_quotas():
    sources={m['id']:m for m in json.loads((INPUT/'source_manifest.json').read_text(encoding='utf-8'))}
    legacy_sources={m['id']:m for m in read_csv(ROOT/'output/research/quota_deadline_20261023_r2/source_snapshot_index.csv')}
    original=json.loads((ROOT/'output/research/quota_deadline_20261023_r2/quota_deadline_dataset.json').read_text(encoding='utf-8'))['records']
    choices=json.loads((INPUT/'legacy_quota_selections.json').read_text(encoding='utf-8'))
    result=[]
    for choice in choices:
        matches=[r for r in original if all(r.get(k)==choice[k] for k in ['school','year','unit','record_kind'])
                 and not str(r.get('review_status','')).startswith('规则')]
        if len(matches)!=1:raise ValueError(f'Ambiguous legacy quota join: {choice}')
        old=matches[0]
        row=dict(quota_id=f'legacy_{old["record_id"]}',ranks=choice['ranks'],school=old['school'],unit=old['unit'],
            year=old['year'],quota_basis=choice.get('quota_basis_override') or
              ('post_recommendation_notice' if old.get('reported_exam_quota') is not None
               else 'total_less_actual_recommended'),
            total_plan=old.get('total_plan_same_scope'),accepted_recommended=old.get('accepted_recommended'),
            planned_recommended=old.get('planned_recommended'),stated_exam_quota=old.get('reported_exam_quota'),
            ordinary_scope=old['special_scope'],publication_date=old.get('effective_publish_date'),
            source_ids=old['source_ids'],source_urls=[old['primary_source_url'],*old['supporting_urls']],
            source_sha256=old['source_sha256'],source_locator=old['source_locator'],notes=old['notes'])
        if row['year']==2026:
            row['notes']='回退2026统考计划；不是2027已知名额。'+row['notes']
        result.append(row)
    result.extend(json.loads((INPUT/'quota_overrides.json').read_text(encoding='utf-8')))
    dates=json.loads((INPUT/'reviewed_dates.json').read_text(encoding='utf-8'))
    for row in result:
        if row['quota_id'] in dates:row['publication_date']=dates[row['quota_id']]
        row.setdefault('total_plan',None)
        row.setdefault('accepted_recommended',None)
        row.setdefault('planned_recommended',None)
        row.setdefault('stated_exam_quota',None)
        if 'source_urls' not in row:
            metadata=[sources[sid] for sid in row['source_ids'] if sid.startswith('new:')]
            if not metadata or any(m.get('status')!='ok' for m in metadata):
                raise ValueError(f'Missing captured source for {row["quota_id"]}')
            row['source_urls']=[public_url(m['url']) for m in metadata]
            row['source_sha256']=[m['sha256'] for m in metadata]
            row['captured_at']=max(m['collected_at'] for m in metadata)
        else:
            row['source_urls']=[public_url(url) for url in row['source_urls']]
            captured=[legacy_sources[sid]['collected_at'] for sid in row['source_ids'] if sid in legacy_sources]
            row['captured_at']=max(captured) if captured else None
        row['net_exam_quota']=net_quota(row)
        row['study_mode']='全日制'
        row['major_code']='025200'
        row['net_not_actual_admissions']=True
        row['review_status']='已对照原文，待用户人工终审'
        row['quota_stage']=('目录预计统考计划，仍可能调整' if row['quota_basis']=='explicit_exam_catalogue'
                            else '官方承诺统考差额不变' if row['quota_basis']=='official_fixed_difference'
                            else '推免后/复试阶段统考计划')
        row['publication_date_basis']=('公告正文/明确列示日期；当前附件版本未必与初次发布同日'
            if row['publication_date'] else '发布日期尚未核实；抓取时间仅证明当次可见')
        row['denominator_evidence']=('目录预计统考列' if row['quota_basis']=='explicit_exam_catalogue'
            else '官方固定统考差额' if row['quota_basis']=='official_fixed_difference'
            else '总计划减已接收推免（参考差额）' if row['quota_basis']=='total_less_actual_recommended'
            else '官方已单列统考计划')
    return result

def build(write=True):
    raw=read_csv(INPUT/'screenshot_rows.csv')
    ranks=[int(r['rank']) for r in raw]
    if ranks!=list(range(1,243)):raise ValueError('Screenshot sequence must cover ranks 1–242 exactly once')
    schools={r['school']:r for r in read_csv(ROOT/'data/processed/schools.csv')}
    leads={rank:lead for lead in json.loads((INPUT/'unresolved_quota_leads.json').read_text(encoding='utf-8')) for rank in lead['ranks']}
    quotas=load_quotas()
    screenshot_manifest=json.loads((INPUT/'screenshot_manifest.json').read_text(encoding='utf-8'))
    screenshot_hash={r['page']:r['sha256'] for r in screenshot_manifest}
    duplicate_units=Counter((r['school_raw'],r['unit_raw']) for r in raw)
    for r in raw:
        r['screenshot_page']=(int(r['rank'])-1)//10+1
        r['is_target_school']=normalise_school(r['school_raw']) in schools
        r['duplicate_unit_label']=duplicate_units[(r['school_raw'],r['unit_raw'])]>1
        r['screenshot_sha256']=screenshot_hash[r['screenshot_page']]
    quota_index={}
    for q in quotas:
        for rank in q['ranks']:
            quota_index.setdefault(rank,[]).append(q)
    rows=[]
    for rawrow in raw:
        rank=int(rawrow['rank'])
        school=normalise_school(rawrow['school_raw'])
        if school not in schools:continue
        selected=sorted(quota_index.get(rank,[]),key=lambda q:q['year'],reverse=True)
        if selected and selected[0]['school']!=school:
            raise ValueError(f'School mismatch for rank {rank}')
        if len(selected)>1 and selected[0]['year']==selected[1]['year']:
            raise ValueError(f'Ambiguous same-year quota for rank {rank}')
        q=selected[0] if selected else None
        n=int(rawrow['observed_applicants'])
        row=dict(record_id=f'rank_{rank:03d}',school=school,unit=rawrow['unit_raw'],
            is_985=int(schools[school]['is_985']),is_211=int(schools[school]['is_211']),
            faction=schools[school]['faction'],observed_applicants=n,source_rank=rank,
            screenshot_page=(rank-1)//10+1,screenshot_time_display='16:30',
            screenshot_sha256=screenshot_hash[(rank-1)//10+1],
            observation_date='2026-10-24',observation_date_basis='用户本轮提交日期，截图未独立显示日期',
            numerator_scope='平台自报/核验样本；全日制、专项、有效报名口径未逐人验证',
            quota_id=q['quota_id'] if q else None,quota_year=q['year'] if q else None,
            net_exam_quota=q['net_exam_quota'] if q else None,
            sample_dynamic_ratio=ratio(n,q['net_exam_quota']) if q else None,
            fallback_2026=bool(q and q['year']==2026),
            quota_basis=q['quota_basis'] if q else None,
            quota_scope=q['ordinary_scope'] if q else None,
            quota_stage=q['quota_stage'] if q else None,
            denominator_evidence=q['denominator_evidence'] if q else None,
            quota_publication_date=q['publication_date'] if q else None,
            quota_captured_at=q['captured_at'] if q else None,
            source_urls=q['source_urls'] if q else [],
            status=('2026回退' if q and q['year']==2026 else '2027名额') if q else '缺少同口径统考名额',
            notes=q['notes'] if q else '保留报名人数；2027及2026同院系/方向的推免后统考计划尚未核定，不以总计划、拟推免数或实际录取人数替代。')
        if q is None and rank in leads:
            row['notes']=leads[rank]['reason']
            row['source_urls']=[public_url(u) for u in leads[rank]['source_urls']]
        rows.append(row)
    coverage=[]
    for school,meta in schools.items():
        observed=[r for r in rows if r['school']==school]
        matched=[r for r in observed if r['sample_dynamic_ratio'] is not None]
        coverage.append(dict(school=school,faction=meta['faction'],observed_units=len(observed),
            units_with_ratio=len(matched),units_with_2027_quota=sum(r['quota_year']==2027 for r in observed),
            units_with_2026_fallback=sum(r['fallback_2026'] for r in observed),
            status='本次未观察到，不能记零' if not observed else ('全部观察单元有可用分母' if len(matched)==len(observed) else '仍缺部分或全部分母')))
    summary=dict(generated_at=datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds'),
        source='用户提供统计战线小程序25页截图',raw_records=len(raw),target_school_count=len(schools),
        target_records=len(rows),observed_target_schools=len({r['school'] for r in rows}),
        target_schools_not_observed=[r['school'] for r in coverage if not r['observed_units']],
        ratio_records=sum(r['sample_dynamic_ratio'] is not None for r in rows),
        records_using_2027=sum(r['quota_year']==2027 for r in rows),
        records_using_2026_fallback=sum(r['fallback_2026'] for r in rows),
        missing_denominator_records=sum(r['sample_dynamic_ratio'] is None for r in rows),
        formula='平台观察报名人数 ÷ 同范围全日制统考计划（已排除推免）',
        actual_application_expansion_factor=None,common_underreporting_assumption_verified=False,
        forecast_model_changed=False,contains_individual_candidate_data=False,
        numerator_as_of='截图时钟16:30；日期按用户本轮提交日2026-10-24标记，不视为独立时间戳证明。',
        denominator_policy='优先2027已核统考计划，其次2026已核统考计划；目录预计值单列阶段，缺失不填零。',
        denominator_as_of='逐件核对采集时间见名额来源；可能晚于分子截图16:30，不声称完全同步快照。',
        all_counts_are_plan_not_eventual_admissions=True)
    summary['catalogue_reference_records']=sum(q['quota_basis']=='explicit_exam_catalogue' for q in quotas)
    summary['total_minus_actual_reference_records']=sum(q['quota_basis']=='total_less_actual_recommended' for q in quotas)
    summary['duplicate_raw_unit_labels']=[{'school':s,'unit':u,'ranks':[int(r['rank']) for r in raw if (r['school_raw'],r['unit_raw'])==(s,u)]}
        for (s,u),n in duplicate_units.items() if n>1]
    payload=dict(summary=summary,records=rows,quotas=quotas,school_coverage=coverage)
    if write:
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'dynamic_application_ratios.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        dump_csv(OUTPUT/'target_unit_ratios.csv',rows)
        dump_csv(OUTPUT/'quota_evidence.csv',quotas)
        dump_csv(OUTPUT/'school_coverage.csv',coverage)
        dump_csv(OUTPUT/'all_screenshot_rows.csv',raw)
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    return payload

if __name__=='__main__':build()
