"""Local OCR of official aggregate quota tables; never publish raw OCR or names."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT/'work/quota-r2-ocr-deps'
if DEPS.exists():
    sys.path.insert(0,str(DEPS))
from rapidocr import RapidOCR
import pypdfium2 as pdfium
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')
SNAP = ROOT/'output/research/quota_deadline_20261023_r2/snapshots'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--pages',help='1-based comma-separated pages; default all')
    args=parser.parse_args()
    meta=json.loads((SNAP/f'{args.source_id}.json').read_text(encoding='utf-8'))
    if '名单' in meta.get('title',''):
        raise ValueError('This helper accepts aggregate quota tables, not individual rosters')
    blob=ROOT/meta['snapshot']
    if hashlib.sha256(blob.read_bytes()).hexdigest()!=meta['sha256']:
        raise ValueError('Original source hash changed')
    out=ROOT/'work/quota-r2-ocr'
    out.mkdir(parents=True,exist_ok=True)
    engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,
                            'EngineConfig.onnxruntime.inter_op_num_threads':1,
                            'Det.limit_side_len':2400,'Det.limit_type':'max'})
    document=pdfium.PdfDocument(str(blob)) if blob.suffix=='.pdf' else None
    pages=[int(value)-1 for value in args.pages.split(',')] if args.pages else list(range(len(document))) if document else [0]
    results=[]
    for page_idx in pages:
        image_path=out/f'{args.source_id}_p{page_idx+1}.png'
        if document:
            page=document[page_idx]
            bitmap=page.render(scale=2.5)
            image=bitmap.to_pil()
            image.save(image_path)
            bitmap.close()
            page.close()
        else:
            image=Image.open(blob).convert('RGB')
            image.save(image_path)
        recognized=engine(image)
        items=[]
        for box,text,score in zip(recognized.boxes,recognized.txts,recognized.scores):
            points=box.tolist()
            items.append({'text':text,'score':float(score),'box':points,
                          'x':sum(p[0] for p in points)/4,'y':sum(p[1] for p in points)/4})
        items.sort(key=lambda item:(item['y'],item['x']))
        grouped=[]
        for item in items:
            if grouped and abs(item['y']-grouped[-1]['y'])<=9:
                grouped[-1]['items'].append(item)
            else:
                grouped.append({'y':item['y'],'items':[item]})
        rows=[]
        for group in grouped:
            cells=sorted(group['items'],key=lambda item:item['x'])
            rows.append({'text':' | '.join(item['text'] for item in cells),'min_score':min(item['score'] for item in cells),'items':cells})
        results.append({'page':page_idx+1,'image':image_path.relative_to(ROOT).as_posix(),'rows':rows})
        hits=[row['text'] for row in rows if re.search(r'应\s*用\s*统\s*计|025200',row['text'])]
        print(json.dumps({'page':page_idx+1,'target_rows':hits,'header':[r['text'] for r in rows[:7]]},ensure_ascii=False),flush=True)
    if document:
        document.close()
    ocr_path=SNAP/f'{args.source_id}.ocr.json'
    existing_pages={}
    if ocr_path.exists():
        previous=json.loads(ocr_path.read_text(encoding='utf-8'))
        if previous['source_sha256']!=meta['sha256']:
            raise ValueError('OCR belongs to a different source version; previous results preserved')
        existing_pages={page['page']:page for page in previous['pages']}
    existing_pages.update({page['page']:page for page in results})
    ocr_path.write_text(json.dumps({'source_id':args.source_id,'source_sha256':meta['sha256'],'engine':'rapidocr-3.10.0-local-cpu','review_status':'OCR only; original image review required','pages':[existing_pages[key] for key in sorted(existing_pages)]},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    main()
