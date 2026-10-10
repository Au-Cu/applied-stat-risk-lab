"""Reconcile live mini-program values with the compiled school-year panel.

The resulting table is supplemental evidence only.  It never overwrites the
workbook value; a link is created only when the independently fetched value
matches the processed value within a declared tolerance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERIODS = ROOT / "data" / "processed" / "program_year.csv"
DEFAULT_INDEX = ROOT / "data" / "processed" / "mini_program_year_index.csv"
DEFAULT_URL_AUDIT = ROOT / "data" / "processed" / "source_url_audit.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "program_year_supplemental_provenance.csv"
DEFAULT_AUDIT = ROOT / "data" / "audit" / "supplemental_provenance.json"

FIELD_MAP = {
    "reported_cutoff": ("cutoff", 0.51, "schoolMajorVO.repeatGrade"),
    "reported_admitted_min": ("admitted_min", 0.51, "schoolMajorVO.repeatMinGrade"),
    "reported_admitted_count": ("admitted_count", 0.01, "schoolMajorVO.enterpersonVolunteerNum"),
    "reported_retest_count": ("retest_count", 0.01, "schoolMajorVO.enterpersonRepeatNum"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build value-reconciled supplemental provenance.")
    parser.add_argument("--periods", type=Path, default=DEFAULT_PERIODS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--url-audit", type=Path, default=DEFAULT_URL_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    return parser.parse_args()


def number(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def main() -> None:
    args = parse_args()
    periods = pd.read_csv(args.periods, encoding="utf-8-sig")
    index = pd.read_csv(args.index, encoding="utf-8-sig")
    index = index[
        index["in_scope"].astype(str).str.lower().isin(["true", "1", "yes"])
        & pd.to_numeric(index["year"], errors="coerce").between(2022, 2026)
    ].copy()
    period_map = {
        (row["school"], int(row["year"])): row
        for row in periods.to_dict("records")
    }
    matches = []
    discrepancies = []
    for api_row in index.to_dict("records"):
        key = (api_row["school"], int(api_row["year"]))
        panel = period_map.get(key)
        if panel is None:
            continue
        for api_field, (panel_field, tolerance, api_path) in FIELD_MAP.items():
            observed = number(api_row.get(api_field))
            compiled = number(panel.get(panel_field))
            if observed is None or compiled is None:
                continue
            difference = observed - compiled
            base = {
                "school": key[0],
                "year": key[1],
                "college": api_row.get("college", ""),
                "major_name": api_row.get("major_name", ""),
                "field_name": panel_field,
                "compiled_value": compiled,
                "independent_value": observed,
                "difference": difference,
                "tolerance": tolerance,
                "api_field_path": api_path,
                "api_url": api_row["api_url"],
                "roster_url": api_row.get("repeat_url", ""),
                "api_retrieved_at": api_row.get("retrieved_at", ""),
                "source_type": "mini_program_api_value_reconciled",
                "authority_grade": "secondary_structured",
                "source_id": hashlib.sha256(api_row["api_url"].encode("utf-8")).hexdigest()[:16],
            }
            if abs(difference) <= tolerance:
                matches.append({**base, "reconciliation_status": "matched"})
            else:
                discrepancies.append({**base, "reconciliation_status": "mismatch"})
    match_frame = pd.DataFrame(matches).drop_duplicates(
        ["school", "year", "college", "field_name", "api_url"]
    ) if matches else pd.DataFrame()
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    match_frame.to_csv(args.output.resolve(), index=False, encoding="utf-8-sig")

    failed_third_party = set()
    if args.url_audit.exists():
        urls = pd.read_csv(args.url_audit, encoding="utf-8-sig")
        failed = urls[
            urls["reachability"].ne("reachable")
            & urls["source_domain"].astype(str).str.contains("ludengkaoyan|sjds", regex=True)
        ]
        for row in failed.to_dict("records"):
            schools = str(row.get("schools", "")).split(";")
            years = str(row.get("years", "")).split(";")
            for school in schools:
                for year in years:
                    if school and year.isdigit():
                        failed_third_party.add((school, int(year)))
    supplemented_keys = {(row["school"], int(row["year"])) for row in matches}
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_field_sources": len(match_frame),
        "matched_school_years": len(supplemented_keys),
        "matched_by_field": match_frame["field_name"].value_counts().to_dict() if not match_frame.empty else {},
        "mismatched_candidates": len(discrepancies),
        "dead_third_party_school_years": len(failed_third_party),
        "dead_third_party_school_years_with_live_reconciled_supplement": len(failed_third_party & supplemented_keys),
        "policy": "Supplemental evidence never overwrites a compiled value; only matching values are linked.",
        "mismatch_sample": discrepancies[:50],
    }
    args.audit.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.audit.resolve().write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in audit.items() if key != "mismatch_sample"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
