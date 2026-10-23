"""Compact aggregate-table review; no candidate-level names are printed."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'output/research/quota_deadline_20261023_r2/snapshots'
sys.stdout.reconfigure(encoding='utf-8')
from quota_source_readers import TARGET

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--school')
    p.add_argument('--id',nargs='*')
    p.add_argument('--limit',type=int,default=30)
    p.add_argument('--offset',type=int,default=0)
    p.add_argument('--position',action='store_true')
    p.add_argument('--actual',action='store_true')
    args=p.parse_args()
    results=[]
    seen=set()
    for path in sorted(SNAP.glob('*.json')):
        if path.name.endswith(('.ocr.json','.position.json')):
            continue
        meta=json.loads(path.read_text(encoding='utf-8'))
        if not meta.get('id') or meta.get('status')!='ok' or (args.school and meta['school']!=args.school) or (args.id and meta['id'] not in args.id):
            continue
        if meta.get('sha256') in seen:
            continue
        text_path=SNAP/(meta['id']+'.txt')
        text=text_path.read_text(encoding='utf-8') if text_path.exists() else ''
        if re.search(r'考生编号|准考证号|考生姓名|身份证|姓名',text[:2400]) or re.search(r'名单|成绩|录取汇总|录取情况|报录统计|分数线|报告|工作总结',meta.get('title','')):
            continue
        if args.actual and not re.search(r'已接收推免|推免.{0,18}(?:人数|统计|情况)|接收推免硕士研究生人数',meta.get('title','')):
            continue
        if args.position:
            position_path=SNAP/(meta['id']+'.position.txt')
            if not position_path.exists():
                continue
            text=position_path.read_text(encoding='utf-8')
        lines=text.splitlines()
        hits=[i for i,line in enumerate(lines) if TARGET.search(line)]
        tables=meta.get('expanded_target_tables',meta.get('target_tables',[]))
        table_rows=[]
        for table in tables:
            for idx,row in enumerate(table):
                if TARGET.search(' '.join(row)):
                    table_rows.append({'header':[' | '.join(r)[:420] for r in table[:3]],'before':[' | '.join(r) for r in table[max(0,idx-1):idx]],'row':row})
        if not hits and not table_rows:
            continue
        seen.add(meta.get('sha256'))
        results.append({'id':meta['id'],'school':meta['school'],'year_hint':meta.get('year'),
                        'title':meta.get('title','')[:120],
                        'dates':meta.get('date_candidates_not_automatically_accepted',[])[:4],
                        'tables':table_rows[:4],
                        'lines':[' / '.join(lines[max(0,i-1):i+2])[:700] for i in hits[:5]]})
    print(json.dumps({'total_unique_candidate_sources':len(results),'items':results[args.offset:args.offset+args.limit]},ensure_ascii=False))

if __name__=='__main__':
    main()
