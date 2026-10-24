"""Print aggregate quota tables, including HTML escaped in CMS attributes."""
import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from quota_source_readers import SpanTableParser

sys.stdout.reconfigure(encoding='utf-8')

class EmbeddedHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contents=[]
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and '<table' in value:
                self.contents.append(value)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--text', action='store_true')
    args=parser.parse_args()
    p=Path(args.path)
    content=p.read_text(encoding='utf-8')
    embedded=EmbeddedHTML()
    embedded.feed(content)
    parser=SpanTableParser()
    for block in [content,*embedded.contents]:
        parser.feed(block)
    for table in parser.tables:
        hits=[row for row in table if any(re.search(r'025200|应用统计',cell) for cell in row)
              and max(map(len,row),default=0)<500]
        if hits:
            print(json.dumps({'headers':table[:2],'rows':hits},ensure_ascii=False))
    if args.text:
        text=re.sub(r'<[^>]+>',' ',html.unescape(content))
        print(re.sub(r'\s+',' ',text)[:6000])

if __name__=='__main__':main()
