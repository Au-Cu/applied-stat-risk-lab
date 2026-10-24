"""Re-evaluate a fixed V6 model after an independently audited data refresh.

No hyperparameter search or production promotion. Scores remain aggregate;
each origin can see only strictly earlier outcome years.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from candidate_score_layer import recompute_exact_aware_features

from experiment_statistical_inference import (
    PROBS, calibrate_observations, evaluate, fit_state, national_prediction, fit_nested_reml,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/evidence_refresh_20261024"
OUT = ROOT / "output/experiments/evidence_refresh_20261024"


def run_fixed_model(periods, distributions, national, evaluation_keys):
    rows, fits = [], []
    tests = distributions.merge(periods[["school", "year", "national_zone"]], on=["school", "year"])
    tests = tests.merge(evaluation_keys, on=["school", "year"])
    for origin in (2024, 2025, 2026):
        observations, calibration = calibrate_observations(periods, distributions, origin)
        if not (observations.year < origin).all():
            raise ValueError("Outcome-time leakage")
        state = fit_state(observations, "random_intercept")
        fits.append({"origin": origin, "latest_training_year": int(observations.year.max()),
            "exact_training_groups": calibration["exact_training_groups"], "converged": state.converged,
            "school_variance": state.school_variance, "innovation_variance": state.innovation_variance})
        prior = distributions[distributions.year < origin]
        for _, record in tests[tests.year.eq(origin)].iterrows():
            center, state_variance = state.predict(record.school, origin)
            line, line_variance = national_prediction(national, origin, record.national_zone)
            history = prior[prior.school.eq(record.school)].sort_values("year")
            cohort_variance = float(history.iloc[-1].q10_bootstrap_sd ** 2) if len(history) else calibration["default_sampling_variance"]
            sd = float(np.sqrt(state_variance + line_variance + cohort_variance))
            row = {"school": record.school, "year": origin, "actual": float(record.score_q10),
                "kind": "fixed_random_intercept", "latest_training_year": int(observations.year.max()),
                "pred_sd": sd, "state_variance": state_variance, "national_variance": line_variance,
                "future_cohort_variance": cohort_variance}
            for probability in PROBS:
                row[f"pred_q{int(probability*100):02d}"] = line + center + norm.ppf(probability) * sd
            rows.append(row)
    return pd.DataFrame(rows), fits


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    periods = pd.read_csv(ROOT / "data/processed/program_year.csv")
    # The officially corrected cutoff belongs to a separate data vintage.
    updated_periods = periods.copy()
    official_cutoffs = {2025: (385.0, "https://math.tongji.edu.cn/__local/3/1A/33/AF6A002A4BB347DE45D3402442F_84DEA1DF_14A81.pdf"),
                        2026: (396.0, "https://math.tongji.edu.cn/__local/1/E0/BA/E8D86468F3671102B822631B627_6ACD045A_19C00.pdf")}
    for year, (cutoff, source) in official_cutoffs.items():
        mask = updated_periods.school.eq("同济大学") & updated_periods.year.eq(year)
        updated_periods.loc[mask, "cutoff"] = cutoff
        updated_periods.loc[mask, "cutoff_text"] = str(int(cutoff))
        updated_periods.loc[mask, "margin_cutoff"] = cutoff - updated_periods.loc[mask, "national_line"]
        updated_periods.loc[mask, "cutoff_detail"] = "数学科学学院应用统计01、02全日制方向；03、04非全日制及专项不混入"
        updated_periods.loc[mask, "cutoff_source"] = source
    updated_periods.to_csv(DATA / "program_year_proxy_with_cutoff_corrections.csv", index=False, encoding="utf-8-sig")
    old = pd.read_csv(ROOT / "output/experiments/v5_hierarchical_distribution_20261009/candidate_distribution_summary.csv")
    new = pd.read_csv(DATA / "exact_distribution_summary.csv")
    effective = updated_periods.copy()
    effective["proxy_q10_value"] = effective.q10_value
    effective["proxy_q10_method"] = effective.q10_method
    effective["original_reported_admitted_count"] = effective.admitted_count
    for row in new.itertuples():
        mask=effective.school.eq(row.school) & effective.year.eq(row.year)
        for column,value in {"q10_value": row.score_q10, "q10_method": "exact_candidate_scores",
            "q10_weight": 1.0, "target_value": row.score_q10, "target_kind": "q10_exact", "target_weight": 1.0,
            "admitted_count": row.candidate_n, "admitted_min": row.score_min, "admitted_median": row.score_q50,
            "admitted_max": row.score_max, "q10_sampling_sd": row.q10_bootstrap_sd}.items():
            effective.loc[mask,column]=value
        effective.loc[mask,"margin_q10"]=row.score_q10-effective.loc[mask,"national_line"]
    school_tier=pd.read_csv(ROOT/"data/processed/schools.csv")[["school","is_985"]]
    effective=effective.merge(school_tier,on="school",how="left",validate="many_to_one")
    effective=recompute_exact_aware_features(effective)
    effective.to_csv(DATA/"program_year.csv",index=False,encoding="utf-8-sig")
    national = json.loads((ROOT / "data/processed/national_lines.json").read_text(encoding="utf-8"))
    common = pd.read_csv(ROOT / "output/experiments/v5_exact_labels_20261009/exact_evaluation/paired_exact_backtest.csv")[["school", "year"]]
    # One test set isolates changes in training evidence; another includes
    # newly audited outcomes. Their MAEs are never compared as equal samples.
    old_prediction, old_fits = run_fixed_model(periods, old, national, common)
    new_prediction, new_fits = run_fixed_model(updated_periods, new, national, common)
    expanded, expanded_fits = run_fixed_model(updated_periods, new, national, new[new.year.isin([2024, 2025, 2026])][["school", "year"]])
    old_prediction.to_csv(OUT / "previous_evidence_common_predictions.csv", index=False, encoding="utf-8-sig")
    new_prediction.to_csv(OUT / "refreshed_evidence_common_predictions.csv", index=False, encoding="utf-8-sig")
    expanded.to_csv(OUT / "refreshed_evidence_expanded_predictions.csv", index=False, encoding="utf-8-sig")
    same = old_prediction[["school", "year", "actual"]].merge(new_prediction[["school", "year", "actual"]], on=["school", "year"], suffixes=("_old", "_new"))
    changed_labels = same[(same.actual_old - same.actual_new).abs() > 1e-9]
    nested, _ = fit_nested_reml(new, year_fixed=True, profile=False)
    summary = {"experiment": "fixed V6 model with refreshed evidence", "created_on": "2026-10-24",
        "python_version": platform.python_version(),
        "input_roles": {"effective_training_panel": "data/processed/evidence_refresh_20261024/program_year.csv",
            "proxy_calibration_panel": "data/processed/evidence_refresh_20261024/program_year_proxy_with_cutoff_corrections.csv",
            "exact_label_priority": "85 audited empirical labels replace proxies; original proxy columns remain solely for observation-error calibration"},
        "model": "random_intercept", "hyperparameters_retuned": False,
        "same_key_test": {"previous": evaluate(old_prediction), "refreshed": evaluate(new_prediction),
            "outcome_label_changes": changed_labels.to_dict("records")},
        "expanded_audited_test": evaluate(expanded),
        "yearly": [{"vintage": name, "year": int(year), **evaluate(group)}
            for name, frame in [("previous_common", old_prediction), ("refreshed_common", new_prediction), ("refreshed_expanded", expanded)]
            for year, group in frame.groupby("year")],
        "origin_fits": {"previous": old_fits, "refreshed": new_fits, "expanded": expanded_fits},
        "production_promoted": False,
        "current_audited_distribution": {"school_years": len(new), "schools": int(new.school.nunique()),
            "candidates": int(new.candidate_n.sum()),
            "median_within_school_year_sd": float(new.score_sd.median()),
            "q10_range": [float(new.score_q10.min()), float(new.score_q10.max())],
            "nested_reml_calendar_adjusted": nested},
        "limitations": ["retrospective source reconstruction, not a blind forecast",
            "only three independent outer calendar years", "school-year rosters are not a nationwide random sample",
            "newly audited outcomes change the expanded evaluation population",
            "2027 syllabus event has verified existence but no empirically estimated shock probability",
            "no personal-score uncertainty was included"]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key in {"same_key_test", "expanded_audited_test", "production_promoted"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
