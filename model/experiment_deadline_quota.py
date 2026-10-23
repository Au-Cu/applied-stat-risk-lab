"""Deadline-visible quota backtests. Research only: never writes production.

Run from the repository root with the project's Python environment. All inputs
are public school-year aggregates, not candidate identities or private rosters.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

import numpy as np
import pandas as pd
from scipy.stats import norm

from deadline_quota_research import (
    POLICIES, QuotaDesign, attach_current_features, build_ledger, fit_covariate_state,
)
import experiment_statistical_inference as v6
from forecast_freeze import sha256_file
from verify_frozen_forecast_outputs import FROZEN_OUTPUTS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output/experiments/deadline_quota_20261024"
DATASET = ROOT / "output/research/quota_deadline_20261023_r2/quota_deadline_dataset.json"
DISTRIBUTIONS = ROOT / "output/experiments/v5_hierarchical_distribution_20261009/candidate_distribution_summary.csv"
PAIRED = ROOT / "output/experiments/v5_exact_labels_20261009/exact_evaluation/paired_exact_backtest.csv"
SEED = 20261024
ORIGINS = (2024, 2025, 2026)
QUANTILES = (5, 10, 20, 50, 80, 90, 95)


def scored_rows(frame):
    y = frame.actual.to_numpy(float)
    median = frame.pred_q50.to_numpy(float)
    result = pd.DataFrame(index=frame.index)
    result["ae"] = np.abs(y - median)
    result["squared_error"] = (y - median) ** 2
    result["error"] = y - median
    wis = .5 * result.ae.to_numpy()
    for low, high in ((5, 95), (10, 90), (20, 80)):
        lower = frame[f"pred_q{low:02d}"].to_numpy(float)
        upper = frame[f"pred_q{high:02d}"].to_numpy(float)
        alpha = 2. * low / 100
        score = upper - lower + 2 / alpha * (np.maximum(lower - y, 0) + np.maximum(y - upper, 0))
        wis += alpha / 2 * score
    result["wis"] = wis / 3.5
    for q in QUANTILES:
        prediction = frame[f"pred_q{q:02d}"].to_numpy(float)
        difference = y - prediction
        result[f"coverage_{q}"] = (difference <= 0).astype(float)
        result[f"pinball_{q}"] = np.maximum(q / 100 * difference, (q / 100 - 1) * difference)
        result[f"upper_width_{q}"] = prediction - median
    return result


def metrics(frame):
    if frame.empty:
        return {"n": 0, "schools": 0, "years": 0}
    losses = scored_rows(frame)
    w = frame.evaluation_weight.to_numpy(float)
    result = {"n": len(frame), "schools": int(frame.school.nunique()), "years": int(frame.year.nunique()),
        "mae": float(losses.ae.mean()), "weighted_mae": float(np.average(losses.ae, weights=w)),
        "rmse": float(np.sqrt(losses.squared_error.mean())),
        "bias_actual_minus_prediction": float(losses.error.mean()),
        "wis": float(losses.wis.mean()), "weighted_wis": float(np.average(losses.wis, weights=w)),
        "year_equal_mae": float(frame.assign(ae=losses.ae).groupby("year").ae.mean().mean()),
        "quota_observed_rows": int(frame.quota_available.sum()),
        "quota_observed_schools": int(frame.loc[frame.quota_available.eq(1), "school"].nunique()),
        "effective_weight_n_kish_not_cluster_n": float(w.sum() ** 2 / np.square(w).sum())}
    for q in QUANTILES:
        result[f"q{q:02d}_coverage"] = float(losses[f"coverage_{q}"].mean())
        result[f"q{q:02d}_pinball"] = float(losses[f"pinball_{q}"].mean())
        if q >= 50:
            result[f"q{q:02d}_minus_q50"] = float(losses[f"upper_width_{q}"].mean())
    return result


def eval_views(frame):
    yield "exact_paired", frame[frame.is_paired_exact]
    yield "exact_all_available", frame[frame.label_kind.eq("audited_empirical_q10")]
    yield "proxy_only_diagnostic", frame[frame.label_kind.eq("proxy_q10")]


def paired_uncertainty(frame, baseline, groupby, seed=SEED):
    paired = frame.merge(baseline[["school", "year", "pred_q50", "row_wis"]],
        on=["school", "year"], suffixes=("", "_baseline"), validate="one_to_one")
    mae_delta = np.abs(paired.actual - paired.pred_q50) - np.abs(paired.actual - paired.pred_q50_baseline)
    paired["mae_delta"] = mae_delta
    paired["wis_delta"] = paired.row_wis - paired.row_wis_baseline
    groups = [g for _, g in paired.groupby(groupby, sort=True)]
    result = {"cluster": groupby, "clusters": len(groups), "n": len(paired),
        "mae_difference": float(mae_delta.mean()) if len(paired) else None,
        "wis_difference": float(paired.wis_delta.mean()) if len(paired) else None,
        "limitation": "Observed-cluster resampling only; not iid school-year inference or evidence of future-year significance."}
    if len(groups) < 2:
        result["mae_ci90"] = result["wis_ci90"] = None
        result["limitation"] = "Fewer than two clusters; no informative cluster-bootstrap interval."
        return result
    values = np.array([[len(g), g.mae_delta.sum(), g.wis_delta.sum()] for g in groups], float)
    rng = np.random.default_rng(seed)
    sums = values[rng.integers(0, len(values), size=(4000, len(values)))].sum(axis=1)
    for index, name in ((1, "mae"), (2, "wis")):
        result[name + "_ci90"] = np.quantile(sums[:, index] / sums[:, 0], [.05, .95]).tolist()
    return result


def freeze_hashes():
    return {name: sha256_file(ROOT / name) for name in sorted(FROZEN_OUTPUTS)}


def text_hash_lf(path):
    """Git may check out text as CRLF on Windows; retain both audit hashes."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write_csv(frame, path):
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    forbidden = (ROOT / "data", ROOT / "app", ROOT / "paper")
    if any(out == path or path in out.parents for path in forbidden):
        raise SystemExit("Research outputs cannot be written into production, data or paper directories.")
    out.mkdir(parents=True, exist_ok=True)
    before = freeze_hashes()
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    periods = pd.read_csv(ROOT / "data/processed/program_year.csv")
    schools = pd.read_csv(ROOT / "data/processed/schools.csv")
    distributions = pd.read_csv(DISTRIBUTIONS)
    paired = pd.read_csv(PAIRED)
    national = json.loads((ROOT / "data/processed/national_lines.json").read_text(encoding="utf-8"))
    ledger = build_ledger(payload, schools)
    write_csv(ledger, out / "record_eligibility.csv")

    all_features = pd.concat([attach_current_features(
        pd.MultiIndex.from_product([schools.school, range(2022, 2028)], names=["school", "year"]).to_frame(index=False),
        ledger, policy).assign(policy=policy) for policy in POLICIES], ignore_index=True)
    write_csv(all_features, out / "current_year_quota_features.csv")
    exact = distributions[["school", "year", "score_q10"]]
    test = periods.merge(exact, on=["school", "year"], how="left", validate="one_to_one")
    test = test[test.year.isin(ORIGINS)].copy()
    test["actual"] = test.score_q10.combine_first(test.q10_value)
    test["label_kind"] = np.where(test.score_q10.notna(), "audited_empirical_q10", "proxy_q10")
    test["evaluation_weight"] = np.where(test.score_q10.notna(), 1., test.target_weight)
    test = test[test.actual.notna() & ((test.score_q10.notna()) | (test.target_weight >= .12))]
    paired_keys = set(zip(paired.school, paired.year))
    test["is_paired_exact"] = [(s, y) in paired_keys for s, y in zip(test.school, test.year)]
    definitions = [("availability", 10.), ("level", 10.), ("change", 10.), ("level_change", 10.),
        ("level_change", 5.), ("level_change", 20.)]
    predictions, fits = [], []
    reproduction = []
    v6_reference = pd.read_csv(v6.OUT / "rolling_predictions.csv")
    for origin in ORIGINS:
        observations, calibration = v6.calibrate_observations(periods, distributions, origin)
        earlier = distributions[distributions.year < origin]
        origin_test = test[test.year.eq(origin)].copy()
        baseline = v6.fit_state(observations, "random_intercept")
        for policy in POLICIES:
            train = attach_current_features(observations, ledger, policy)
            target = attach_current_features(origin_test, ledger, policy)
            models = [("baseline_v6", baseline, None, 0.)] if policy == POLICIES[0] else []
            for kind, slope_sd in definitions:
                design = QuotaDesign.fit(train, kind, slope_sd)
                model = fit_covariate_state(train, design,
                    (baseline.school_variance, baseline.innovation_variance))
                name = f"{policy}__{kind}__sd{int(slope_sd)}"
                models.append((name, model, design, slope_sd))
                fit = {"origin": origin, "kind": name, "n_training_rows": len(train),
                    "latest_target_training_year": int(train.year.max()),
                    "training_quota_rows": int(train.quota_available.sum()),
                    "training_quota_schools": int(train.loc[train.quota_available.eq(1), "school"].nunique()),
                    "training_quota_change_rows": int(train.quota_change_available.sum()),
                    "intercept": model.intercept, "school_variance": model.school_variance,
                    "innovation_variance": model.innovation_variance, "converged": model.converged,
                    "level_center_log2_training_only": design.level_center,
                    "coefficient_summary": model.slope_summary,
                    "observation_calibration": calibration}
                fits.append(fit)
            for kind, model, design, slope_sd in models:
                for _, r in target.iterrows():
                    margin, statevar = model.predict(r.school, origin) if design is None else model.predict(r.to_dict())
                    line, linevar = v6.national_prediction(national, origin, r.national_zone)
                    local = earlier[earlier.school.eq(r.school)].sort_values("year")
                    cohortvar = float(local.iloc[-1].q10_bootstrap_sd ** 2) if len(local) else calibration["default_sampling_variance"]
                    variance = statevar + linevar + cohortvar
                    row = {"school": r.school, "year": origin, "kind": kind, "policy": policy,
                        "actual": float(r.actual), "label_kind": r.label_kind,
                        "evaluation_weight": float(r.evaluation_weight), "is_paired_exact": bool(r.is_paired_exact),
                        "latest_target_training_year": int(observations.year.max()),
                        "state_variance": statevar, "national_variance": linevar, "future_cohort_variance": cohortvar,
                        "prior_slope_sd": slope_sd,
                        **{c: r[c] for c in target if c.startswith("quota_")}}
                    for q in QUANTILES:
                        row[f"pred_q{q:02d}"] = line + margin + norm.ppf(q / 100) * np.sqrt(variance)
                    predictions.append(row)
                print(f"{origin}: {kind}, test rows={len(target)}", flush=True)
        # Reproduce every stored V6 baseline quantile, not just headline MAE.
        current = pd.DataFrame([r for r in predictions if r["year"] == origin and r["kind"] == "baseline_v6"])
        reference = v6_reference[(v6_reference.year == origin) & v6_reference.kind.eq("random_intercept")]
        comparison = reference.merge(current, on=["school", "year"], suffixes=("_reference", "_new"), validate="one_to_one")
        maximum = max(float(np.abs(comparison[f"pred_q{q:02d}_reference"] - comparison[f"pred_q{q:02d}_new"]).max()) for q in QUANTILES)
        reproduction.append({"origin": origin, "n": len(comparison), "max_abs_quantile_difference": maximum,
            "passed": len(comparison) == len(reference) and maximum < 1e-4})

    prediction = pd.DataFrame(predictions)
    prediction["row_wis"] = scored_rows(prediction).wis
    write_csv(prediction, out / "rolling_predictions.csv")
    metric_rows, yearly, subgroup, reliability, uncertainty = [], [], [], [], []
    baseline = prediction[prediction.kind.eq("baseline_v6")]
    for kind, group in prediction.groupby("kind", sort=False):
        policy = POLICIES[0] if kind == "baseline_v6" else group.policy.iloc[0]
        # Reattach policy-specific coverage also to the common baseline; this
        # makes covered-subset comparisons use identical rows under each policy.
        for view, values in eval_views(group):
            metric_rows.append({"kind": kind, "view": view, **metrics(values)})
            for year, year_values in values.groupby("year"):
                yearly.append({"kind": kind, "view": view, "year": int(year), **metrics(year_values)})
            for q in QUANTILES:
                if len(values):
                    reliability.append({"kind": kind, "view": view, "nominal": q / 100,
                        "observed": float((values.actual <= values[f"pred_q{q:02d}"]).mean()), "n": len(values)})
            if kind != "baseline_v6":
                base_policy = attach_current_features(baseline, ledger, policy)
                base_view = dict(eval_views(base_policy))[view]
                for label, filter_available in (("quota_observed", True), ("quota_missing", False)):
                    selection = values.quota_available.eq(int(filter_available))
                    base_selection = base_view.quota_available.eq(int(filter_available))
                    subgroup.append({"kind": kind, "view": view, "subset": label,
                        "candidate": metrics(values[selection]), "baseline": metrics(base_view[base_selection])})
                for cluster in ("school", "year"):
                    uncertainty.append({"kind": kind, "view": view, "subset": "all",
                        **paired_uncertainty(values, base_view, cluster)})
                    observed = values[values.quota_available.eq(1)]
                    base_observed = base_view[base_view.quota_available.eq(1)]
                    uncertainty.append({"kind": kind, "view": view, "subset": "quota_observed",
                        **paired_uncertainty(observed, base_observed, cluster)})
    result_metrics = pd.DataFrame(metric_rows)
    write_csv(result_metrics, out / "comparison.csv")
    write_csv(pd.DataFrame(yearly), out / "yearly_metrics.csv")
    write_csv(pd.DataFrame(reliability), out / "reliability.csv")
    write_csv(pd.DataFrame([{"kind": k, "school": s, "year": int(y), "actual": g.actual.iloc[0],
        "q50": g.pred_q50.iloc[0], "q90": g.pred_q90.iloc[0], "net_quota": g.quota_current_net.iloc[0],
        "quota_log2_change": g.quota_log2_change.iloc[0], "label_kind": g.label_kind.iloc[0]}
        for (k, s, y), g in prediction[prediction.quota_available.eq(1)].groupby(["kind", "school", "year"])]),
        out / "covered_school_year_predictions.csv")

    paired_baselines = {}
    paired_eval = paired.rename(columns={"q10_exact": "actual"})
    for prefix in ("baseline", "enhanced"):
        values = paired_eval.rename(columns={f"{prefix}_q{q:02d}": f"pred_q{q:02d}" for q in QUANTILES}).copy()
        values = attach_current_features(values, ledger, POLICIES[0])
        values["evaluation_weight"] = 1.
        paired_baselines["frozen_production" if prefix == "baseline" else "v5_exact_enhanced"] = metrics(values)

    gates = []
    base_primary = result_metrics[(result_metrics.kind == "baseline_v6") & (result_metrics.view == "exact_paired")].iloc[0]
    for kind in prediction.kind.unique():
        if kind == "baseline_v6":
            continue
        group = prediction[prediction.kind.eq(kind) & prediction.is_paired_exact]
        score = metrics(group)
        observed = group[group.quota_available.eq(1)]
        enough = len(observed) >= 20 and observed.school.nunique() >= 5 and observed.year.nunique() >= 2 and len(observed) / len(group) >= .10
        byyear = []
        coverage_changes = []
        for year, g in group.groupby("year"):
            b = baseline[(baseline.year == year) & baseline.is_paired_exact]
            byyear.append(metrics(g)["mae"] - metrics(b)["mae"])
            coverage_changes.append(metrics(g)["q90_coverage"] - metrics(b)["q90_coverage"])
        performance = (score["wis"] <= base_primary.wis * .98 and score["mae"] <= base_primary.mae + .5
            and max(byyear) <= 2. and score["q90_coverage"] >= base_primary.q90_coverage - .03 and min(coverage_changes) >= -.03)
        gates.append({"kind": kind, "exact_quota_oos_rows": len(observed), "exact_quota_oos_schools": int(observed.school.nunique()),
            "exact_quota_oos_years": int(observed.year.nunique()), "enough_independent_coverage": bool(enough),
            "performance_gate": bool(performance), "worst_year_mae_change": max(byyear),
            "production_decision": "not_authorized_research_only", "recommendation": "insufficient_cross_school_evidence" if not enough else "further_independent_validation_needed"})
    after = freeze_hashes()
    if before != after:
        raise RuntimeError("Frozen production outputs changed during research run.")
    if not all(row["passed"] for row in reproduction):
        raise RuntimeError("V6 baseline did not replicate. Do not interpret comparisons.")
    input_paths = [DATASET, DISTRIBUTIONS, PAIRED, ROOT / "data/processed/program_year.csv",
        ROOT / "data/processed/schools.csv", ROOT / "data/processed/national_lines.json",
        ROOT / "docs/deadline_quota_backtest_protocol_20261024.md", Path(__file__),
        ROOT / "model/deadline_quota_research.py", ROOT / "model/experiment_statistical_inference.py"]
    coverage = []
    for policy in POLICIES:
        eligible = ledger[ledger.policy.eq(policy) & ledger.evidence_eligible]
        linked = ledger[ledger.policy.eq(policy) & ledger.linked_for_research]
        coverage.append({"policy": policy, "evidence_records": len(eligible),
            "evidence_school_years": len(eligible[["school", "year"]].drop_duplicates()),
            "linked_records": len(linked), "linked_schools": int(linked.school.nunique()),
            "historical_linked_records_2022_2026": int(linked.year.le(2026).sum()),
            "linked_by_school": {str(s): sorted(map(int, g.year)) for s, g in linked.groupby("school")},
            "reason_counts_not_mutually_exclusive": dict(Counter(reason for cell in ledger.loc[ledger.policy.eq(policy), "reason_codes"] for reason in cell.split(";") if reason))})
    summary = {
        "status": "research_only_no_production_promotion", "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "quota_data_release": "data-quota-20261023-r2", "cutoff_rule": "formal registration deadline at 22:00 Asia/Hong_Kong",
        "target": "audited empirical Q10 of full-time ordinary admitted cohort; not individual admission probability",
        "candidate_score_uncertainty": "excluded", "seed": SEED, "origins": list(ORIGINS),
        "historical_vintage_limitation": "Most historical values reconstructed from dated present official pages, not original-year archives; later/unknown attachment versions excluded.",
        "scope_sensitivity_warning": "special_scope_sensitivity is not verified ordinary-net quota and cannot establish effectiveness of the requested ordinary-quota variable.",
        "model": "V6 random-intercept observation-error model plus integrated regularized current-quota coefficients; empirical-Bayes variance plug-in",
        "baseline_reproduction": reproduction, "coverage": coverage,
        "primary_comparison": result_metrics[result_metrics.view.eq("exact_paired")].to_dict("records"),
        "historical_reference_baselines_same_54_rows": paired_baselines, "gates": gates,
        "frozen_output_hashes": before, "frozen_output_check": "10 files unchanged",
        "frozen_output_hashes_lf": {name: text_hash_lf(ROOT / name) for name in sorted(FROZEN_OUTPUTS)},
        "inputs": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(p),
            "sha256_lf": text_hash_lf(p)} for p in input_paths],
        "environment": {"python": platform.python_version(), **{name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scipy", "scikit-learn")}},
        "limitations": ["Only three observed evaluation years; no claim of prospective statistical significance.",
            "Quota publication missingness may be informative; masks do not identify a missingness mechanism.",
            "Integrated coefficient uncertainty does not integrate estimated variance hyperparameters.",
            "Covariate effects are predictive associations, not causal effects or guaranteed capacity elasticities.",
            "No candidate or model is selected using the pooled outer-fold scores; production requires a separate user decision."],
    }
    for name, value in (("summary.json", summary), ("origin_fits.json", fits), ("subgroup_metrics.json", subgroup), ("paired_uncertainty.json", uncertainty)):
        (out / name).write_text(json.dumps(safe(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(safe({"status": summary["status"],
        "comparison": [{k: r[k] for k in ("kind", "n", "mae", "wis", "q90_coverage", "quota_observed_rows")}
            for r in summary["primary_comparison"]], "baseline_reproduction": reproduction}), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
