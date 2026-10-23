"""Replay extraction on unchanged raw captures; keep failures visible.

Only aggregate source derivatives are produced in the ignored snapshots/work
directories. Replaying parsers never upgrades evidence to human-reviewed data.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT/'output/research/quota_deadline_20261023_r2/snapshots'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(ROOT/'work/quota-r2-ocr-deps'))
from quota_source_readers import TARGET, html_grids, read_xls_bytes, read_xlsx_bytes, position_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--position', action='store_true')
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    audit = []
    for path in sorted(SNAP.glob('*.json')):
        if path.name.endswith(('.ocr.json', '.position.json')):
            continue
        meta = json.loads(path.read_text(encoding='utf-8'))
        if not meta.get('id') or (args.only and meta['id'] not in args.only):
            continue
        source = ROOT / meta['snapshot'] if meta.get('snapshot') else None
        record = {k: meta.get(k) for k in ('id', 'school', 'year', 'url', 'status')}
        if not source or not source.exists():
            record['reader_status'] = '原件未取得，保留失败记录'
            audit.append(record)
            continue
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta.get('sha256'):
            raise ValueError('Original hash mismatch: '+meta['id'])
        try:
            if raw.startswith(b'\xd0\xcf\x11\xe0') or raw.startswith(b'PK'):
                tables = read_xls_bytes(raw) if raw.startswith(b'\xd0\xcf\x11\xe0') else read_xlsx_bytes(raw)
                text = '\n\n'.join('[SHEET '+table['sheet']+']\n'+'\n'.join(' | '.join(row) for row in table['rows']) for table in tables)
                meta['spreadsheet_target_tables'] = [table for table in tables if any(TARGET.search(' '.join(row)) for row in table['rows'])]
                meta['extraction_format'] = 'xls' if raw.startswith(b'\xd0\xcf\x11\xe0') else 'xlsx'
                (SNAP/(meta['id']+'.txt')).write_text(text, encoding='utf-8')
                meta['text_snapshot'] = (SNAP/(meta['id']+'.txt')).relative_to(ROOT).as_posix()
                meta['extraction_repaired'] = True
                # A prior text-reader failure is not a network failure once the
                # retained original has been successfully read and hash checked.
                if meta.get('status') != 'ok':
                    meta['previous_extraction_error'] = meta.get('error')
                    meta['status'] = 'ok'
                    meta.pop('error', None)
                record['reader_status'] = '原始电子表格已恢复读取'
            elif source.suffix == '.html':
                charset = re.search(br'charset\s*=\s*[\x27\x22]?([\w-]+)',raw[:20000],re.I)
                document = raw.decode(charset[1].decode('ascii') if charset else 'utf-8',errors='replace')
                meta['expanded_target_tables'] = [t for t in html_grids(document) if any(TARGET.search(' '.join(row)) for row in t)]
                record['reader_status'] = 'HTML跨行跨列表格已复原'
                if re.search(r'/(?:identity/)?login(?:[/?]|$)|://cas\.',meta.get('resolved_url',''),re.I) and not TARGET.search(document):
                    meta['status']='access_restricted'
                    meta['error']='Official source redirects to authentication; login page is not quota evidence'
                    record['reader_status']='已跳转登录，不误记为取得招生原文'
            elif source.suffix == '.pdf':
                record['reader_status'] = '全文文本已扫描；无文本不视为无专业'
                if args.position and meta.get('pdf_target_pages') and not (SNAP/(meta['id']+'.position.json')).exists():
                    import pypdfium2 as pdfium
                    pages=[]
                    doc=pdfium.PdfDocument(str(source))
                    try:
                        for num in meta['pdf_target_pages']:
                            page=doc[num-1]
                            try:
                                rows=position_rows(page)
                            finally:
                                page.close()
                            pages.append({'page':num,'rows':rows})
                    finally:
                        doc.close()
                    (SNAP/(meta['id']+'.position.json')).write_text(json.dumps({'source_id':meta['id'],'source_sha256':meta['sha256'],'pages':pages},ensure_ascii=False,indent=2),encoding='utf-8')
                    (SNAP/(meta['id']+'.position.txt')).write_text('\n\n'.join('[POSITION PAGE '+str(p['page'])+']\n'+'\n'.join(r['text'] for r in p['rows']) for p in pages),encoding='utf-8')
                if (SNAP/(meta['id']+'.position.json')).exists():
                    record['reader_status']='目标页已按字符坐标复原表格行'
                if (SNAP/(meta['id']+'.ocr.json')).exists():
                    record['ocr_status']='已作本地OCR；数值仍须对照原图'
            else:
                record['reader_status']='原图或待支持格式，不能当作已读取'
            path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:
            record['reader_status']='读取失败，原件保留且不置零'
            record['reader_error']=type(exc).__name__+': '+str(exc)[:300]
        audit.append(record)
    out=ROOT/'work/quota-r2-inventory'
    out.mkdir(exist_ok=True,parents=True)
    (out/'reader_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(Counter(r['reader_status'] for r in audit)),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
