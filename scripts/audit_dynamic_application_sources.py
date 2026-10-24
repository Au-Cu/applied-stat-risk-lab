"""Optional local-original hash audit; publication contains aggregate metadata only."""
import csv
import hashlib
import json
import sys
from pathlib import Path
from public_quota_urls import public_url

ROOT=Path(__file__).resolve().parents[1]
BATCH='dynamic_applications_20261024'
OUT=ROOT/'output/research'/BATCH
sys.stdout.reconfigure(encoding='utf-8')


def main():
    data=json.loads((OUT/'dynamic_application_ratios.json').read_text(encoding='utf-8'))
    sources={}
    with (ROOT/'output/research/quota_deadline_20261023_r2/source_snapshot_index.csv').open(encoding='utf-8-sig',newline='') as handle:
        sources.update({r['id']:r for r in csv.DictReader(handle)})
    private=ROOT/'data/private'/BATCH
    for path in (private/'snapshots').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));sources['new:'+r['id']]=r
    used=set();originals=set()
    for row in data['quotas']:
        for sid,digest in zip(row['source_ids'],row['source_sha256'],strict=True):
            r=sources[sid];assert r['status']=='ok',sid
            assert r['sha256']==digest,sid
            original=ROOT/r['snapshot']
            assert hashlib.sha256(original.read_bytes()).hexdigest()==digest,sid
            assert public_url(r['url']) in row['source_urls'],sid
            used.add(sid);originals.add(str(original))
    images=json.loads((ROOT/'data/research'/BATCH/'screenshot_manifest.json').read_text(encoding='utf-8'))
    assert len(images)==25
    for r in images:
        assert hashlib.sha256((private/'screenshots'/f'page_{r["page"]:02d}.png').read_bytes()).hexdigest()==r['sha256']
    forbidden={'candidate_name','candidate_number','candidate_id','id_number','姓名','考生编号','身份证号'}
    for section in ['records','quotas','school_coverage']:
        for row in data[section]:assert not forbidden.intersection(row),row.keys()
    report=dict(status='passed',referenced_source_ids=len(used),original_files_hash_checked=len(originals),
                screenshot_files_hash_checked=25,public_target_records=len(data['records']),
                computed_ratios=data['summary']['ratio_records'],private_raw_files_published=False,
                personal_candidate_fields_published=False,
                limitation='哈希、口径计算和字段检查不等于所有计划已最终确定、分子完全可比或人工终审通过。')
    (OUT/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
