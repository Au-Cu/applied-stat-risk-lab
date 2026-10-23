"""Keep public discovery logs free of unverified spam/clone links.

Only discovery logs/manifests created by this research batch are normalised.
Raw source snapshots and their hashes are never rewritten.
"""
import json
from pathlib import Path
from urllib.parse import urlparse
from public_quota_urls import public_url

ROOT=Path(__file__).resolve().parents[1]
RESEARCH=ROOT/'data/research/quota_deadline_20261023_r2'
# The Alipan catalogue share is explicitly linked by an official NJUST notice;
# retaining that public pointer is not a claim that its login/download worked.
SECONDARY={'chinakaoyan.com','eol.cn','360eol.com','koolearn.com','xdf.cn','233.com','educity.cn','kaoyan.cn','alipan.com','mp.weixin.qq.com'}

def trusted(url):
    host=(urlparse(url).hostname or '').lower()
    return host.endswith(('.edu.cn','.gov.cn','.chsi.com.cn')) or any(host==base or host.endswith('.'+base) for base in SECONDARY)

def main():
    total_removed=0
    for path in sorted(RESEARCH.glob('*search_log.json')):
        rows=json.loads(path.read_text(encoding='utf-8'))
        for row in rows:
            original=row.get('entries',[])
            kept=[{**e,'url':public_url(e['url']),'title':e.get('title','')[:220]} for e in original if public_url(e['url']) and trusted(e['url'])]
            removed=len(original)-len(kept)
            row['entries']=kept
            row['unverified_external_results_excluded']=row.get('unverified_external_results_excluded',0)+removed
            total_removed+=removed
        path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    for path in sorted(RESEARCH.glob('sources*.json')):
        rows=json.loads(path.read_text(encoding='utf-8'))
        rows=[row for row in rows if public_url(row['url'])]
        for row in rows:
            row['url']=public_url(row['url'])
            row['title']=row.get('title','')[:220]
            if not trusted(row['url']):
                raise ValueError('Unapproved source host in explicit evidence manifest: '+path.name)
        path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'unverified_external_search_results_removed':total_removed,'raw_sources_changed':False}))

if __name__=='__main__':
    main()
