"""Inspect only non-personal programme metadata from known public endpoints."""
import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')

def main():
    rows=list(csv.DictReader((ROOT/'data/processed/mini_program_year_index.csv').open(encoding='utf-8-sig')))
    urls={r['api_url'] for r in rows if r['school']=='同济大学'}
    for url in sorted(urls):
        payload=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))
        data=payload.get('data') or {}
        programme=data.get('schoolMajorVO') or {}
        # Comments, account identifiers and avatars are never printed or saved.
        fields=['schoolName','college','name','train','num','enterpersonYear','enterpersonVolunteerNum']
        selected={k:programme.get(k) for k in fields}
        print(json.dumps(selected,ensure_ascii=False,indent=2)[:14000])

if __name__=='__main__':main()
