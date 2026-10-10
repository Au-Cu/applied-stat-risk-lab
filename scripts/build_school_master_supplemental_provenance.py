"""Reconcile non-personal programme fields against the public detail API.

The API is secondary evidence.  A URL is attached only where its value is
equal or semantically equivalent to the compiled school-master value; partial
text support is kept separate and never described as full-field validation.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schools", type=Path, default=ROOT / "data" / "processed" / "schools.csv")
    parser.add_argument("--index", type=Path, default=ROOT / "data" / "processed" / "mini_program_roster_index.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "processed" / "school_master_supplemental_provenance.csv",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=ROOT / "data" / "audit" / "school_master_supplemental_provenance.json",
    )
    return parser.parse_args()


def compact(value) -> str:
    return re.sub(r"[\s,，、;；:：()（）\[\]【】]", "", str(value or "")).lower()


def canonical_subject(value: str) -> str:
    value = compact(value)
    aliases = {
        "政治": "101思想政治理论",
        "思想政治理论": "101思想政治理论",
        "数三": "数学三",
        "数二": "数学二",
        "数一": "数学一",
    }
    return aliases.get(value, value)


def fetch_program(api_url: str) -> dict:
    request = urllib.request.Request(api_url, headers={"User-Agent": "applied-stat-risk-lab/0.2 provenance-audit"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)
    data = payload.get("data") or payload
    # Do not retain commentTreeVO or any other user-generated content.
    return dict(data.get("schoolMajorVO") or {})


def main() -> None:
    args = parse_args()
    schools = pd.read_csv(args.schools, encoding="utf-8-sig")
    index = pd.read_csv(args.index, encoding="utf-8-sig")
    targets = index[["school", "detail_id", "api_url"]].drop_duplicates().to_dict("records")
    compiled = {str(row.school): row._asdict() for row in schools.itertuples(index=False)}
    rows: list[dict] = []
    errors: list[dict] = []

    for target in targets:
        school = str(target["school"])
        if school not in compiled:
            continue
        try:
            program = fetch_program(str(target["api_url"]))
        except Exception as exc:
            errors.append({"school": school, "api_url": target["api_url"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        source_values = {
            "unit_2026": program.get("college"),
            "study_mode": program.get("train"),
            "duration": program.get("year"),
        }
        subjects = [part for part in re.split(r"[,，、;；]", str(program.get("startSubjects") or "")) if part.strip()]
        subject_fields = ["politics_subject", "english_subject", "math_subject", "major_subject"]
        for field, value in zip(subject_fields, subjects):
            source_values[field] = value

        for field, source_value in source_values.items():
            compiled_value = compiled[school].get(field)
            if not source_value or not compiled_value:
                continue
            lhs = canonical_subject(source_value) if field in subject_fields else compact(source_value)
            rhs = canonical_subject(compiled_value) if field in subject_fields else compact(compiled_value)
            if lhs != rhs:
                continue
            rows.append(
                {
                    "school": school,
                    "field_name": field,
                    "compiled_value": compiled_value,
                    "independent_value": source_value,
                    "reconciliation_status": "semantic_equivalent" if str(compiled_value) != str(source_value) else "exact_match",
                    "api_field_path": {
                        "unit_2026": "schoolMajorVO.college",
                        "study_mode": "schoolMajorVO.train",
                        "duration": "schoolMajorVO.year",
                        "politics_subject": "schoolMajorVO.startSubjects[0]",
                        "english_subject": "schoolMajorVO.startSubjects[1]",
                        "math_subject": "schoolMajorVO.startSubjects[2]",
                        "major_subject": "schoolMajorVO.startSubjects[3]",
                    }[field],
                    "api_url": target["api_url"],
                    "detail_id": target["detail_id"],
                    "source_type": "mini_program_api_value_reconciled",
                    "authority_grade": "secondary_structured",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    output = pd.DataFrame(rows).drop_duplicates(["school", "field_name", "api_url"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False, encoding="utf-8-sig")
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_targets": len(targets),
        "matched_field_sources": int(len(output)),
        "matched_schools": int(output["school"].nunique()) if len(output) else 0,
        "matched_by_field": output["field_name"].value_counts().to_dict() if len(output) else {},
        "errors": errors,
        "policy": "Only exact or predeclared semantic-equivalent values are linked; the API remains secondary evidence.",
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
