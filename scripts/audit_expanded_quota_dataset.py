"""Audit the research batch, source hashes and the no-auto-promotion gates."""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/research/quota_deadline_20261023_r2'
SNAP=OUT/'snapshots'
sys.stdout.reconfigure(encoding='utf-8')
from build_expanded_quota_dataset import export_csv, timing


def main():
    dataset=json.loads((OUT/'quota_deadline_dataset.json').read_text(encoding='utf-8'))
    sources={s['id']:s for s in dataset['sources']}
    assert len(sources)==len(dataset['sources']), 'Nonunique source namespaces'
    assert len(dataset['coverage'])==81*6
    assert len({(r['school'],r['year']) for r in dataset['coverage']})==486
    assert len({r['record_id'] for r in dataset['records']})==len(dataset['records'])
    hashes={}
    referenced=set()
    for row in dataset['records']:
        assert row.get('model_eligible') is False
        assert row['year'] in range(2022,2028)
        assert row['deadline_timing']==timing(row.get('effective_publish_date'),row['registration_deadline'],row.get('publication_precision','date'))
        t,r=row.get('total_plan_same_scope'),row.get('accepted_recommended')
        expected=t-r if t is not None and r is not None else None
        assert row['total_less_accepted']==expected, row['record_id']
        if row.get('planned_recommended') is not None and r is None:
            assert row['total_less_accepted'] is None
        for key,digest in zip(row['source_ids'],row['source_sha256'],strict=True):
            source=sources[key]
            assert source['status']=='ok'
            assert source['sha256']==digest
            referenced.add(key)
            original=ROOT/source['snapshot']
            assert original.exists(), 'Local source is missing; this audit requires the private evidence cache'
            if str(original) not in hashes:
                hashes[str(original)]=hashlib.sha256(original.read_bytes()).hexdigest()
            assert hashes[str(original)]==digest
    index=[]
    for source in dataset['sources']:
        row={k:source.get(k) for k in ['id','school','year','url','status','sha256']}
        if source.get('evidence_batch')!='r2':
            continue
        text_path=SNAP/(source['id'].removeprefix('r2:')+'.txt')
        text=text_path.read_text(encoding='utf-8') if text_path.exists() else ''
        stem=source['id'].removeprefix('r2:')
        row.update({'plain_text_characters':len(text.strip()),
                    'contains_target_major_code':bool(re.search(r'(?<!\d)025200(?!\d)',text)),
                    'contains_name_mention':bool(re.search(r'应\s*用\s*统\s*计',text)),
                    'position_rows_available':(SNAP/(stem+'.position.json')).exists(),
                    'local_ocr_available':(SNAP/(stem+'.ocr.json')).exists(),
                    'referenced_in_registered_records':source['id'] in referenced,
                    'raw_roster_public_release_allowed':False})
        if source['status']!='ok':
            row['reading_gate']='访问失败或需登录，不视为无数据'
        elif (source.get('snapshot') or '').endswith(('.png','.jpg')) and not row['local_ocr_available']:
            row['reading_gate']='图片尚未完成OCR及原图核对'
        elif not text.strip() and not row['local_ocr_available']:
            row['reading_gate']='未取得可用文本；不以检索未命中判无专业'
        elif row['contains_target_major_code'] or row['contains_name_mention']:
            row['reading_gate']='已读取到相关提及；不等于已识别名额列或完成复核'
        else:
            row['reading_gate']='当前文本未检出目标；扫描、附件或专业状态仍可待查'
        index.append(row)
    export_csv(OUT/'source_reading_audit.csv',index)
    report={'status':'passed','registered_records':len(dataset['records']),
            'referenced_source_ids_hash_checked':len(referenced),'distinct_original_files_hash_checked':len(hashes),
            'complete_school_year_grid':486,'automatic_model_promotions':0,
            'reader_gates':dict(Counter(r['reading_gate'] for r in index)),
            'legacy_records_flagged_for_reaudit':sum(r.get('review_status','').startswith('历史批次') for r in dataset['records']),
            'raw_candidate_or_roster_files_published':False,
            'limitation':'格式/哈希/防泄漏检查通过不等于全部数值正确、全部名额齐备或人工终审已完成。'}
    (OUT/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
