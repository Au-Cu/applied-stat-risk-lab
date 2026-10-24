"""Inspect existing public-source captures; snippets are leads, not quotas."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--school')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--batch', default='old')
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    directories = ([ROOT / 'data/private/dynamic_applications_20261024/snapshots']
                   if args.batch == 'new' else [ROOT / f'output/research/{name}/snapshots'
                       for name in ['quota_deadline_20261023', 'quota_deadline_20261023_r2']])
    records, seen = [], set()
    for directory in directories:
        for path in sorted(directory.glob('*.json')):
            meta = json.loads(path.read_text(encoding='utf-8-sig'))
            if args.school and meta.get('school') != args.school:
                continue
            if meta.get('status') != 'ok' or meta.get('year') not in [2026, 2027]:
                continue
            if meta.get('url') in seen:
                continue
            seen.add(meta.get('url'))
            text_path = path.with_suffix('.txt')
            content = text_path.read_text(encoding='utf-8') if text_path.exists() else ''
            if not re.search(r'025200|应\s*用\s*统\s*计', content):
                continue
            title=str(meta.get('title') or re.sub(r'\s+',' ',content[:180]))
            if re.search(r'名单|拟录取公示|拟录取信息',title):
                continue  # Never print potentially identifying individual rows.
            hits = [content[max(0, m.start()-180):m.end()+430]
                    for m in list(re.finditer(r'025200|应\s*用\s*统\s*计', content))[:4]]
            tables = [row for table in meta.get('target_tables', []) for row in table
                      if any(re.search(r'025200|应用统计', cell) for cell in row)]
            if args.compact:
                if not re.search(r'统考.{0,8}(?:计划|招生|人数)|剩余可用计划|推免.*剩余',content):
                    continue
                if not re.search(r'复试|招生计划|招生.{0,4}目录|招生章程',title):
                    continue
                candidates=[]
                for m in re.finditer(r'025200|应\s*用\s*统\s*计',content):
                    snippet=re.sub(r'\s+',' ',content[max(0,m.start()-100):m.end()+240])
                    if re.search(r'考生编号|姓名|身份证',snippet):
                        continue
                    candidates.append(snippet)
                print(json.dumps(dict(id=meta['id'],school=meta.get('school'),year=meta.get('year'),
                    url=meta.get('url'),title=title[:100],hits=candidates[:2]),ensure_ascii=False))
                continue
            records.append(dict(id=meta['id'], school=meta.get('school'), year=meta.get('year'),
                title=meta.get('title'), url=meta.get('url'),
                tables=tables[:4], headers=[t[:2] for t in meta.get('target_tables', [])][:2],
                hits=hits))
    print(json.dumps(records[:args.limit], ensure_ascii=False, indent=2))
    print(f'\nTOTAL_MATCHING_SOURCES={len(records)}')


if __name__ == '__main__':
    main()
