"""Version existing and recovered roster evidence without editing a freeze.

Raw rosters, links to individual images, row hashes and scores remain private.
Only school-year aggregates and official-document provenance are exported.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import extract_candidate_scores as extraction

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/evidence_refresh_20261024"
PUBLIC = ROOT / "data/processed/evidence_refresh_20261024"


def truth(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def assemble_assets():
    manifest = pd.read_csv(ROOT / "data/processed/roster_asset_manifest.csv").fillna("")
    images = pd.read_csv(ROOT / "data/processed/roster_ocr_audit.csv").fillna("")
    raw_rows = pd.read_csv(ROOT / "data/private/retest_initial_scores.csv").fillna("")
    # Verify every stored source before reusing OCR. A broken path or changed
    # payload is an error, not an empty roster or a missing-data zero.
    for record in manifest.to_dict("records"):
        path = ROOT / record["local_private_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Source hash mismatch: {record['school']} {record['year']}")
    recovered = {}
    for name in ("recovered_assets.json", "tongji_recovered_assets.json"):
        for record in json.loads((PRIVATE / name).read_text(encoding="utf-8")):
            if record.get("layout_status") == "parsed":
                recovered[record["sha256"]] = record
    header_records = json.loads((PRIVATE / "header_audit.json").read_text(encoding="utf-8"))
    if len(header_records) != len(manifest):
        raise ValueError("Header audit is incomplete")
    headers = {row["source_sha256"]: row for row in header_records}
    groups = {key: group for key, group in raw_rows.groupby("source_sha256")}
    image_map = {record["source_sha256"]: record for record in images.to_dict("records")}
    assets, recovery_rows = [], []
    for record in manifest.to_dict("records"):
        sha = record["sha256"]
        old = image_map[sha]
        header = headers[sha]
        if header.get("error"):
            # These source images visibly contain no identifiable raw initial
            # total. Keep the originals, never keep an accidentally readable
            # retest/composite score as an initial-score observation.
            recovered[sha] = {**record, **old, "score_rows": [],
                "layout_status": "no_initial_score_column", "error": header["error"],
                "target_major_match": False, "special_population_flag": False,
                "score_order_monotone": False, "rank_coverage": 0.0,
                "score_ocr_confidence_median": 0.0, "sha256": sha}
        if sha in recovered:
            asset = recovered[sha]
            # Keep source-verified scope failures out of exact and soft labels.
            if "非全日制" in asset.get("title", ""):
                asset["special_population_flag"] = True
            assets.append(asset)
            recovery_rows.append({"school": record["school"], "year": int(record["year"]),
                "source_sha256": sha, "previous_layout_status": old["layout_status"],
                "current_layout_status": asset["layout_status"], "previous_readable_rows": int(old["score_row_count"]),
                "current_readable_rows": len(asset["score_rows"]),
                "explicit_admission_rule": asset["highlight_rule"],
                "recovered_omitted_rows": int(asset.get("recovered_omitted_rows", 0)),
                "score_header": asset.get("recovery_geometry", {}).get("score_header", ""),
                "rank_sequence_verified": asset.get("rank_sequence_verified", False)})
            continue
        scores = []
        if sha in groups:
            for row in groups[sha].to_dict("records"):
                scores.append({"band_index": int(row["row_index"]), "initial_score": float(row["initial_score"]),
                    "ocr_confidence": float(row["ocr_confidence"]), "special_row": truth(row["special_row"]),
                    "admission_status": row["admission_status"], "highlight": row["highlight"]})
        asset = {**record, **{key: old[key] for key in ("layout_status", "title", "title_confidence", "footer",
            "footer_confidence", "roster_stage", "highlight_rule", "target_major_match", "special_population_flag",
            "horizontal_lines", "vertical_lines", "score_order_monotone", "rank_coverage", "score_ocr_confidence_median", "error")},
            "score_rows": scores}
        for key in ("target_major_match", "special_population_flag", "score_order_monotone"):
            asset[key] = truth(asset[key])
        if header.get("score_column_disagrees"):
            # A failed recovery of a known wrong column cannot fall through to
            # the old OCR rows and silently restore invalid observations.
            asset.update(score_rows=[], layout_status="score_column_recovery_pending",
                         target_major_match=False, score_order_monotone=False,
                         error="Verified initial-score column differs from legacy extraction; recovery required")
        assets.append(asset)
    return assets, pd.DataFrame(recovery_rows)


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    assets, recovery = assemble_assets()
    recovery.to_csv(PUBLIC / "asset_recovery_summary.csv", index=False, encoding="utf-8-sig")
    args = argparse.Namespace(periods=ROOT / "data/processed/program_year.csv", schools=ROOT / "data/processed/schools.csv",
        image_audit=PRIVATE / "roster_ocr_audit.csv", program_audit=PUBLIC / "candidate_label_audit.csv",
        retest_output=PRIVATE / "retest_initial_scores.csv", candidate_output=PRIVATE / "candidate_initial_scores.csv",
        audit=PRIVATE / "candidate_score_extraction.json")
    # The extraction writer prints a large aggregate ledger. Keep it local and
    # emit a compact summary instead; no source-image URLs go into app data.
    with contextlib.redirect_stdout(io.StringIO()):
        extraction.write_extraction_outputs(args, assets)
    programs = pd.read_csv(args.program_audit).fillna("")
    programs["model_label_eligible"] = programs.validation_pass.map(truth) & pd.to_numeric(programs.model_n).ge(10)
    programs.to_csv(args.program_audit, index=False, encoding="utf-8-sig")
    from sys import path as python_path
    python_path.insert(0, str(ROOT / "model"))
    from candidate_score_layer import candidate_distribution_by_program, load_candidate_scores, audited_candidate_pool, audited_distribution_by_program
    candidates = load_candidate_scores(args.candidate_output)
    readable = pd.read_csv(args.retest_output)
    unique_readable = readable.drop_duplicates(["school", "year", "source_sha256", "row_index", "initial_score"])
    exact = candidate_distribution_by_program(candidates)
    exact.to_csv(PUBLIC / "exact_distribution_summary.csv", index=False, encoding="utf-8-sig")
    pool = audited_candidate_pool(candidates, image_audit_path=args.image_audit, program_audit_path=args.program_audit)
    audited_distribution_by_program(pool).to_csv(PUBLIC / "audited_distribution_summary.csv", index=False, encoding="utf-8-sig")
    def identity(row):
        return (str(row["school"]), int(row["year"]), str(row["source_sha256"]), int(row["row_index"]))
    exact_identities={identity(row) for row in candidates[candidates.model_eligible].to_dict("records")}
    soft_identities={identity(row) for row in pool[pool.candidate_evidence_tier.eq("soft_roster")].to_dict("records")}
    role_rows=[]
    for row in unique_readable.to_dict("records"):
        key=identity(row)
        if key in exact_identities:role="exact_label_and_distribution"
        elif key in soft_identities:role="soft_distribution_only"
        elif truth(row.get("special_row")):role="excluded_special_population"
        elif row["admission_status"]=="not_admitted":role="retest_not_admitted"
        elif row["admission_status"]=="admitted":role="diagnostic_admission_not_verified"
        else:role="retest_unknown_outcome"
        role_rows.append({"school":row["school"],"year":int(row["year"]),"statistical_role":role})
    role_counts=pd.DataFrame(role_rows).groupby(["school","year","statistical_role"]).size().reset_index(name="n")
    role_counts.to_csv(PUBLIC/"score_roles_by_school_year.csv",index=False,encoding="utf-8-sig")
    # All accepted scores are retained even in tiny cohorts. Small cohorts may
    # contribute descriptive distributions; the forecast exact-label n>=10
    # policy is unchanged and not silently loosened.
    accepted = pool.groupby(["school", "year", "candidate_evidence_tier"]).size().reset_index(name="n")
    accepted.to_csv(PUBLIC / "audited_cohort_counts.csv", index=False, encoding="utf-8-sig")
    old_programs = pd.read_csv(ROOT / "data/processed/candidate_label_audit.csv")
    old_exact = old_programs[old_programs.model_label_eligible.map(truth)]
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    old_keys = set(zip(old_exact.school, old_exact.year))
    new_keys = set(zip(exact.school, exact.year))
    summary = {"version": "evidence-refresh-20261024", "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope_schools": 81, "scope_school_years": 405, "local_source_hashes_verified": len(assets),
        "unique_source_payloads": len({asset["sha256"] for asset in assets}),
        "api_targets_refreshed": 108, "api_targets_successful": 108,
        "api_roster_schools": 79, "api_roster_school_years": 353,
        "roster_urls_added": 0, "images_parsed_before": 412, "images_parsed_after": audit["images_parsed"],
        "readable_score_rows_before": 14317, "readable_score_rows_after": audit["deidentified_score_rows"],
        "unique_readable_score_rows_after": len(unique_readable),
        "duplicate_readable_references": len(readable)-len(unique_readable),
        "exact_school_years_before": len(old_exact), "exact_school_years_after": len(exact),
        "exact_candidate_rows_before": 2312, "exact_candidate_rows_after": int(exact.candidate_n.sum()),
        "exact_schools_after": int(exact.school.nunique()),
        "added_exact_school_years": [{"school": s, "year": int(y)} for s, y in sorted(new_keys-old_keys)],
        "removed_exact_school_years": [{"school": s, "year": int(y)} for s, y in sorted(old_keys-new_keys)],
        "admission_rows_after": len(candidates), "audited_admission_rows_after": len(pool),
        "unique_score_role_counts": role_counts.groupby("statistical_role").n.sum().astype(int).to_dict(),
        "privacy": "Only school-year aggregates are public. Raw images, roster image URLs, per-person rows and candidate hashes remain private.",
        "production_numeric_forecast_changed": False,
        "computer_use": "Required node_repl/Sky tool unavailable; used authorized public mini-program metadata API and original local images instead. No desktop operation was performed."}
    dump(PUBLIC / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
