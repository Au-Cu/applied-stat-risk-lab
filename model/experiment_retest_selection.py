"""Use every readable retest/admission score without leaking future information.

The admitted-score model answers where the lower tail of the admitted cohort
lies.  The larger OCR table also contains explicitly rejected candidates and
rows whose admission status is unknown.  This experiment gives those rows a
separate, auditable role:

* explicit admitted/not-admitted rows estimate the within-school-year score
  selection gradient and the overlap between outcomes;
* unknown-status rows estimate the retest-pool score distribution only;
* any predictive experiment uses strictly lagged cohort summaries and is
  reported as a guarded auxiliary candidate, never as same-year information.

Only aggregate school-year outputs are written.  Candidate hashes and source
rows remain in the private input and are never emitted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from candidate_score_layer import audited_candidate_pool, load_candidate_scores
from experiment_hierarchical_distribution import build_group_data


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data" / "private"
PROCESSED = ROOT / "data" / "processed"
DEFAULT_OUTPUT = ROOT / "output" / "experiments" / "v5_retest_selection_20261009"
TARGET_MAJOR = "025200"
EXPLICIT_RULES = {"green_excluded", "blue_excluded"}
KNOWN_OUTCOMES = {"admitted", "not_admitted"}
FEATURES = (
    "lag_selection_auc",
    "lag_admission_rate",
    "lag_score_gap_mean",
    "lag_score_gap_median",
    "lag_retest_score_iqr",
    "lag_log_cohort_n",
    "lag_selection_age",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scores",
        type=Path,
        default=PRIVATE / "retest_initial_scores.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "可用"}


def load_scores(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, encoding="utf-8")
    raw["major_code"] = (
        raw["major_code"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    raw["year"] = pd.to_numeric(raw["year"], errors="coerce").astype("Int64")
    raw["initial_score"] = pd.to_numeric(raw["initial_score"], errors="coerce")
    raw["ocr_confidence"] = pd.to_numeric(raw["ocr_confidence"], errors="coerce")
    raw["special_row"] = raw["special_row"].map(_bool)
    valid = raw[
        raw["major_code"].eq(TARGET_MAJOR)
        & raw["study_mode"].eq("全日制")
        & raw["year"].notna()
        & raw["initial_score"].between(180, 500)
    ].copy()
    valid = valid.sort_values("ocr_confidence", ascending=False, na_position="last")
    duplicate_rows = int(valid.duplicated("candidate_id_hash", keep="first").sum())
    valid = valid.drop_duplicates("candidate_id_hash", keep="first").copy()
    audit = {
        "raw_rows": int(len(raw)),
        "valid_target_rows_before_deduplication": int(
            (
                raw["major_code"].eq(TARGET_MAJOR)
                & raw["study_mode"].eq("全日制")
                & raw["year"].notna()
                & raw["initial_score"].between(180, 500)
            ).sum()
        ),
        "duplicate_rows_not_double_counted": duplicate_rows,
        "unique_valid_score_rows": int(len(valid)),
        "raw_admitted_rows": int(raw["admission_status"].eq("admitted").sum()),
        "raw_not_admitted_rows": int(raw["admission_status"].eq("not_admitted").sum()),
        "raw_unknown_outcome_rows": int(raw["admission_status"].eq("unknown").sum()),
    }
    return valid, audit


def auc_from_scores(frame: pd.DataFrame) -> float:
    labels = frame["admission_status"].eq("admitted").astype(int)
    positive = int(labels.sum())
    negative = int(len(labels) - positive)
    if positive == 0 or negative == 0:
        return float("nan")
    ranks = frame["initial_score"].rank(method="average").to_numpy(float)
    rank_sum = float(ranks[labels.to_numpy(bool)].sum())
    return (rank_sum - positive * (positive + 1) / 2.0) / (positive * negative)


def cohort_summary(scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = scores[
        scores["highlight_rule"].isin(EXPLICIT_RULES)
        & scores["admission_status"].isin(KNOWN_OUTCOMES)
        & ~scores["special_row"]
        & scores["ocr_confidence"].ge(0.75)
    ].copy()
    records: list[dict] = []
    deciles: list[dict] = []
    for (school, year), group in eligible.groupby(["school", "year"], sort=True):
        admitted = group[group["admission_status"].eq("admitted")]
        rejected = group[group["admission_status"].eq("not_admitted")]
        if admitted.empty or rejected.empty:
            continue
        percentile = group["initial_score"].rank(method="average", pct=True)
        group = group.assign(
            score_decile=np.ceil(percentile.mul(10)).clip(1, 10).astype(int),
            admitted_flag=group["admission_status"].eq("admitted").astype(int),
        )
        for decile, block in group.groupby("score_decile"):
            deciles.append(
                {
                    "school": school,
                    "year": int(year),
                    "score_decile": int(decile),
                    "candidate_n": int(len(block)),
                    "admission_rate": float(block["admitted_flag"].mean()),
                }
            )
        records.append(
            {
                "school": school,
                "year": int(year),
                "cohort_n": int(len(group)),
                "admitted_n": int(len(admitted)),
                "not_admitted_n": int(len(rejected)),
                "admission_rate": float(len(admitted) / len(group)),
                "selection_auc": float(auc_from_scores(group)),
                "retest_score_q10": float(group["initial_score"].quantile(0.10)),
                "retest_score_q25": float(group["initial_score"].quantile(0.25)),
                "retest_score_q50": float(group["initial_score"].quantile(0.50)),
                "retest_score_q75": float(group["initial_score"].quantile(0.75)),
                "retest_score_q90": float(group["initial_score"].quantile(0.90)),
                "retest_score_iqr": float(
                    group["initial_score"].quantile(0.75)
                    - group["initial_score"].quantile(0.25)
                ),
                "admitted_score_mean": float(admitted["initial_score"].mean()),
                "not_admitted_score_mean": float(rejected["initial_score"].mean()),
                "score_gap_mean": float(
                    admitted["initial_score"].mean() - rejected["initial_score"].mean()
                ),
                "admitted_score_median": float(admitted["initial_score"].median()),
                "not_admitted_score_median": float(rejected["initial_score"].median()),
                "score_gap_median": float(
                    admitted["initial_score"].median() - rejected["initial_score"].median()
                ),
                "admitted_below_admitted_q10_share": float(
                    (admitted["initial_score"] <= admitted["initial_score"].quantile(0.10)).mean()
                ),
            }
        )
    cohorts = pd.DataFrame(records)
    decile_frame = pd.DataFrame(deciles)
    qualified = cohorts[
        cohorts["admitted_n"].ge(3) & cohorts["not_admitted_n"].ge(3)
    ].copy()
    return cohorts, qualified, decile_frame


def score_only_summary(scores: pd.DataFrame) -> pd.DataFrame:
    unknown = scores[
        scores["admission_status"].eq("unknown")
        & scores["roster_stage"].eq("retest_roster")
        & ~scores["special_row"]
    ].copy()
    records = []
    for (school, year), group in unknown.groupby(["school", "year"], sort=True):
        records.append(
            {
                "school": school,
                "year": int(year),
                "score_only_n": int(len(group)),
                "score_only_q10": float(group["initial_score"].quantile(0.10)),
                "score_only_q50": float(group["initial_score"].quantile(0.50)),
                "score_only_q90": float(group["initial_score"].quantile(0.90)),
                "role": "retest_pool_distribution_only_outcome_unknown",
            }
        )
    return pd.DataFrame(records)


def add_lagged_selection(groups: pd.DataFrame, cohorts: pd.DataFrame) -> pd.DataFrame:
    result = groups.copy()
    history = {
        school: frame.sort_values("year") for school, frame in cohorts.groupby("school")
    }
    for index, row in result.iterrows():
        prior = history.get(row["school"])
        if prior is None:
            continue
        prior = prior[prior["year"] < int(row["year"])]
        if prior.empty:
            continue
        latest = prior.iloc[-1]
        result.at[index, "lag_selection_auc"] = latest["selection_auc"]
        result.at[index, "lag_admission_rate"] = latest["admission_rate"]
        result.at[index, "lag_score_gap_mean"] = latest["score_gap_mean"]
        result.at[index, "lag_score_gap_median"] = latest["score_gap_median"]
        result.at[index, "lag_retest_score_iqr"] = latest["retest_score_iqr"]
        result.at[index, "lag_log_cohort_n"] = np.log1p(latest["cohort_n"])
        result.at[index, "lag_selection_age"] = int(row["year"]) - int(latest["year"])
    return result


def lagged_predictive_diagnostic(
    candidate_scores: pd.DataFrame,
    cohorts: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    groups, _, _, _, _ = build_group_data(candidate_scores)
    groups = add_lagged_selection(groups, cohorts)
    groups = groups[groups["anchor_q10"].notna()].copy()
    rows: list[dict] = []
    for origin in sorted(int(value) for value in groups["year"].unique() if int(value) >= 2024):
        train = groups[(groups["year"] < origin) & groups[list(FEATURES)].notna().any(axis=1)]
        test = groups[(groups["year"] == origin) & groups[list(FEATURES)].notna().any(axis=1)]
        if len(train) < 12 or test.empty:
            continue
        model = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("ridge", Ridge(alpha=12.0)),
            ]
        )
        model.fit(train[list(FEATURES)], train["score_q10"] - train["anchor_q10"])
        correction = model.predict(test[list(FEATURES)])
        for row_index, (_, row) in enumerate(test.iterrows()):
            rows.append(
                {
                    "school": row["school"],
                    "year": origin,
                    "actual_q10": float(row["score_q10"]),
                    "anchor_q10": float(row["anchor_q10"]),
                    "selection_ridge_q10": float(row["anchor_q10"] + correction[row_index]),
                    "lag_selection_age": float(row.get("lag_selection_age", np.nan)),
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"status": "insufficient_strictly_lagged_overlap"}
    anchor_error = np.abs(frame["actual_q10"] - frame["anchor_q10"])
    candidate_error = np.abs(frame["actual_q10"] - frame["selection_ridge_q10"])
    yearly = {
        str(int(year)): {
            "n": int(len(block)),
            "anchor_mae": float(np.mean(np.abs(block["actual_q10"] - block["anchor_q10"]))),
            "selection_ridge_mae": float(
                np.mean(np.abs(block["actual_q10"] - block["selection_ridge_q10"]))
            ),
        }
        for year, block in frame.groupby("year")
    }
    delta = float(candidate_error.mean() - anchor_error.mean())
    return frame, {
        "status": "diagnostic_not_promoted",
        "school_years": int(len(frame)),
        "origins": sorted(int(value) for value in frame["year"].unique()),
        "anchor_mae": float(anchor_error.mean()),
        "selection_ridge_mae": float(candidate_error.mean()),
        "candidate_minus_anchor_mae": delta,
        "year_metrics": yearly,
        "promotion_rule": "No promotion without a material, stable improvement under nested time-ordered validation.",
        "same_year_leakage": False,
    }


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scores, input_audit = load_scores(args.scores.resolve())
    cohorts, qualified, deciles = cohort_summary(scores)
    score_only = score_only_summary(scores)

    candidate_scores = load_candidate_scores()
    audited = audited_candidate_pool(candidate_scores)
    exact = int(audited["candidate_evidence_tier"].eq("exact").sum())
    soft = int(audited["candidate_evidence_tier"].eq("soft_roster").sum())
    admitted_diagnostic = int(len(candidate_scores) - exact - soft)
    predictions, predictive = lagged_predictive_diagnostic(candidate_scores, qualified)

    cohorts.to_csv(
        PROCESSED / "retest_selection_summary.csv", index=False, encoding="utf-8-sig"
    )
    score_only.to_csv(
        PROCESSED / "retest_score_only_summary.csv", index=False, encoding="utf-8-sig"
    )
    qualified.to_csv(
        output / "qualified_selection_cohorts.csv", index=False, encoding="utf-8-sig"
    )
    deciles.to_csv(output / "selection_deciles.csv", index=False, encoding="utf-8-sig")
    predictions.to_csv(
        output / "lagged_selection_predictions.csv", index=False, encoding="utf-8-sig"
    )

    decile_balanced = (
        deciles.merge(
            qualified[["school", "year"]], on=["school", "year"], how="inner"
        )
        .groupby("score_decile")["admission_rate"]
        .agg(["mean", "median", "count", lambda x: x.quantile(0.10), lambda x: x.quantile(0.90)])
        .reset_index()
    )
    decile_balanced.columns = [
        "score_decile",
        "mean_admission_rate",
        "median_admission_rate",
        "school_years",
        "p10_admission_rate",
        "p90_admission_rate",
    ]
    decile_balanced.to_csv(
        output / "selection_decile_balanced_curve.csv", index=False, encoding="utf-8-sig"
    )

    summary = {
        "status": "post_freeze_v5_retest_selection_experiment",
        "input_audit": input_audit,
        "row_roles": {
            "admitted_distribution_rows_raw": int(len(candidate_scores)),
            "admitted_exact_rows": exact,
            "admitted_soft_rows": soft,
            "admitted_diagnostic_rows": admitted_diagnostic,
            "explicit_outcome_rows_after_deduplication": int(
                scores[
                    scores["highlight_rule"].isin(EXPLICIT_RULES)
                    & scores["admission_status"].isin(KNOWN_OUTCOMES)
                    & ~scores["special_row"]
                    & scores["ocr_confidence"].ge(0.75)
                ].shape[0]
            ),
            "unknown_outcome_score_rows_after_deduplication": int(
                scores["admission_status"].eq("unknown").sum()
            ),
            "note": "Roles overlap by design: an admitted row informs both its admitted distribution and, where the legend is explicit, the retest selection gradient.",
        },
        "selection_cohorts": {
            "school_years_with_both_outcomes": int(len(cohorts)),
            "qualified_school_years_minimum_three_each": int(len(qualified)),
            "candidate_rows_in_qualified_cohorts": int(qualified["cohort_n"].sum()),
            "schools": int(qualified["school"].nunique()),
            "years": sorted(int(value) for value in qualified["year"].unique()),
            "median_selection_auc": float(qualified["selection_auc"].median()),
            "median_admission_rate": float(qualified["admission_rate"].median()),
            "median_admitted_minus_rejected_score": float(qualified["score_gap_median"].median()),
            "share_auc_below_0_5": float(qualified["selection_auc"].lt(0.5).mean()),
            "interpretation": "Scores are associated with selection but the outcome distributions overlap; Q10 is a risk indicator, not a deterministic institutional cutoff.",
        },
        "unknown_outcome_score_only": {
            "rows": int(score_only["score_only_n"].sum()) if not score_only.empty else 0,
            "school_years": int(len(score_only)),
            "role": "Used for retest-pool distribution sensitivity only; never converted into an admission label.",
        },
        "lagged_predictive_diagnostic": predictive,
        "privacy": "Only school-year aggregates are public; no candidate hash or row-level source text is emitted.",
        "production_guardrail": "Frozen V4 forecasts remain unchanged.",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "data" / "audit" / "score_row_utilisation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
