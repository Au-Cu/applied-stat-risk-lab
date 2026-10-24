"""Read JavaScript explicitly linked by an already captured public catalogue."""
import argparse
import os
import re
import sys
import urllib.request
from urllib.parse import urljoin
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('host')
    parser.add_argument('file')
    args=parser.parse_args()
    content=Path(args.file).read_text(encoding='utf-8')
    urls=[urljoin(args.host,m.group(1)) for m in re.finditer(r'<script[^>]+src=[\"\']([^\"\']+)',content)]
    urls=[url for url in urls if '/resource/' in url]
    if os.environ.get('HTTPS_PROXY'):
        os.environ['HTTP_PROXY']=os.environ['HTTPS_PROXY']
    for url in urls:
        text=urllib.request.urlopen(url,timeout=40).read().decode('utf-8')
        print(url)
        print(text[:18000])

if __name__=='__main__':
    main()
