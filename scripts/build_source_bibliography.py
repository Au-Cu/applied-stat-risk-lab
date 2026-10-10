"""Build a public-source bibliography from row-level provenance ledgers.

The research workbook is an internal evidence index, not a public source.  This
script therefore cites the underlying URLs and records exactly which fields,
schools and years each URL supports.  It never invents a webpage title: when a
title was not retained in a structured source, the entry is explicitly marked
as a scope-based description.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
AUDIT = ROOT / "data" / "audit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROCESSED / "public_source_bibliography.csv",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=ROOT / "paper" / "public_source_bibliography.html",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=AUDIT / "public_source_bibliography.json",
    )
    parser.add_argument("--access-date", default="2026-10-09")
    return parser.parse_args()


def strings(series) -> list[str]:
    return sorted(
        {
            str(value).strip()
            for value in series
            if pd.notna(value) and str(value).strip()
        }
    )


def shortened(values: list[str], limit: int = 8) -> str:
    if len(values) <= limit:
        return "；".join(values)
    return "；".join(values[:limit]) + f"；等 {len(values)} 项"


def institution_label(domain: str, schools: list[str], source_name: str) -> str:
    if source_name:
        return source_name
    if domain.endswith("moe.gov.cn"):
        return "中华人民共和国教育部"
    if domain.endswith("chsi.com.cn"):
        return "中国研究生招生信息网"
    if domain.endswith("jiuxianzai.cn") or domain.endswith("aliyuncs.com"):
        return "统计战线统数圈公开数据库"
    if len(schools) == 1 and (
        domain.endswith("edu.cn") or ".edu.cn" in domain
    ):
        return schools[0]
    return domain or "网络来源"


def main() -> None:
    args = parse_args()
    records: dict[str, dict[str, set | str]] = defaultdict(
        lambda: {
            "schools": set(),
            "years": set(),
            "fields": set(),
            "source_types": set(),
            "authority_grades": set(),
            "layers": set(),
            "titles": set(),
        }
    )

    def add(
        url,
        *,
        school="",
        year="",
        field="",
        source_type="",
        authority="",
        layer="",
        title="",
    ) -> None:
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return
        item = records[url]
        for key, value in (
            ("schools", school),
            ("years", year),
            ("fields", field),
            ("source_types", source_type),
            ("authority_grades", authority),
            ("layers", layer),
            ("titles", title),
        ):
            if pd.notna(value) and str(value).strip():
                item[key].add(str(value).strip())

    year_path = PROCESSED / "program_year_provenance.csv"
    if year_path.exists():
        for row in pd.read_csv(year_path, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("source_url"),
                school=row.get("学校"),
                year=row.get("年份"),
                field=f"{row.get('field_group', '')}/{row.get('field_name', '')}",
                source_type=row.get("source_type"),
                authority=row.get("authority_grade"),
                layer="逐字段校年台账",
            )

    master_path = PROCESSED / "school_master_provenance.csv"
    if master_path.exists():
        for row in pd.read_csv(master_path, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("source_url"),
                school=row.get("school") or row.get("学校"),
                field=row.get("field_name") or row.get("field_group"),
                source_type=row.get("source_type"),
                authority=row.get("authority_grade"),
                layer="院校静态字段台账",
            )

    registry_path = PROCESSED / "source_registry_urls.csv"
    if registry_path.exists():
        for row in pd.read_csv(registry_path, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("source_url"),
                field=row.get("covered_fields"),
                source_type=row.get("source_type"),
                authority=row.get("authority_grade"),
                layer="来源总台账",
                title=row.get("source_name"),
            )

    supplemental_path = PROCESSED / "program_year_supplemental_provenance.csv"
    if supplemental_path.exists():
        for row in pd.read_csv(supplemental_path, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("api_url"),
                school=row.get("school"),
                year=row.get("year"),
                field=row.get("field_name"),
                source_type=row.get("source_type"),
                authority=row.get("authority_grade"),
                layer="校年值级补证",
            )
            add(
                row.get("roster_url"),
                school=row.get("school"),
                year=row.get("year"),
                field="逐名名单图像",
                source_type="mini_program_asset",
                authority=row.get("authority_grade"),
                layer="校年值级补证",
            )

    supplemental_master = PROCESSED / "school_master_supplemental_provenance.csv"
    if supplemental_master.exists():
        for row in pd.read_csv(supplemental_master, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("api_url"),
                school=row.get("school"),
                field=row.get("field_name"),
                source_type=row.get("source_type"),
                authority=row.get("authority_grade"),
                layer="院校静态字段补证",
            )

    roster_index = PROCESSED / "mini_program_roster_index.csv"
    if roster_index.exists():
        for row in pd.read_csv(roster_index, encoding="utf-8-sig").to_dict("records"):
            add(
                row.get("repeat_url"),
                school=row.get("school"),
                year=row.get("year"),
                field="逐名复试/录取名单",
                source_type="mini_program_asset",
                authority="secondary_structured",
                layer="逐名名单索引",
                title=row.get("repeat_title"),
            )
            add(
                row.get("api_url"),
                school=row.get("school"),
                year=row.get("year"),
                field="历年复试与录取汇总",
                source_type="mini_program_api",
                authority="secondary_structured",
                layer="逐名名单索引",
            )

    health = {}
    health_path = PROCESSED / "source_url_audit.csv"
    if health_path.exists():
        health_frame = pd.read_csv(health_path, encoding="utf-8-sig")
        health = {
            str(row["source_url"]): row
            for row in health_frame.to_dict("records")
        }

    rows = []
    for sequence, (url, item) in enumerate(sorted(records.items()), start=1):
        domain = urlparse(url).netloc.lower()
        schools = sorted(item["schools"])
        years = sorted(item["years"], key=str)
        fields = sorted(item["fields"])
        titles = sorted(item["titles"])
        retained_title = titles[0] if titles else ""
        institution = institution_label(domain, schools, retained_title)
        if retained_title:
            title = retained_title
            title_status = "retained_structured_title"
        else:
            scope = shortened(fields, 3) or "研究数据"
            school_scope = shortened(schools, 2)
            year_scope = shortened(years, 5)
            title = " ".join(part for part in (school_scope, year_scope, scope) if part)
            title_status = "scope_description_not_original_page_title"
        audit_row = health.get(url, {})
        reachability = str(audit_row.get("reachability", "not_checked") or "not_checked")
        bibliography_id = f"S{sequence:04d}"
        citation_text = (
            f"[{bibliography_id}] {institution}. {title}[EB/OL]. "
            f"({args.access_date})[{args.access_date}]. {url}"
        )
        rows.append(
            {
                "bibliography_id": bibliography_id,
                "institution_or_source": institution,
                "title_or_scope_description": title,
                "title_status": title_status,
                "schools": "；".join(schools),
                "years": "；".join(years),
                "supported_fields": "；".join(fields),
                "source_types": "；".join(sorted(item["source_types"])),
                "authority_grades": "；".join(sorted(item["authority_grades"])),
                "provenance_layers": "；".join(sorted(item["layers"])),
                "reachability": reachability,
                "http_status": audit_row.get("http_status", ""),
                "access_date": args.access_date,
                "source_url": url,
                "citation_text": citation_text,
            }
        )

    frame = pd.DataFrame(rows)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_csv, index=False, encoding="utf-8-sig")

    html_rows = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td>{html.escape(row['bibliography_id'])}</td>"
            f"<td>{html.escape(row['institution_or_source'])}</td>"
            f"<td>{html.escape(row['title_or_scope_description'])}"
            + (
                '<br><span class="inferred">题名未结构化保存；此处为支撑范围描述</span>'
                if row["title_status"] != "retained_structured_title"
                else ""
            )
            + "</td>"
            f"<td>{html.escape(row['schools'])}</td>"
            f"<td>{html.escape(row['years'])}</td>"
            f"<td>{html.escape(row['supported_fields'])}</td>"
            f"<td>{html.escape(row['authority_grades'])}</td>"
            f"<td>{html.escape(row['reachability'])}</td>"
            f"<td><a href=\"{html.escape(row['source_url'], quote=True)}\">{html.escape(row['source_url'])}</a></td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>逐字段公共数据来源文献目录</title>
<style>
body{{font-family:'Noto Serif CJK SC','Source Han Serif SC','SimSun',serif;margin:28px;color:#172033}}
h1{{font-size:24px}} p{{line-height:1.7}} table{{border-collapse:collapse;width:100%;font-size:10px}}
th,td{{border:1px solid #aeb8c6;padding:5px;vertical-align:top;word-break:break-all}}
th{{background:#eaf0f7;position:sticky;top:0}} .inferred{{color:#8a4b08}} a{{color:#184f8f}}
</style></head><body>
<h1>逐字段公共数据来源文献目录</h1>
<p>本目录由逐字段来源台账自动生成，共 {len(rows)} 个唯一公开 URL。研究者工作底稿不作为底层事实来源；每条记录均回链至公开网页、公告、API 或名单图像。题名未被原始台账结构化保存时，仅给出支撑范围描述，并显式标记，避免把推断描述冒充网页原题名。访问失败表示当前复核时链接失效或受阻，不等于证据从未存在。</p>
<table><thead><tr><th>编号</th><th>责任机构/来源</th><th>题名或支撑范围</th><th>学校</th><th>年份</th><th>支撑字段</th><th>来源等级</th><th>访问状态</th><th>URL</th></tr></thead>
<tbody>{''.join(html_rows)}</tbody></table></body></html>"""
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.write_text(document, encoding="utf-8")

    payload = {
        "generated_on": str(date.today()),
        "access_date": args.access_date,
        "unique_public_urls": int(len(frame)),
        "structured_titles": int((frame["title_status"] == "retained_structured_title").sum()),
        "scope_descriptions": int((frame["title_status"] != "retained_structured_title").sum()),
        "reachability": frame["reachability"].value_counts(dropna=False).to_dict(),
        "policy": "The compiled workbook is an internal evidence index and is not cited as a public underlying source.",
        "outputs": [
            str(path.resolve().relative_to(ROOT)).replace("\\", "/")
            for path in (args.output_csv, args.output_html)
        ],
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
