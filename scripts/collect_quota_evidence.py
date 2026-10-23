"""Capture public, aggregate quota evidence without touching frozen model inputs.

This is a research collector. Most manifests contain aggregate notices only.
An explicitly flagged public incoming-recommendation roster may be retained
locally solely to compute anonymised aggregate counts; never release raw rows.
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
import threading
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo
from public_quota_urls import public_url

sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "output" / "research" / "quota_deadline_20261023"
PDFIUM_LOCK = threading.RLock()


def extract_pdf_text(blob_path, meta):
    """Keep a full-document text scan and layout text around all target pages.

    PDFium is protected by a process-wide mutex, as required by its API. Large
    catalogues need not pay for layout reconstruction on every unrelated page.
    A negative scan is not evidence that the university does not offer MAS.
    """
    try:
        import pypdfium2 as pdfium
        plain_pages = []
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(str(blob_path))
            try:
                for page_idx in range(len(document)):
                    page = document[page_idx]
                    try:
                        text_page = page.get_textpage()
                        try:
                            plain_pages.append(text_page.get_text_bounded())
                        finally:
                            text_page.close()
                    finally:
                        page.close()
            finally:
                document.close()
        targets = [idx for idx, text in enumerate(plain_pages)
                   if re.search(r"应\s*用\s*统\s*计|0252(?:00)?", text)]
        meta["pdf_page_count"] = len(plain_pages)
        meta["pdf_target_pages"] = [idx + 1 for idx in targets]
        full_text = "\n\f\n".join(f"[PDF PAGE {idx + 1}]\n{text}" for idx, text in enumerate(plain_pages))
        meta["pdf_extraction_backend"] = "pdfium_full_document"
        if not targets:
            meta["target_scan_note"] = "No target detected by first parser; not evidence of no programme or zero quota"
        if os.environ.get("QUOTA_PDF_LAYOUT") != "1":
            return full_text
        selected = set(range(min(2, len(plain_pages))))
        for idx in targets:
            selected.update(range(max(0, idx - 1), min(len(plain_pages), idx + 2)))
        from pypdf import PdfReader
        reader = PdfReader(blob_path)
        layout = "\n\f\n".join(f"[LAYOUT PAGE {idx + 1}]\n" +
                                 (reader.pages[idx].extract_text(extraction_mode="layout") or "")
                                 for idx in sorted(selected))
        layout_path = blob_path.with_suffix(".layout.txt")
        layout_path.write_text(layout, encoding="utf-8")
        meta["layout_text_snapshot"] = layout_path.relative_to(ROOT).as_posix()
        meta["pdf_extraction_backend"] = "pdfium_full_document_and_pypdf_target_layout"
        if not targets:
            meta["target_scan_note"] = "No target detected by first parser; not evidence of no programme or zero quota"
        return full_text + "\n" + layout
    except ImportError:
        from pypdf import PdfReader
        meta["pdf_extraction_backend"] = "pypdf_full_layout"
        return "\n\f\n".join(page.extract_text(extraction_mode="layout") or "" for page in PdfReader(blob_path).pages)


class EvidenceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.images = []
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
        if tag == "img" and (attrs.get("src") or attrs.get("data-src")):
            self.images.append({"url": attrs.get("src") or attrs.get("data-src"), "alt": attrs.get("alt", "")})

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


def fetch_one(source, output_dir, refresh=False, cache_failures=False):
    if not public_url(source['url']):
        raise ValueError('Only public HTTP(S) evidence links are allowed; local/file links are blocked before cache access')
    source_id = source["id"]
    meta_path = output_dir / "snapshots" / f"{source_id}.json"
    if meta_path.exists() and not refresh:
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
        if existing.get("url") != source["url"] and not (public_url(existing.get('url','')) and public_url(existing['url'])==public_url(source['url'])):
            raise ValueError(f"Evidence ID collision; original capture preserved: {source_id}")
        if existing.get("status") == "ok" or cache_failures:
            return existing
    url = source["url"]
    meta = {
        **source,
        "collected_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "publication_date_policy": "review_body_or_official_listing_not_url_or_http_metadata",
    }
    try:
        url=public_url(url)
        if not url:
            raise ValueError('Only public HTTP(S) evidence links are permitted; non-HTTP/local links are blocked')
        meta['url']=url
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
                       "--proto", "=http,https", "--proto-redir", "=http,https",
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
        if raw.startswith(b"\x89PNG"):
            suffix = ".png"
        elif raw.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
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
                    text = extract_pdf_text(blob_path, meta)
                except ImportError:
                    meta["extraction_warning"] = "PDF retained; use web PDF reader or install pypdf in the analysis runtime"
        elif suffix == ".html":
            if not encoding:
                match = re.search(br"charset\s*=\s*['\"]?([\w-]+)", raw[:20000], re.I)
                encoding = match.group(1).decode("ascii") if match else "utf-8"
            document = raw.decode(encoding, errors="replace")
            parser = EvidenceHTML()
            parser.feed(document)
            meta["image_refs"] = [{"url": urllib.parse.urljoin(meta["resolved_url"], item["url"]), "alt": item["alt"]}
                                  for item in parser.images]
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
        if (re.search(r'/(?:identity/)?login(?:[/?]|$)|://cas\.',meta.get('resolved_url',''),re.I)
                and not re.search(r'025200|应用统计',text)):
            meta['status']='access_restricted'
            meta['error']='Official source redirects to authentication; login page is not quota evidence'
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
    parser.add_argument("--follow-public-roster-attachments", action="store_true", help="Only explicitly privacy-flagged public recommendation notices; local raw files stay private")
    parser.add_argument("--summary", action="store_true", help="Report batch totals instead of every capture")
    parser.add_argument("--cache-failures", action="store_true", help="Keep prior failed attempts while following additional links")
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    sources = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.only:
        sources = [source for source in sources if source["id"] in args.only]
    (args.output_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    # Use the configured working outbound proxy consistently without logging it.
    if os.environ.get("HTTPS_PROXY"):
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda source: fetch_one(source, args.output_dir, args.refresh, args.cache_failures), sources))
    if args.follow_attachments or args.follow_notices or args.follow_public_roster_attachments:
        all_sources = json.loads(args.manifest.read_text(encoding="utf-8"))
        known_urls = {row["url"] for row in all_sources}
        known_ids = {row["id"] for row in all_sources}
        attachments = []
        for source in results:
            number = 0
            for link in source.get("links", []):
                if args.follow_notices:
                    # Link cards can start with an archive date (2025-10)
                    # before an intake title (2026年); prefer the latter.
                    year_match = re.search(r"202[2-7](?=\s*[年级])", link["text"]) or re.search(r"202[2-7]", link["text"])
                    official = urllib.parse.urlparse(link["url"]).hostname or ""
                    source_host=urllib.parse.urlparse(source['url']).hostname or ''
                    same_university='.'.join(official.split('.')[-3:])=='.'.join(source_host.split('.')[-3:])
                    if (year_match and official.endswith(".edu.cn")
                            and same_university
                            and re.search(r"统考.{0,20}计划|各专业已接收推免|推免.{0,30}(?:统计|人数|接收情况)|接收推免.{0,15}(?:人数|统计)|硕士.{0,15}招生.{0,5}目录|招生章程和招生目录", link["text"])
                            and not re.search(r"名单|复试|录取情况|考试人数", link["text"])
                            and len(attachments)<200
                            and link["url"] not in known_urls):
                        attachment = {"id": f"notice_{hashlib.sha256(link['url'].encode()).hexdigest()[:10]}",
                                      "url": link["url"], "school": source["school"], "year": int(year_match.group()),
                                      "parent_id": source["id"], "title": link["text"]}
                        attachments.append(attachment)
                        known_urls.add(link["url"])
                if (re.search(r"\.(pdf|xlsx?)(?:$|\?)", link["url"], re.I)
                        or re.search(r"\.(pdf|xlsx?)$", link["text"], re.I)):
                    roster_allowed=(args.follow_public_roster_attachments
                                    and source.get('privacy_scope')=='public_incoming_recommendation_roster_aggregate_count_only'
                                    and re.search(r'推免|拟录取',link['text']) and re.search(r'名单|信息表|公示',link['text'])
                                    and not re.search(r'本科|推荐资格|候补|夏令营',link['text']))
                    aggregate_allowed=(args.follow_attachments and re.search(r"统考|剩余|招生计划|推免.{0,18}(人数|情况|统计)|已接收推免|专业目录|招生目录|分专业|人数.{0,4}统计|接收人数|名额",link['text']) and not re.search(r"名单|成绩|录取工作简报",link['text']))
                    link_host=urllib.parse.urlparse(link['url']).hostname or ''
                    source_host=urllib.parse.urlparse(source['url']).hostname or ''
                    if not (roster_allowed or aggregate_allowed) or (roster_allowed and '.'.join(link_host.split('.')[-3:])!='.'.join(source_host.split('.')[-3:])):
                        continue
                    if link["url"] in known_urls:
                        continue
                    number += 1
                    while f"{source['id']}_attach{number}" in known_ids or (args.output_dir / "snapshots" / f"{source['id']}_attach{number}.json").exists():
                        number += 1
                    attachment = {"id": f"{source['id']}_attach{number}", "url": link["url"],
                                  "school": source["school"], "year": source["year"],
                                  "parent_id": source["id"], "title": link["text"]}
                    if roster_allowed:
                        attachment.update({'privacy_scope':source['privacy_scope'],'public_raw_release_allowed':False})
                    attachments.append(attachment)
                    known_ids.add(attachment["id"])
                    known_urls.add(link["url"])
        if attachments:
            all_sources.extend(attachments)
            args.manifest.write_text(json.dumps(all_sources, ensure_ascii=False, indent=2), encoding="utf-8")
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results.extend(pool.map(lambda source: fetch_one(source, args.output_dir, args.refresh, args.cache_failures), attachments))
    if args.summary:
        states = sorted({row["status"] for row in results})
        print(json.dumps({"sources": len(results), "status": {state: sum(row["status"] == state for row in results) for state in states}}, ensure_ascii=False))
    else:
        print(json.dumps([{"id": row["id"], "status": row["status"], "bytes": row.get("bytes"),
                           "error": row.get("error"), "dates": row.get("date_candidates_not_automatically_accepted", [])[:4]}
                          for row in results], ensure_ascii=False))


if __name__ == "__main__":
    main()
