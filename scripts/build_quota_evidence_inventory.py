"""Index every captured source for review, without accepting any quota label.

The inspection cache is private: unreviewed excerpts can contain personal
information if an official attachment unexpectedly turns out to be a roster.
Only explicitly curated aggregate records may enter the public dataset.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'output/research/quota_deadline_20261023_r2/snapshots'
OUT=ROOT/'work/quota-r2-inventory'
sys.stdout.reconfigure(encoding='utf-8')
TARGET=re.compile(r'应\s*用\s*统\s*计|(?<!\d)025200(?!\d)')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cards=[]
    sources=[]
    for path in sorted(SNAP.glob('*.json')):
        if path.name.endswith('.ocr.json'):
            continue
        try:
            meta=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            continue
        if not meta.get('id'):
            continue
        source={key:meta.get(key) for key in ['id','school','year','url','title','parent_id','status','error','sha256','bytes','snapshot','collected_at','pdf_page_count','pdf_target_pages','pdf_extraction_backend','date_candidates_not_automatically_accepted']}
        sources.append(source)
        text_path=SNAP/f"{meta['id']}.txt"
        text=text_path.read_text(encoding='utf-8') if text_path.exists() else ''
        position_path=SNAP/f"{meta['id']}.position.txt"
        if position_path.exists():
            text+='\n'+position_path.read_text(encoding='utf-8')
        ocr_path=SNAP/f"{meta['id']}.ocr.json"
        if ocr_path.exists():
            ocr=json.loads(ocr_path.read_text(encoding='utf-8'))
            text+='\n'+'\n'.join('\n'.join(row.get('text','') for row in page.get('rows',[])) for page in ocr.get('pages',[]))
        text=re.sub(r'[ \t\xa0]+',' ',text)
        matched=list(TARGET.finditer(text))
        if not matched:
            continue
        quotes=[]
        seen=set()
        for hit in matched:
            quote=text[max(0,hit.start()-140):hit.end()+440].strip()
            key=re.sub(r'\s+','',quote)
            if key not in seen:
                quotes.append(quote)
                seen.add(key)
            if len(quotes)>=10:
                break
        tables=[]
        grids=meta.get('expanded_target_tables',meta.get('target_tables',[]))
        grids+= [t['rows'] for t in meta.get('spreadsheet_target_tables',[])]
        for table in grids:
            selected=[idx for idx,row in enumerate(table) if TARGET.search(' '.join(row))]
            if not selected:
                continue
            tables.append({'headers':table[:5],'rows':[table[idx] for idx in selected],
                           'context':[table[idx] for idx in sorted({j for i in selected for j in range(max(0,i-1),min(len(table),i+2))})]})
        cards.append({**source,'heading':text[:2600], 'target_tables':tables,
                      'target_quotes':quotes,'candidate_only':True,
                      'ocr_available':(SNAP/f"{meta['id']}.ocr.json").exists()})
    (OUT/'sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'cards.json').write_text(json.dumps(cards,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'captured_sources':len(sources),'statuses':dict(Counter(row['status'] for row in sources)),
             'sources_mentioning_target':len(cards),'schools_with_text_mentions':len({row['school'] for row in cards}),
             'by_school':dict(Counter(row['school'] for row in cards)),
             'note':'Mentions and search hits are not verified quota observations.'}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
