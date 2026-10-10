"""Enforce the public aggregate / private row label-validation gates.

This is an idempotent postcondition check for OCR outputs.  It is useful when
an interrupted or older extraction run completed under a weaker rule.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_VALIDATION_TIERS = {
    "four_summary_reconciled",
    "count_available_summary_and_structure_reconciled",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program-audit", type=Path, default=ROOT / "data" / "processed" / "candidate_label_audit.csv")
    parser.add_argument("--image-audit", type=Path, default=ROOT / "data" / "processed" / "roster_ocr_audit.csv")
    parser.add_argument("--candidates", type=Path, default=ROOT / "data" / "private" / "candidate_initial_scores.csv")
    parser.add_argument("--audit", type=Path, default=ROOT / "data" / "audit" / "candidate_score_extraction.json")
    return parser.parse_args()


def truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "是"])


def main() -> None:
    args = parse_args()
    programs = pd.read_csv(args.program_audit, encoding="utf-8-sig")
    old_valid = truthy(programs["validation_pass"])
    if "validation_tier" not in programs:
        # Older extracts did not retain the tier.  Only fully reconciled rows
        # can be recovered safely from their four independent summaries.
        reference_complete = programs[
            ["reference_n", "reference_min", "reference_median", "reference_max"]
        ].notna().all(axis=1)
        programs["validation_tier"] = "not_reconciled"
        programs.loc[old_valid & reference_complete, "validation_tier"] = (
            "four_summary_reconciled"
        )
    allowed_tier = programs["validation_tier"].isin(ALLOWED_VALIDATION_TIERS)
    strict_valid = old_valid & allowed_tier
    demoted = old_valid & ~allowed_tier
    programs.loc[demoted, "validation_pass"] = False
    programs.loc[demoted, "validation_status"] = "independent_summary_incomplete"
    programs.loc[demoted, "q10_exact"] = pd.NA
    programs.loc[demoted, "selected_asset_count"] = 0
    model_count_column = "model_n" if "model_n" in programs else "extracted_n"
    programs["model_label_eligible"] = strict_valid & pd.to_numeric(
        programs[model_count_column], errors="coerce"
    ).ge(10)
    programs.to_csv(args.program_audit, index=False, encoding="utf-8-sig")
    valid_keys = {
        (str(row.school), int(row.year))
        for row in programs.loc[programs["model_label_eligible"]].itertuples(index=False)
    }
    candidates = pd.read_csv(args.candidates, encoding="utf-8-sig")
    keep_key = pd.Series(
        [(str(school), int(year)) in valid_keys for school, year in zip(candidates["school"], candidates["year"])],
        index=candidates.index,
    )
    keep = keep_key & truthy(candidates["model_eligible"])
    candidates["model_eligible"] = keep
    special = candidates["candidate_type"].eq("special")
    candidates.loc[~keep & ~special, "candidate_type"] = "unknown"
    candidates.loc[~keep, "adjustment_status"] = "unknown"
    candidates.loc[~keep, "review_status"] = "machine_extracted_not_label_validated"
    candidates.to_csv(args.candidates, index=False, encoding="utf-8-sig")

    if args.image_audit.exists():
        images = pd.read_csv(args.image_audit, encoding="utf-8-sig")
        images["selected_for_exact_label"] = [
            bool(selected) and (str(school), int(year)) in valid_keys
            for selected, school, year in zip(
                truthy(images["selected_for_exact_label"]), images["school"], images["year"]
            )
        ]
        images.to_csv(args.image_audit, index=False, encoding="utf-8-sig")

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    validated = programs.loc[strict_valid].copy()
    model_validated = programs.loc[programs["model_label_eligible"]].copy()
    audit["model_eligible_rows"] = int(keep.sum())
    audit["validated_exact_programs"] = int(len(validated))
    audit["model_eligible_exact_programs"] = int(len(model_validated))
    audit["validated_by_year"] = dict(Counter(str(int(year)) for year in validated["year"]))
    audit["validated_programs"] = [
        {
            "school": str(row.school),
            "year": int(row.year),
            "n": int(getattr(row, model_count_column)),
            "q10_exact": float(row.q10_exact),
            "min": float(getattr(row, "model_min", row.extracted_min)),
            "median": float(getattr(row, "model_median", row.extracted_median)),
            "max": float(getattr(row, "model_max", row.extracted_max)),
            "validation_tier": str(row.validation_tier),
        }
        for row in validated.itertuples(index=False)
    ]
    audit["strict_gate"] = {
        "allowed_validation_tiers": sorted(ALLOWED_VALIDATION_TIERS),
        "legacy_structural_tier_requires": [
            "count reconciliation",
            "available independent summary reconciliation",
            "explicit admitted/excluded colour legend",
            "monotone score order",
            "rank coverage >= 0.90",
            "median OCR confidence >= 0.85",
        ],
        "demoted_unapproved_tier_programs": int(demoted.sum()),
    }
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"validated_exact_programs": len(validated), "model_eligible_exact_programs": len(model_validated), "model_eligible_rows": int(keep.sum()), "demoted": int(demoted.sum())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
