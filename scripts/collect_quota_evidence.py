"""Capture public, aggregate quota evidence without touching frozen model inputs.

This is a research collector, not an admissions scraper. The explicit manifest
contains official aggregate notices only; it must not contain candidate rosters.
Publication dates are reviewed separately. A URL date, HTTP Last-Modified header,
or the collection timestamp is never promoted to a publication date.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "output" / "research" / "quota_deadline_20261023"


class EvidenceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.link = None
        self.skip = 0
        self.table_stack = []
        self.tables = []
        self.cell = None
        self.row = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "div", "tr", "br", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            self.parts.append(" | ")
            self.cell = ""
        if tag == "table":
            self.table_stack.append([])
        if tag == "tr":
            self.row = []
        if tag == "a":
            self.link = {"url": attrs.get("href", ""), "text": ""}
        if attrs.get("pdfsrc"):
            self.links.append({"url": attrs["pdfsrc"], "text": attrs.get("sudyfile-attr", "嵌入招生计划附件.pdf")})

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append(re.sub(r"\s+", " ", self.cell).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            if self.table_stack:
                self.table_stack[-1].append(self.row)
            self.row = None
        if tag == "table" and self.table_stack:
            self.tables.append(self.table_stack.pop())
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self.link is not None:
            self.links.append(self.link)
            self.link = None
        if tag in {"p", "div", "tr", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.cell is not None:
                self.cell += data
            if self.link is not None:
                self.link["text"] += data


def fetch_one(source, output_dir, refresh=False):
    source_id = source["id"]
    meta_path = output_dir / "snapshots" / f"{source_id}.json"
    if meta_path.exists() and not refresh:
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
        if existing.get("status") == "ok":
            return existing
    url = source["url"]
    meta = {
        **source,
        "collected_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "publication_date_policy": "review_body_or_official_listing_not_url_or_http_metadata",
    }
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; academic quota evidence collection)", "Accept": "*/*"}
        data = None
        if source.get("method") == "POST":
            data = urllib.parse.urlencode(source["body"]).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        request = urllib.request.Request(url, data=data, headers=headers, method=source.get("method", "GET"))
        try:
            with urllib.request.urlopen(request, timeout=22) as response:
                raw = response.read(15_000_001)
                if len(raw) > 15_000_000:
                    raise ValueError("Aggregate evidence exceeds 15MB safety limit")
                content_type = response.headers.get("Content-Type", "")
                encoding = response.headers.get_content_charset()
                meta.update({"resolved_url": response.url, "http_status": response.status, "content_type": content_type,
                             "http_last_modified_not_publication_date": response.headers.get("Last-Modified", "")})
        except urllib.error.URLError as error:
            curl = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "curl.exe"
            if not isinstance(error.reason, ssl.SSLCertVerificationError) or not curl.is_file():
                raise
            # Schannel uses the Windows trust store. TLS validation remains on.
            temporary = output_dir / "snapshots" / f"{source_id}.download"
            command = [str(curl), "--fail", "--silent", "--show-error", "--location", "--max-time", "25",
                       "--max-filesize", "15000000", "--output", str(temporary),
                       "--write-out", "%{http_code}\n%{content_type}\n%{url_effective}"]
            for name, value in headers.items():
                command.extend(["--header", f"{name}: {value}"])
            if data is not None:
                command.extend(["--request", source.get("method", "GET"), "--data-raw", data.decode("ascii")])
            command.append(url)
            result = subprocess.run(command, capture_output=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Validated Windows TLS fallback failed: " + result.stderr.decode("utf-8", errors="replace")[:300]) from error
            status, content_type, resolved = result.stdout.decode("utf-8", errors="replace").split("\n", 2)
            raw = temporary.read_bytes()
            if len(raw) > 15_000_000:
                raise ValueError("Aggregate evidence exceeds 15MB safety limit")
            temporary.unlink()
            encoding = None
            meta.update({"resolved_url": resolved, "http_status": int(status), "content_type": content_type,
                         "download_backend": "windows_curl_tls_validated"})
        suffix = ".pdf" if raw.startswith(b"%PDF") else ".html"
        if raw[:2] == b"PK":
            suffix = ".xlsx"
        blob_path = output_dir / "snapshots" / f"{source_id}{suffix}"
        blob_path.write_bytes(raw)
        meta.update({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                     "snapshot": str(blob_path.relative_to(ROOT)).replace("\\", "/")})
        text = ""
        if suffix == ".pdf":
            pdftotext = shutil.which("pdftotext")
            if pdftotext:
                completed = subprocess.run([pdftotext, "-layout", "-enc", "UTF-8", str(blob_path), "-"],
                                           capture_output=True, timeout=30)
                if completed.returncode == 0:
                    text = completed.stdout.decode("utf-8", errors="replace")
            if not text:
                try:
                    from pypdf import PdfReader
                    text = "\n\f\n".join(page.extract_text(extraction_mode="layout") or "" for page in PdfReader(blob_path).pages)
                except ImportError:
                    meta["extraction_warning"] = "PDF retained; use web PDF reader or install pypdf in the analysis runtime"
        elif suffix == ".html":
            if not encoding:
                match = re.search(br"charset\s*=\s*['\"]?([\w-]+)", raw[:20000], re.I)
                encoding = match.group(1).decode("ascii") if match else "utf-8"
            document = raw.decode(encoding, errors="replace")
            parser = EvidenceHTML()
            parser.feed(document)
            meta["target_tables"] = [table for table in parser.tables
                                      if any("应用统计" in " ".join(row) or "025200" in " ".join(row) for row in table)]
            text = re.sub(r"[ \t\xa0]+", " ", "".join(parser.parts))
            text = re.sub(r"\n[ \t]*\n+", "\n", text).strip()
            embedded = re.findall(r'showVsbpdfIframe\("([^\"]+)"', document)
            parser.links.extend({"url": html.unescape(url), "text": "嵌入统考招生计划.pdf"} for url in embedded)
            meta["links"] = [{"url": urllib.parse.urljoin(meta["resolved_url"], link["url"]),
                              "text": re.sub(r"\s+", " ", link["text"]).strip()}
                             for link in parser.links if link["url"] and not link["url"].startswith(("javascript:", "mailto:"))]
            meta["date_candidates_not_automatically_accepted"] = list(dict.fromkeys(
                re.findall(r"20\d{2}[年/.-]\s*\d{1,2}[月/.-]\s*\d{1,2}日?(?:\s+\d{1,2}:\d{2})?", text)))[:35]
        if text:
            text_path = output_dir / "snapshots" / f"{source_id}.txt"
            text_path.write_text(text, encoding="utf-8")
            meta["text_snapshot"] = str(text_path.relative_to(ROOT)).replace("\\", "/")
            lines = text.splitlines()
            selected = set()
            for idx, line in enumerate(lines):
                if re.search(r"应用统计|025200|发布时间|发布日期|时间[：:]|发表于|普通计划|不含专项|含专项|推免.{0,15}(结束|人数|接收)|招生计划.{0,20}推免", line):
                    selected.update(range(max(0, idx - 1), min(len(lines), idx + 3)))
            meta["review_snippets"] = [{"line": idx + 1, "text": lines[idx]} for idx in sorted(selected)][:100]
        meta["status"] = "ok"
    except Exception as error:
        meta.update({"status": "fetch_failed", "error": f"{type(error).__name__}: {error}"})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "research" / "quota_deadline_20261023" / "sources.json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--follow-attachments", action="store_true")
    parser.add_argument("--follow-notices", action="store_true")
    args = parser.parse_args()
    sources = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.only:
        sources = [source for source in sources if source["id"] in args.only]
    (args.output_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    # Use the configured working outbound proxy consistently without logging it.
    if os.environ.get("HTTPS_PROXY"):
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda source: fetch_one(source, args.output_dir, args.refresh), sources))
    if args.follow_attachments or args.follow_notices:
        all_sources = json.loads(args.manifest.read_text(encoding="utf-8"))
        known_urls = {row["url"] for row in all_sources}
        attachments = []
        for source in results:
            number = 0
            for link in source.get("links", []):
                if args.follow_notices and not source.get("parent_id"):
                    year_match = re.search(r"202[2-7]", link["text"])
                    official = urllib.parse.urlparse(link["url"]).hostname or ""
                    if (year_match and official.endswith(".edu.cn")
                            and re.search(r"统考.{0,20}计划|各专业已接收推免|推免生.{0,15}接收情况|硕士研究生招生专业目录|招生章程和招生目录", link["text"])
                            and not re.search(r"名单|复试|录取情况|考试人数", link["text"])
                            and link["url"] not in known_urls):
                        attachment = {"id": f"notice_{hashlib.sha256(link['url'].encode()).hexdigest()[:10]}",
                                      "url": link["url"], "school": source["school"], "year": int(year_match.group()),
                                      "parent_id": source["id"], "title": link["text"]}
                        attachments.append(attachment)
                        known_urls.add(link["url"])
                if (re.search(r"\.(pdf|xlsx?)(?:$|\?)", link["url"], re.I)
                        or re.search(r"\.(pdf|xlsx?)$", link["text"], re.I)):
                    if not args.follow_attachments or not re.search(r"统考|剩余|招生计划|推免生招生人数|已接收推免", link["text"]) or re.search(r"名单|成绩|录取工作简报", link["text"]):
                        continue
                    if link["url"] in known_urls:
                        continue
                    number += 1
                    attachment = {"id": f"{source['id']}_attach{number}", "url": link["url"],
                                  "school": source["school"], "year": source["year"],
                                  "parent_id": source["id"], "title": link["text"]}
                    attachments.append(attachment)
                    known_urls.add(link["url"])
        if attachments:
            all_sources.extend(attachments)
            args.manifest.write_text(json.dumps(all_sources, ensure_ascii=False, indent=2), encoding="utf-8")
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results.extend(pool.map(lambda source: fetch_one(source, args.output_dir, args.refresh), attachments))
    print(json.dumps([{"id": row["id"], "status": row["status"], "bytes": row.get("bytes"),
                       "error": row.get("error"), "dates": row.get("date_candidates_not_automatically_accepted", [])[:4]}
                      for row in results], ensure_ascii=False))


if __name__ == "__main__":
    main()
