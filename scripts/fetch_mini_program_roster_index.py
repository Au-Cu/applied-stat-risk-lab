"""Fetch the non-personal roster index from public mini-program detail APIs.

Only ``schoolMajorVO`` metadata and ``majorRepeatList`` are retained.  Comment
content, avatars, nicknames, and user identifiers returned by the same endpoint
are intentionally discarded before anything is written to disk.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE = ROOT / "data" / "processed" / "program_year_provenance.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "mini_program_roster_index.csv"
DEFAULT_YEAR_OUTPUT = ROOT / "data" / "processed" / "mini_program_year_index.csv"
DEFAULT_AUDIT = ROOT / "data" / "audit" / "mini_program_roster_index.json"
TARGET_PATTERN = re.compile(r"应用统计|应统|025200")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch public mini-program roster URL indexes.")
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--year-output", type=Path, default=DEFAULT_YEAR_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def read_api_targets(path: Path) -> list[dict]:
    schools_by_url: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("source_type") != "mini_program_api" or not row.get("source_url"):
                continue
            schools_by_url[row["source_url"]].add(row["学校"])
    return [
        {"api_url": url, "workbook_schools": sorted(schools)}
        for url, schools in sorted(schools_by_url.items())
    ]


def parallel_map(years, values) -> dict[str, str]:
    year_items = [item.strip() for item in re.split(r"[;；]", str(years or ""))]
    value_items = [item.strip() for item in re.split(r"[;；]", str(values or ""))]
    return {
        year: value_items[index] if index < len(value_items) else ""
        for index, year in enumerate(year_items)
        if year
    }


def fetch(target: dict) -> dict:
    result = {**target, "status": "error", "error": "", "rows": [], "year_rows": [], "metadata": {}}
    try:
        request = urllib.request.Request(
            target["api_url"],
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AppliedStatRiskResearch/1.0)",
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://servicewechat.com/wxccab980dae519e2f/34/page-frame.html",
            },
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        if int(payload.get("code", 0)) != 200:
            raise ValueError(f"API code {payload.get('code')}: {payload.get('msg', '')}")
        # Deliberately select only the non-personal program object.  Do not keep
        # payload['data']['commentTreeVO'] or any other user-generated content.
        program = (payload.get("data") or {}).get("schoolMajorVO") or {}
        api_school = str(program.get("schoolName") or "").strip()
        workbook_school = api_school if api_school in target["workbook_schools"] else target["workbook_schools"][0]
        major_name = str(program.get("name") or "").strip()
        college = str(program.get("college") or "").strip()
        detail_id = str(program.get("id") or "").strip()
        in_scope = bool(TARGET_PATTERN.search(major_name))
        retrieved_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for item in program.get("majorRepeatList") or []:
            year = str(item.get("year") or "").strip()
            url = str(item.get("repeatUrl") or "").strip()
            if not year or not url:
                continue
            rows.append(
                {
                    "school": workbook_school,
                    "api_school": api_school,
                    "college": college,
                    "major_name": major_name,
                    "detail_id": detail_id,
                    "year": year,
                    "repeat_title": str(item.get("repeatTitle") or "").strip(),
                    "repeat_url": url,
                    "api_url": target["api_url"],
                    "in_scope": in_scope,
                    "retrieved_at": retrieved_at,
                }
            )
        roster_by_year = {row["year"]: row for row in rows}
        cutoff_by_year = parallel_map(program.get("repeatYear"), program.get("repeatGrade"))
        admitted_min_by_year = parallel_map(program.get("repeatYear"), program.get("repeatMinGrade"))
        admitted_count_by_year = parallel_map(program.get("enterpersonYear"), program.get("enterpersonVolunteerNum"))
        retest_count_by_year = parallel_map(program.get("enterpersonYear"), program.get("enterpersonRepeatNum"))
        report_ratio_by_year = parallel_map(program.get("reportYear"), program.get("reportRatio"))
        all_years = sorted(
            set(roster_by_year)
            | set(cutoff_by_year)
            | set(admitted_min_by_year)
            | set(admitted_count_by_year)
            | set(retest_count_by_year)
            | set(report_ratio_by_year)
        )
        year_rows = []
        for year in all_years:
            roster = roster_by_year.get(year, {})
            year_rows.append(
                {
                    "school": workbook_school,
                    "api_school": api_school,
                    "college": college,
                    "major_name": major_name,
                    "detail_id": detail_id,
                    "year": year,
                    "reported_cutoff": cutoff_by_year.get(year, ""),
                    "reported_admitted_min": admitted_min_by_year.get(year, ""),
                    "reported_admitted_count": admitted_count_by_year.get(year, ""),
                    "reported_retest_count": retest_count_by_year.get(year, ""),
                    "reported_report_ratio": report_ratio_by_year.get(year, ""),
                    "repeat_title": roster.get("repeat_title", ""),
                    "repeat_url": roster.get("repeat_url", ""),
                    "api_url": target["api_url"],
                    "in_scope": in_scope,
                    "retrieved_at": retrieved_at,
                }
            )
        result.update(
            {
                "status": "ok",
                "rows": rows,
                "year_rows": year_rows,
                "metadata": {
                    "school": workbook_school,
                    "api_school": api_school,
                    "college": college,
                    "major_name": major_name,
                    "detail_id": detail_id,
                    "in_scope": in_scope,
                    "roster_items": len(rows),
                },
            }
        )
    except urllib.error.HTTPError as exc:
        result["error"] = f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    args = parse_args()
    targets = read_api_targets(args.provenance.resolve())
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(fetch, target): target for target in targets}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 20 == 0 or index == len(futures):
                print(f"fetched {index}/{len(futures)}", flush=True)
    rows = [row for result in results for row in result["rows"]]
    year_rows = [row for result in results for row in result["year_rows"]]
    rows.sort(key=lambda row: (row["school"], row["college"], int(row["year"]), row["repeat_url"]))
    fields = [
        "school",
        "api_school",
        "college",
        "major_name",
        "detail_id",
        "year",
        "repeat_title",
        "repeat_url",
        "api_url",
        "in_scope",
        "retrieved_at",
    ]
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    with args.output.resolve().open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    year_rows.sort(key=lambda row: (row["school"], row["college"], int(row["year"]), row["detail_id"]))
    year_fields = [
        "school",
        "api_school",
        "college",
        "major_name",
        "detail_id",
        "year",
        "reported_cutoff",
        "reported_admitted_min",
        "reported_admitted_count",
        "reported_retest_count",
        "reported_report_ratio",
        "repeat_title",
        "repeat_url",
        "api_url",
        "in_scope",
        "retrieved_at",
    ]
    args.year_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    with args.year_output.resolve().open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=year_fields)
        writer.writeheader()
        writer.writerows(year_rows)

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_targets": len(targets),
        "successful_api_targets": sum(result["status"] == "ok" for result in results),
        "failed_api_targets": sum(result["status"] != "ok" for result in results),
        "index_rows": len(rows),
        "year_index_rows": len(year_rows),
        "in_scope_rows": sum(bool(row["in_scope"]) for row in rows),
        "schools": len({row["school"] for row in rows if row["in_scope"]}),
        "school_years": len({(row["school"], row["year"]) for row in rows if row["in_scope"]}),
        "privacy": "Only school/program/roster URL metadata was retained; commentTreeVO was discarded in memory.",
        "programs": [result["metadata"] for result in results if result["status"] == "ok"],
        "errors": [
            {"api_url": result["api_url"], "schools": result["workbook_schools"], "error": result["error"]}
            for result in results
            if result["status"] != "ok"
        ],
    }
    args.audit.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.audit.resolve().write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in audit.items() if key not in {"programs", "errors"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
