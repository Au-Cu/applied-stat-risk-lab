"""Set thesis contents pages from the rendered PDF, never guessed offsets."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import re

from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"paper/modeling_paper_v6_2.html"
PDF=ROOT/"output/pdf/报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V6.2_证据修订与固定模型复核.pdf"
AUDIT=ROOT/"paper/assets/v6_2/toc_pages.json"


class Headings(HTMLParser):
    def __init__(self):
        super().__init__();self.inside=False;self.current=[];self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag=="h2":self.inside=True;self.current=[]
    def handle_data(self,value):
        if self.inside:self.current.append(value)
    def handle_endtag(self,tag):
        if tag=="h2" and self.inside:
            self.items.append("".join(self.current));self.inside=False


def normalize(value):
    return re.sub(r"\s+","",value)


def main():
    source=SOURCE.read_text(encoding="utf-8")
    blank=re.sub(r'(<span class="page" data-toc="\d+">)\d*(</span>)',r'\1\2',source)
    parser=Headings();parser.feed(blank)
    headings=[h for h in parser.items if normalize(h) not in {"摘要","目录"}]
    pages=[page.extract_text() or "" for page in PdfReader(PDF).pages]
    records=[]
    for i,heading in enumerate(headings):
        wanted=normalize(heading);found=None
        for p,text in enumerate(pages[2:],3):
            lines=text.splitlines()
            if any(normalize("".join(lines[j:j+k]))==wanted for j in range(len(lines)) for k in (1,2)):
                found=p;break
        if found is None:raise ValueError(f"Heading missing in PDF: {heading}")
        records.append({"index":i,"heading":heading,"page":found})
        pattern=rf'(<span class="page" data-toc="{i}">)\d*(</span>)'
        source,count=re.subn(pattern,lambda m:m.group(1)+str(found)+m.group(2),source)
        if count!=1:raise ValueError(f"Missing contents anchor {i}")
    AUDIT.write_text(json.dumps({"source_content_sha256":hashlib.sha256(blank.encode()).hexdigest(),
        "pdf_pages":len(pages),"headings":records},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    SOURCE.write_text(source,encoding="utf-8")
    print(json.dumps({"contents_entries":len(records),"pdf_pages":len(pages)},ensure_ascii=False))


if __name__=="__main__":main()
