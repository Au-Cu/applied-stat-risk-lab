"""Independent arithmetic and non-mutation checks for the quota experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from deadline_quota_research import attach_current_features, build_ledger
from experiment_deadline_quota import DATASET, DEFAULT_OUT, ROOT, metrics, QUANTILES, text_hash_lf
from forecast_freeze import sha256_file
from experiment_statistical_inference import evaluate as existing_v6_evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(out / "rolling_predictions.csv")
    comparison = pd.read_csv(out / "comparison.csv")
    errors = []
    checks = []
    newline_only_differences = []

    def check(condition, label):
        checks.append(label)
        if not condition:
            errors.append(label)

    for item in summary["inputs"]:
        raw_match = sha256_file(ROOT / item["path"]) == item["sha256"]
        lf_match = text_hash_lf(ROOT / item["path"]) == item.get("sha256_lf")
        check(raw_match or lf_match, "input SHA256: " + item["path"])
        if not raw_match and lf_match:
            newline_only_differences.append(item["path"])
    for name, digest in summary["frozen_output_hashes"].items():
        raw_match = sha256_file(ROOT / name) == digest
        lf_match = text_hash_lf(ROOT / name) == summary.get("frozen_output_hashes_lf", {}).get(name)
        check(raw_match or lf_match, "frozen unchanged: " + name)
        if not raw_match and lf_match:
            newline_only_differences.append(name)
    check(not predictions.duplicated(["kind", "school", "year"]).any(), "unique model-school-year keys")
    check((predictions.latest_target_training_year < predictions.year).all(), "all target training strictly earlier than prediction year")
    quantiles = predictions[[f"pred_q{q:02d}" for q in QUANTILES]].to_numpy(float)
    check(np.isfinite(quantiles).all() and (np.diff(quantiles, axis=1) >= 0).all(), "finite monotone quantiles")
    check((predictions[["state_variance", "national_variance", "future_cohort_variance"]] >= 0).all().all(), "nonnegative variance components")
    check(predictions.loc[predictions.quota_available.eq(0), "quota_current_net"].isna().all(), "missing quota never converted to N=0")
    observed = predictions[predictions.quota_available.eq(1)]
    check((observed.quota_source_year == observed.year).all(), "current-year quota only, no carry-forward")
    check((observed.quota_current_net > 0).all(), "positive observed ordinary-cohort quota")
    check(predictions.quota_log2_change.isna().eq(predictions.quota_change_available.eq(0)).all(), "change missingness retained")
    check(predictions.year.lt(2027).all(), "no 2027 outcome used")
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    check(all(r.get("model_eligible") is False for r in payload["records"]), "parent data not promoted")
    ledger = build_ledger(payload, pd.read_csv(ROOT / "data/processed/schools.csv"))
    for policy, g in predictions.groupby("policy"):
        rebuilt = attach_current_features(g.drop(columns=[c for c in g if c.startswith("quota_")]), ledger, policy)
        for column in ("quota_current_net", "quota_log2", "quota_log2_change", "quota_available", "quota_change_available", "quota_source_year"):
            check(np.allclose(rebuilt[column], g[column], equal_nan=True), f"feature reconstructed from ledger: {policy}/{column}")
    for kind, group in predictions.groupby("kind"):
        selected = group[group.is_paired_exact]
        check(len(selected) == 54, "same 54 exact evaluation rows: " + kind)
        expected = comparison[comparison.kind.eq(kind) & comparison.view.eq("exact_paired")].iloc[0]
        actual = metrics(selected)
        for field in ("mae", "wis", "q90_coverage", "q90_minus_q50", "q95_pinball"):
            check(abs(actual[field] - expected[field]) < 1e-9, f"metric recomputation: {kind}/{field}")
        independent = existing_v6_evaluate(selected)
        check(abs(actual["mae"] - independent["mae"]) < 1e-9 and abs(actual["wis"] - independent["wis"]) < 1e-9,
            "MAE/WIS agree with independent pre-existing V6 evaluator: " + kind)
    fits = json.loads((out / "origin_fits.json").read_text(encoding="utf-8"))
    check(all(r["converged"] for r in fits), "all 36 quota fits converged")
    check(all(r["latest_target_training_year"] < r["origin"] for r in fits), "all fit origins isolated")
    check(all(r["passed"] for r in summary["baseline_reproduction"]), "V6 baseline reproduced on every quantile")
    check(all(not r["enough_independent_coverage"] for r in summary["gates"]), "coverage gate blocks premature promotion")
    check(summary["status"] == "research_only_no_production_promotion", "research-only release status")
    report = {"status": "passed" if not errors else "failed", "checks": len(checks),
        "prediction_rows": len(predictions), "candidate_fits": len(fits), "errors": errors,
        "git_checkout_newline_only_differences": newline_only_differences}
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
