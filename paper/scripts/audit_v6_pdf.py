"""Verify V6 pagination, build a contents index, and render contact sheets.

Requires pypdf/Pillow and Poppler. Raster pages are QA intermediates only.
"""
from pathlib import Path
import argparse
import json
import re
import subprocess
from pypdf import PdfReader
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
PDF=ROOT/'output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V6_统计推断与现代统计建模.pdf'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args()
    reader=PdfReader(PDF);pages=[p.extract_text() or '' for p in reader.pages]
    html=(ROOT/'paper/modeling_paper_v6.html').read_text(encoding='utf-8')
    headings=[h for h in re.findall(r'<h2>([^<]+)</h2>',html) if h not in ('摘　要','目　录')]
    def compact(text):return re.sub(r'\s+','',text)
    mapping={}
    for h in headings:
        found=[i+1 for i,p in enumerate(pages) if i>=2 and any(compact(h)==compact(line) for line in p.splitlines())]
        if not found:raise ValueError('Chapter not found in PDF: '+h)
        mapping[h]=found[0]
    diagnostics={'pages':len(pages),'page_text_lengths':[len(p) for p in pages],
        'chapters':mapping,'unresolved_placeholders':sum('@@' in p for p in pages),
        'replacement_glyph_count':sum(p.count('\ufffd') for p in pages),'pdf_bytes':PDF.stat().st_size}
    target=ROOT/'paper/assets/v6/layout_index.json'
    target.write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(diagnostics,ensure_ascii=False))
    if args.render:
        output=ROOT/f'work/v6-pdf-qa-{len(pages)}pages';output.mkdir(parents=True,exist_ok=True)
        render=subprocess.run(['pdftoppm','-q','-png','-scale-to','1100',str(PDF),str(output/'page')],capture_output=True)
        if render.returncode:raise RuntimeError(render.stderr.decode(errors='replace')[:1000])
        paths=sorted(output.glob('page-*.png'))
        if len(paths)!=len(pages):raise ValueError('Missing page renders')
        for start in range(0,len(paths),12):
            sheet=Image.new('RGB',(1440,1640),'#dfe5ea');draw=ImageDraw.Draw(sheet)
            for j,path in enumerate(paths[start:start+12]):
                with Image.open(path) as im:
                    im.thumbnail((345,490));x=(j%4)*360+7;y=(j//4)*540+30
                    sheet.paste(im,(x,y));draw.text((x,y-20),f'Page {start+j+1}',fill='#183153')
            sheet.save(output/f'contact-{start//12+1}.png')
        print(json.dumps({'rendered_pages':len(paths),'contact_sheets':(len(paths)+11)//12}))


if __name__=='__main__':main()
