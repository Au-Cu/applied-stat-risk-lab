"""Read-only inspection of aggregate evidence; discovery is not verification."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / 'output/research/quota_deadline_20261023_r2/snapshots'
sys.stdout.reconfigure(encoding='utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--school')
    parser.add_argument('--id')
    parser.add_argument('--limit',type=int,default=12)
    parser.add_argument('--summary',action='store_true')
    parser.add_argument('--brief',action='store_true')
    parser.add_argument('--quota-only',action='store_true')
    args = parser.parse_args()
    records = []
    for path in sorted(SNAP.glob('*.json')):
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            continue
        if args.school and meta.get('school') != args.school:
            continue
        if args.id and meta.get('id') != args.id:
            continue
        text_path = SNAP/f"{meta['id']}.txt"
        text = text_path.read_text(encoding='utf-8') if text_path.exists() else ''
        if args.id:
            print(json.dumps({k:v for k,v in meta.items() if k not in ['links','target_tables','review_snippets']},ensure_ascii=False,indent=2))
            print(text[:2400])
            for match in list(re.finditer(r'应\s*用\s*统\s*计|025200',text))[:12]:
                print(text[max(0,match.start()-180):match.end()+400])
            return
        if meta.get('status') != 'ok' or not re.search(r'应\s*用\s*统\s*计|025200',text):
            continue
        if args.quota_only and not re.search(r'招生计划|招生.{0,4}目录|招生人数|拟录取人数|已接收推免|接收情况|招生专业',str(meta.get('title',''))+'\n'+text[:2200]):
            continue
        hits=[]
        for match in list(re.finditer(r'应\s*用\s*统\s*计|025200',text))[:6]:
            hits.append(text[max(0,match.start()-120):match.end()+340])
        table_rows=[row for table in meta.get('target_tables',[]) for row in table
                    if any('应用统计' in cell or '025200' in cell for cell in row)]
        records.append({'id':meta['id'],'school':meta.get('school'),'year_hint':meta.get('year'),
                        'title':meta.get('title'), 'url':meta.get('url'),
                        'dates':meta.get('date_candidates_not_automatically_accepted',[])[:6],
                        'rows':list({tuple(row):row for row in table_rows}.values())[:6],
                        'headers':[table[:2] for table in meta.get('target_tables',[])][:2],
                        'hits':hits[:1] if args.brief else hits})
    if args.summary:
        print(json.dumps({'target_sources':len(records),'by_school':dict(Counter(row['school'] for row in records))},ensure_ascii=False,indent=2))
    else:
        print(json.dumps(records[:args.limit],ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
