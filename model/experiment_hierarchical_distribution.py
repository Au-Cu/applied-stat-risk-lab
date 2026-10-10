"""Hierarchical use of audited admitted-score samples.

The model separates two questions that a single P10 proxy cannot answer:

* threshold state: the school-year admitted-score P10 used by the decision
  layer;
* conditional shape: the remaining admitted-score distribution relative to
  that P10.

Candidate rows estimate conditional shape.  They do not count as independent
school-year forecast origins: every loss and every fit uses equal total mass
per school-year.  Model selection is prequential in calendar time.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from candidate_score_layer import (
    apply_exact_candidate_labels,
    audited_candidate_pool,
    audited_distribution_by_program,
    candidate_distribution_by_program,
    load_candidate_scores,
    recompute_exact_aware_features,
)
from experiment_candidate_distribution import (
    exact_candidate_rows,
    forecast_group_frame,
    national_distribution_decomposition,
    weighted_quantile,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
PRIVATE = ROOT / "data" / "private"
DEFAULT_OUTPUT = ROOT / "output" / "experiments" / "v5_hierarchical_distribution_20261009"
PROBABILITIES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
SHAPE_PROBABILITIES = PROBABILITIES
CORRECTION_KINDS = ("zero", "global_median", "school_eb", "ridge")
CORRECTION_NUMERIC = (
    "anchor_q10",
    "is_985",
    "lag1_margin_q10",
    "trailing_margin_median",
    "lag1_surprise_z",
    "lag1_margin_change",
    "lag1_cutoff_change",
    "log_lag1_admitted_count",
    "peer_lag1_surprise_mean",
    "lag_exact_age",
    "lag_exact_score_q10",
    "lag_exact_score_q50",
    "lag_exact_score_sd",
    "lag_exact_score_iqr",
)
CORRECTION_CATEGORICAL = (
    "national_zone",
    "english_subject",
    "math_subject",
    "faction",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--candidate-scores",
        type=Path,
        default=PRIVATE / "candidate_initial_scores.csv",
    )
    return parser.parse_args()


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "可用"}


def qname(probability: float, prefix: str = "pred") -> str:
    return f"{prefix}_q{int(round(probability * 100)):02d}"


def national_line_mean(values: dict[int, dict], year: int, zone: str) -> float:
    available = sorted(value for value in values if value < year)
    prior = np.array([values[value]["A"] for value in available], dtype=float)
    if not len(prior):
        result = 335.0
    elif len(prior) < 3:
        result = float(prior[-1])
    else:
        result = float(0.55 * prior[-1] + 0.45 * np.mean(prior[-5:]))
    return result - (10.0 if zone == "B" else 0.0)


def add_lag_distribution(frame: pd.DataFrame, distributions: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    columns = (
        "candidate_n",
        "score_q10",
        "score_q50",
        "score_sd",
        "score_iqr",
        "lower_tail_span_q50_q10",
        "upper_tail_span_q90_q50",
        "bowley_skewness",
    )
    histories = {
        school: group.sort_values("year")
        for school, group in distributions.groupby("school")
    }
    for index, row in result.iterrows():
        history = histories.get(row["school"])
        if history is None:
            continue
        prior = history[history["year"] < int(row["year"])]
        if prior.empty:
            continue
        latest = prior.iloc[-1]
        result.at[index, "lag_exact_age"] = int(row["year"]) - int(latest["year"])
        for column in columns:
            result.at[index, f"lag_exact_{column}"] = latest[column]
    return result


def build_group_data(candidate_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    distributions = candidate_distribution_by_program(candidate_frame)
    candidates = exact_candidate_rows(candidate_frame)
    periods = pd.read_csv(DATA / "program_year.csv", encoding="utf-8-sig")
    schools = pd.read_csv(DATA / "schools.csv", encoding="utf-8-sig")
    periods = periods.merge(schools, on="school", how="left", suffixes=("", "_school"))
    periods, _ = apply_exact_candidate_labels(periods, candidate_frame)
    periods = recompute_exact_aware_features(periods)
    periods["is_985"] = periods["is_985"].map(_bool).astype(int)
    periods["log_lag1_admitted_count"] = np.log1p(
        pd.to_numeric(periods["lag1_admitted_count"], errors="coerce")
    )
    groups = distributions.merge(periods, on=["school", "year"], how="left", suffixes=("_exact", ""))

    backtest = pd.read_csv(DATA / "rolling_backtest.csv", encoding="utf-8-sig")
    backtest = backtest[["school", "year", "pred_q50", "baseline", "robust_baseline"]]
    groups = groups.merge(backtest, on=["school", "year"], how="left")
    national_payload = json.loads((DATA / "national_lines.json").read_text(encoding="utf-8"))
    national_lines = {int(year): value for year, value in national_payload["values"].items()}
    for index, row in groups.iterrows():
        candidates_anchor = [row.get("robust_baseline"), row.get("pred_q50"), row.get("baseline")]
        anchor = next((float(value) for value in candidates_anchor if pd.notna(value)), np.nan)
        if pd.isna(anchor):
            history = periods[
                periods["school"].eq(row["school"]) & (periods["year"] < int(row["year"]))
            ]
            margins = pd.to_numeric(history["margin_q10"], errors="coerce").dropna()
            if len(margins):
                anchor = national_line_mean(
                    national_lines, int(row["year"]), str(row["national_zone"])
                ) + float(np.median(margins))
        groups.at[index, "anchor_q10"] = anchor
    groups["anchor_error"] = groups["score_q10"] - groups["anchor_q10"]
    groups = add_lag_distribution(groups, distributions)
    candidates = candidates.merge(
        groups[["school", "year", "score_q10"]], on=["school", "year"], how="inner"
    )
    candidates["shape_score"] = candidates["initial_score"] - candidates["score_q10"]
    return groups, candidates, distributions, periods, national_payload


def build_audited_group_data(
    audited_distributions: pd.DataFrame,
    periods: pd.DataFrame,
    exact_distributions: pd.DataFrame,
) -> pd.DataFrame:
    """Attach leakage-safe model features and anchors to all evidence tiers."""

    groups = audited_distributions.merge(
        periods,
        on=["school", "year"],
        how="left",
        suffixes=("_distribution", ""),
    )
    groups["is_985"] = groups["is_985"].map(_bool).astype(int)
    groups["log_lag1_admitted_count"] = np.log1p(
        pd.to_numeric(groups["lag1_admitted_count"], errors="coerce")
    )
    backtest = pd.read_csv(DATA / "rolling_backtest.csv", encoding="utf-8-sig")
    groups = groups.merge(
        backtest[["school", "year", "pred_q50", "baseline", "robust_baseline"]],
        on=["school", "year"],
        how="left",
    )
    national_payload = json.loads((DATA / "national_lines.json").read_text(encoding="utf-8"))
    national_lines = {int(year): value for year, value in national_payload["values"].items()}
    for index, row in groups.iterrows():
        anchor = next(
            (
                float(value)
                for value in (row.get("robust_baseline"), row.get("pred_q50"), row.get("baseline"))
                if pd.notna(value)
            ),
            np.nan,
        )
        if pd.isna(anchor):
            history = periods[
                periods["school"].eq(row["school"])
                & (periods["year"] < int(row["year"]))
            ]
            margins = pd.to_numeric(history["margin_q10"], errors="coerce").dropna()
            if len(margins):
                anchor = national_line_mean(
                    national_lines, int(row["year"]), str(row["national_zone"])
                ) + float(np.median(margins))
        groups.at[index, "anchor_q10"] = anchor
    groups["anchor_error"] = groups["score_q10"] - groups["anchor_q10"]
    return add_lag_distribution(groups, exact_distributions)


def correction_preprocessor(frame: pd.DataFrame) -> tuple[ColumnTransformer, list[str], list[str]]:
    numeric = [column for column in CORRECTION_NUMERIC if column in frame and frame[column].notna().any()]
    categorical = [column for column in CORRECTION_CATEGORICAL if column in frame and frame[column].notna().any()]
    processor = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        sparse_threshold=0.0,
    )
    return processor, numeric, categorical


@dataclass
class CorrectionModel:
    kind: str
    global_value: float = 0.0
    school_values: dict | None = None
    pipeline: Pipeline | None = None

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.kind == "zero":
            return np.zeros(len(frame), dtype=float)
        if self.kind == "global_median":
            return np.full(len(frame), self.global_value, dtype=float)
        if self.kind == "school_eb":
            return np.array(
                [self.school_values.get(school, self.global_value) for school in frame["school"]],
                dtype=float,
            )
        return self.pipeline.predict(frame)


def fit_correction(kind: str, train: pd.DataFrame) -> CorrectionModel:
    clean = train[train["anchor_error"].notna()].copy()
    if kind == "zero" or clean.empty:
        return CorrectionModel("zero")
    global_value = float(clean["anchor_error"].median())
    if kind == "global_median":
        return CorrectionModel(kind, global_value=global_value)
    if kind == "school_eb":
        values = {}
        for school, group in clean.groupby("school"):
            n = len(group)
            school_mean = float(group["anchor_error"].mean())
            weight = n / (n + 3.0)
            values[school] = global_value + weight * (school_mean - global_value)
        return CorrectionModel(kind, global_value=global_value, school_values=values)
    processor, _, _ = correction_preprocessor(clean)
    pipeline = Pipeline([("preprocess", processor), ("model", Ridge(alpha=20.0))])
    sampling_sd = pd.to_numeric(clean["q10_bootstrap_sd"], errors="coerce").fillna(6.0)
    if "programme_evidence_weight" in clean:
        evidence_weight = pd.to_numeric(
            clean["programme_evidence_weight"], errors="coerce"
        ).fillna(1.0).to_numpy(float)
    else:
        evidence_weight = np.ones(len(clean), dtype=float)
    weights = evidence_weight / np.maximum(sampling_sd.to_numpy(float) ** 2, 4.0)
    weights /= np.mean(weights)
    pipeline.fit(clean, clean["anchor_error"], model__sample_weight=weights)
    return CorrectionModel(kind, global_value=global_value, pipeline=pipeline)


def correction_backtest(
    train: pd.DataFrame,
    audited_train: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = []
    years = sorted(int(year) for year in train["year"].unique())
    for origin in years[1:]:
        earlier = train[(train["year"] < origin) & train["anchor_error"].notna()]
        earlier_audited = (
            audited_train[
                (audited_train["year"] < origin)
                & audited_train["anchor_error"].notna()
            ]
            if audited_train is not None
            else pd.DataFrame()
        )
        test = train[(train["year"] == origin) & train["anchor_q10"].notna()]
        if earlier.empty or test.empty:
            continue
        variants = [("exact", kind, earlier) for kind in CORRECTION_KINDS]
        if not earlier_audited.empty:
            variants.extend(
                ("audited", kind, earlier_audited)
                for kind in CORRECTION_KINDS
                if kind != "zero"
            )
        for data_source, kind, fit_frame in variants:
            correction = fit_correction(kind, fit_frame).predict(test)
            for blend in np.linspace(0.0, 1.0, 5):
                prediction = test["anchor_q10"].to_numpy(float) + blend * correction
                for (_, item), value in zip(test.iterrows(), prediction):
                    rows.append(
                        {
                            "origin": origin,
                            "school": item["school"],
                            "kind": kind,
                            "data_source": data_source,
                            "blend": float(blend),
                            "actual": float(item["score_q10"]),
                            "prediction": float(value),
                        }
                    )
    return pd.DataFrame(rows)


def select_correction(
    train: pd.DataFrame,
    audited_train: pd.DataFrame | None = None,
) -> dict:
    backtest = correction_backtest(train, audited_train)
    origins = sorted(backtest["origin"].unique()) if len(backtest) else []
    if len(origins) < 2:
        return {
            "kind": "zero",
            "data_source": "exact",
            "blend": 0.0,
            "reason": "fewer than two strictly prior inner forecast origins",
            "inner_origins": [int(value) for value in origins],
            "candidates": [],
        }
    reports = []
    for (data_source, kind, blend), frame in backtest.groupby(
        ["data_source", "kind", "blend"]
    ):
        frame = frame.copy()
        frame["absolute_error"] = (frame["actual"] - frame["prediction"]).abs()
        yearly = frame.groupby("origin")["absolute_error"].mean()
        reports.append(
            {
                "kind": kind,
                "data_source": data_source,
                "blend": float(blend),
                "mae": float(frame["absolute_error"].mean()),
                "yearly_mae": {str(int(year)): float(value) for year, value in yearly.items()},
            }
        )
    baseline = next(
        report
        for report in reports
        if report["data_source"] == "exact"
        and report["kind"] == "zero"
        and report["blend"] == 0.0
    )
    raw_best = min(reports, key=lambda item: item["mae"])
    complexity = {"zero": 0, "global_median": 1, "school_eb": 2, "ridge": 3}
    near_best = [report for report in reports if report["mae"] <= raw_best["mae"] + 0.10]
    best = min(
        near_best,
        key=lambda item: (
            complexity[item["kind"]] + (1 if item["data_source"] == "audited" else 0),
            item["blend"],
            item["mae"],
        ),
    )
    degradation = max(
        best["yearly_mae"][year] - baseline["yearly_mae"][year]
        for year in baseline["yearly_mae"]
    )
    improvement = baseline["mae"] - best["mae"]
    if improvement < 0.5 or degradation > 2.0:
        selected = {"kind": "zero", "data_source": "exact", "blend": 0.0}
        reason = (
            f"candidate improvement {improvement:.3f} or worst-year degradation "
            f"{degradation:.3f} failed guardrail"
        )
    else:
        selected = {
            "kind": best["kind"],
            "data_source": best["data_source"],
            "blend": best["blend"],
        }
        reason = "passed prequential improvement and worst-year guardrails"
    return {
        **selected,
        "reason": reason,
        "inner_origins": [int(value) for value in origins],
        "baseline_mae": baseline["mae"],
        "best_candidate": best,
        "raw_lowest_mae_candidate": raw_best,
        "parsimony_equivalence_band": 0.10,
        "candidates": reports,
    }


def pooled_shape(train_candidates: pd.DataFrame) -> dict[float, float]:
    counts = train_candidates.groupby(["school", "year"])["shape_score"].transform("size")
    if "programme_evidence_weight" in train_candidates:
        quality = pd.to_numeric(
            train_candidates["programme_evidence_weight"], errors="coerce"
        ).fillna(1.0).to_numpy(float)
    else:
        quality = np.ones(len(train_candidates), dtype=float)
    weights = quality / counts.to_numpy(float)
    offsets = {
        probability: weighted_quantile(
            train_candidates["shape_score"].to_numpy(float), probability, weights
        )
        for probability in SHAPE_PROBABILITIES
    }
    offsets[0.10] = 0.0
    values = np.maximum.accumulate([offsets[p] for p in SHAPE_PROBABILITIES])
    return {probability: float(value) for probability, value in zip(SHAPE_PROBABILITIES, values)}


def shape_offsets(
    test: pd.DataFrame,
    train_distributions: pd.DataFrame,
    train_candidates: pd.DataFrame,
    kind: str,
) -> np.ndarray:
    pooled = pooled_shape(train_candidates)
    rows = []
    for _, item in test.iterrows():
        offsets = dict(pooled)
        if kind == "lag_school_shrinkage":
            prior = train_distributions[
                train_distributions["school"].eq(item["school"])
                & (train_distributions["year"] < int(item["year"]))
            ].sort_values("year")
            if len(prior):
                latest = prior.iloc[-1]
                age = max(int(item["year"]) - int(latest["year"]), 1)
                reliability = min(float(latest["candidate_n"]) / (float(latest["candidate_n"]) + 30.0), 0.75)
                reliability *= math.exp(-0.35 * (age - 1))
                for probability in SHAPE_PROBABILITIES:
                    school_offset = float(latest[f"score_q{int(probability * 100):02d}"] - latest["score_q10"])
                    offsets[probability] = (1.0 - reliability) * pooled[probability] + reliability * school_offset
                offsets[0.10] = 0.0
        rows.append(np.maximum.accumulate([offsets[p] for p in SHAPE_PROBABILITIES]))
    return np.asarray(rows, dtype=float)


def shape_backtest(
    groups: pd.DataFrame,
    exact_candidates: pd.DataFrame,
    audited_candidates: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    years = sorted(int(value) for value in groups["year"].unique())
    for origin in years[1:]:
        train_groups = groups[groups["year"] < origin]
        train_exact = exact_candidates[exact_candidates["year"] < origin]
        train_audited = audited_candidates[audited_candidates["year"] < origin]
        test = groups[groups["year"] == origin]
        if train_groups.empty or train_exact.empty or test.empty:
            continue
        variants = [
            ("pooled_exact", train_exact, "pooled"),
            ("lag_exact", train_exact, "lag_school_shrinkage"),
        ]
        if not train_audited.empty:
            variants.extend(
                [
                    ("pooled_audited", train_audited, "pooled"),
                    (
                        "lag_exact_plus_audited_pool",
                        train_audited,
                        "lag_school_shrinkage",
                    ),
                ]
            )
        for variant, train_candidates, kind in variants:
            offsets = shape_offsets(test, train_groups, train_candidates, kind)
            for row_index, (_, item) in enumerate(test.iterrows()):
                losses = []
                for probability_index, probability in enumerate(SHAPE_PROBABILITIES):
                    actual_offset = float(item[f"score_q{int(probability * 100):02d}"] - item["score_q10"])
                    losses.append(abs(actual_offset - offsets[row_index, probability_index]))
                rows.append(
                    {
                        "origin": origin,
                        "school": item["school"],
                            "kind": variant,
                        "quantile_mae": float(np.mean(losses)),
                    }
                )
    return pd.DataFrame(rows)


def select_shape(
    groups: pd.DataFrame,
    exact_candidates: pd.DataFrame,
    audited_candidates: pd.DataFrame,
) -> dict:
    backtest = shape_backtest(groups, exact_candidates, audited_candidates)
    origins = sorted(backtest["origin"].unique()) if len(backtest) else []
    if len(origins) < 2:
        return {
            "kind": "pooled_exact",
            "reason": "fewer than two strictly prior inner forecast origins",
            "inner_origins": [int(value) for value in origins],
            "candidates": [],
        }
    reports = []
    for kind, frame in backtest.groupby("kind"):
        yearly = frame.groupby("origin")["quantile_mae"].mean()
        reports.append(
            {
                "kind": kind,
                "quantile_mae": float(frame["quantile_mae"].mean()),
                "yearly_quantile_mae": {str(int(year)): float(value) for year, value in yearly.items()},
            }
        )
    pooled = next(report for report in reports if report["kind"] == "pooled_exact")
    raw_best = min(reports, key=lambda report: report["quantile_mae"])
    complexity = {
        "pooled_exact": 0,
        "pooled_audited": 1,
        "lag_exact": 1,
        "lag_exact_plus_audited_pool": 2,
    }
    # A difference below 0.05 score points in average quantile MAE has no
    # practical meaning at the present sample size.  Prefer the simpler
    # candidate inside that equivalence band instead of rewarding a larger
    # data path for a numerically tiny gain.
    near_best = [
        report
        for report in reports
        if report["quantile_mae"] <= raw_best["quantile_mae"] + 0.05
    ]
    best = min(
        near_best,
        key=lambda report: (complexity.get(report["kind"], 99), report["quantile_mae"]),
    )
    improvement = pooled["quantile_mae"] - best["quantile_mae"]
    degradation = max(
        best["yearly_quantile_mae"][year] - pooled["yearly_quantile_mae"][year]
        for year in pooled["yearly_quantile_mae"]
    )
    if best["kind"] != "pooled_exact" and improvement >= 0.2 and degradation <= 1.0:
        kind = best["kind"]
        reason = "candidate distribution source and shape passed prequential guardrails"
    else:
        kind = "pooled_exact"
        reason = (
            f"best shape improvement {improvement:.3f} or worst-year degradation "
            f"{degradation:.3f} failed guardrail"
        )
    return {
        "kind": kind,
        "reason": reason,
        "inner_origins": [int(value) for value in origins],
        "best_candidate": best,
        "raw_lowest_mae_candidate": raw_best,
        "parsimony_equivalence_band": 0.05,
        "candidates": reports,
    }


def selected_shape_offsets(
    test: pd.DataFrame,
    train_groups: pd.DataFrame,
    exact_candidates: pd.DataFrame,
    audited_candidates: pd.DataFrame,
    variant: str,
) -> np.ndarray:
    use_audited = "audited" in variant
    candidates = audited_candidates if use_audited and not audited_candidates.empty else exact_candidates
    kind = "lag_school_shrinkage" if variant.startswith("lag_") else "pooled"
    return shape_offsets(test, train_groups, candidates, kind)


def point_metrics(actual, prediction) -> dict:
    actual = np.asarray(actual, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    error = actual - prediction
    return {
        "n": int(len(actual)),
        "mae": float(np.mean(np.abs(error))),
        "median_ae": float(np.median(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias_actual_minus_prediction": float(np.mean(error)),
    }


def paired_year_school_bootstrap(frame: pd.DataFrame, draws: int = 10000) -> dict:
    clean = frame.dropna(subset=["anchor_q10", "selected_q10"]).copy()
    clean["difference"] = (
        (clean["score_q10"] - clean["selected_q10"]).abs()
        - (clean["score_q10"] - clean["anchor_q10"]).abs()
    )
    years = sorted(clean["year"].unique())
    if not years:
        return {
            "estimate_selected_minus_anchor_mae": None,
            "p05": None,
            "p95": None,
            "draws": draws,
        }
    rng = np.random.default_rng(20261009)
    year_count = len(years)
    # Two-stage cluster bootstrap, vectorised.  Each selected calendar-year
    # block receives an independent within-year school resample.  The former
    # implementation repeatedly filtered a DataFrame inside 10,000 draws and
    # produced the same estimand much more slowly.
    school_bootstrap = []
    for year in years:
        values = clean.loc[clean["year"].eq(year), "difference"].to_numpy(float)
        indices = rng.integers(0, len(values), size=(draws, year_count, len(values)))
        school_bootstrap.append(values[indices].mean(axis=2))
    school_bootstrap = np.asarray(school_bootstrap)  # year x draw x sampled-year slot
    sampled_year_indices = rng.integers(0, year_count, size=(draws, year_count))
    selected = np.empty((draws, year_count), dtype=float)
    draw_indices = np.arange(draws)
    for slot in range(year_count):
        selected[:, slot] = school_bootstrap[
            sampled_year_indices[:, slot], draw_indices, slot
        ]
    estimates = selected.mean(axis=1)
    return {
        "estimate_selected_minus_anchor_mae": float(clean["difference"].mean()),
        "p05": float(np.quantile(estimates, 0.05)),
        "p95": float(np.quantile(estimates, 0.95)),
        "draws": draws,
    }


def evaluate_distribution(frame: pd.DataFrame, candidate_rows: pd.DataFrame) -> dict:
    quantile_mae = {}
    for probability in PROBABILITIES:
        actual = frame[f"score_q{int(probability * 100):02d}"]
        predicted = frame[qname(probability)]
        quantile_mae[qname(probability)] = float(np.mean(np.abs(actual - predicted)))
    merged = candidate_rows.merge(
        frame[["school", "year", *[qname(p) for p in PROBABILITIES]]],
        on=["school", "year"],
        how="inner",
    )
    coverages = {}
    pinball = []
    for probability in PROBABILITIES:
        column = qname(probability)
        group_coverage = merged.groupby(["school", "year"]).apply(
            lambda group: float(np.mean(group["initial_score"] <= group[column])),
            include_groups=False,
        )
        coverages[column] = float(group_coverage.mean())
    for _, group in merged.groupby(["school", "year"]):
        values = group["initial_score"].to_numpy(float)
        losses = []
        for probability in PROBABILITIES:
            prediction = float(group[qname(probability)].iloc[0])
            residual = values - prediction
            losses.append(np.mean(np.maximum(probability * residual, (probability - 1) * residual)))
        pinball.append(float(np.mean(losses)))
    return {
        "quantile_mae": quantile_mae,
        "mean_quantile_mae": float(np.mean(list(quantile_mae.values()))),
        "candidate_coverage": coverages,
        "mean_absolute_calibration_error": float(
            np.mean([abs(coverages[qname(p)] - p) for p in PROBABILITIES])
        ),
        "school_year_balanced_integrated_pinball": float(np.mean(pinball)),
    }


def experimental_forecast_groups(
    periods: pd.DataFrame,
    distributions: pd.DataFrame,
) -> pd.DataFrame:
    schools = pd.read_csv(DATA / "schools.csv", encoding="utf-8-sig")
    frame = forecast_group_frame(periods, schools, distributions)
    return frame.rename(columns={"baseline_q50": "anchor_q10"})


def forecast_national_mixture(frame: pd.DataFrame) -> dict:
    grid = np.linspace(0.05, 0.95, 901)
    samples = []
    for _, row in frame.iterrows():
        anchors = np.array([row[qname(p)] for p in PROBABILITIES], dtype=float)
        samples.append(np.interp(grid, PROBABILITIES, anchors))
    values = np.concatenate(samples)
    return {
        "weighting": "equal mass per school; no current admitted-count weighting is claimed",
        "schools": int(len(frame)),
        **{
            f"q{int(probability * 100):02d}": float(np.quantile(values, probability))
            for probability in PROBABILITIES
        },
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=0)),
    }


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidate_frame = load_candidate_scores(args.candidate_scores)
    groups, candidates, distributions, periods, _ = build_group_data(candidate_frame)
    audited_pool = audited_candidate_pool(candidate_frame)
    audited_distributions = audited_distribution_by_program(audited_pool)
    audited_candidates = audited_pool.merge(
        audited_distributions[
            ["school", "year", "score_q10", "candidate_evidence_tier"]
        ].rename(columns={"candidate_evidence_tier": "group_evidence_tier"}),
        on=["school", "year"],
        how="inner",
    )
    audited_candidates["shape_score"] = (
        audited_candidates["initial_score"] - audited_candidates["score_q10"]
    )
    audited_groups = build_audited_group_data(
        audited_distributions,
        periods,
        distributions,
    )
    decomposition = national_distribution_decomposition(candidates, distributions)
    distributions.to_csv(output / "candidate_distribution_summary.csv", index=False, encoding="utf-8-sig")
    audited_distributions.to_csv(
        output / "audited_candidate_distribution_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output / "national_distribution_decomposition.json").write_text(
        json.dumps(decomposition, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    outer_rows = []
    outer_selection = []
    for origin in sorted(int(year) for year in groups["year"].unique()):
        train_groups = groups[groups["year"] < origin].copy()
        test = groups[(groups["year"] == origin) & groups["anchor_q10"].notna()].copy()
        train_candidates = candidates[candidates["year"] < origin].copy()
        train_audited = audited_candidates[audited_candidates["year"] < origin].copy()
        train_audited_groups = audited_groups[audited_groups["year"] < origin].copy()
        if train_groups.empty or test.empty or train_candidates.empty:
            continue
        correction_selection = select_correction(train_groups, train_audited_groups)
        correction_fit_frame = (
            train_audited_groups
            if correction_selection["data_source"] == "audited"
            else train_groups
        )
        correction_model = fit_correction(
            correction_selection["kind"], correction_fit_frame
        )
        correction = correction_model.predict(test)
        selected_q10 = test["anchor_q10"].to_numpy(float) + float(correction_selection["blend"]) * correction
        shape_selection = select_shape(train_groups, train_candidates, train_audited)
        offsets = selected_shape_offsets(
            test,
            train_groups,
            train_candidates,
            train_audited,
            shape_selection["kind"],
        )
        predictions = selected_q10[:, None] + offsets
        predictions[:, PROBABILITIES.index(0.10)] = selected_q10
        predictions = np.sort(predictions, axis=1)
        outer_selection.append(
            {
                "origin": origin,
                "train_school_years": int(len(train_groups)),
                "train_exact_candidate_rows": int(len(train_candidates)),
                "train_audited_candidate_rows": int(len(train_audited)),
                "train_audited_school_years": int(len(train_audited_groups)),
                "test_school_years": int(len(test)),
                "correction": correction_selection,
                "shape": shape_selection,
            }
        )
        for row_index, (_, item) in enumerate(test.iterrows()):
            record = {
                "school": item["school"],
                "year": origin,
                "candidate_n": int(item["candidate_n"]),
                "anchor_q10": float(item["anchor_q10"]),
                "selected_q10": float(selected_q10[row_index]),
                "correction_kind": correction_selection["kind"],
                "correction_data_source": correction_selection["data_source"],
                "correction_blend": correction_selection["blend"],
                "shape_kind": shape_selection["kind"],
            }
            for probability_index, probability in enumerate(PROBABILITIES):
                record[f"score_q{int(probability * 100):02d}"] = float(
                    item[f"score_q{int(probability * 100):02d}"]
                )
                record[qname(probability)] = float(predictions[row_index, probability_index])
            outer_rows.append(record)
    outer = pd.DataFrame(outer_rows)
    outer.to_csv(output / "strict_outer_predictions.csv", index=False, encoding="utf-8-sig")
    outer_candidates = candidates.merge(
        outer[["school", "year"]].drop_duplicates(), on=["school", "year"], how="inner"
    )

    correction_final = select_correction(
        groups[groups["anchor_q10"].notna()],
        audited_groups[audited_groups["anchor_q10"].notna()],
    )
    shape_final = select_shape(groups, candidates, audited_candidates)
    forecast = experimental_forecast_groups(periods, distributions)
    correction_fit_frame = (
        audited_groups if correction_final["data_source"] == "audited" else groups
    )
    correction_model = fit_correction(correction_final["kind"], correction_fit_frame)
    correction = correction_model.predict(forecast)
    forecast_q10 = forecast["anchor_q10"].to_numpy(float) + float(correction_final["blend"]) * correction
    forecast_offsets = selected_shape_offsets(
        forecast,
        distributions,
        candidates,
        audited_candidates,
        shape_final["kind"],
    )
    forecast_predictions = forecast_q10[:, None] + forecast_offsets
    forecast_predictions[:, PROBABILITIES.index(0.10)] = forecast_q10
    forecast_predictions = np.sort(forecast_predictions, axis=1)
    forecast_output = forecast[["school", "year", "anchor_q10"]].copy()
    forecast_output["experimental_q10"] = forecast_q10
    forecast_output["correction_kind"] = correction_final["kind"]
    forecast_output["correction_data_source"] = correction_final["data_source"]
    forecast_output["correction_blend"] = correction_final["blend"]
    forecast_output["shape_kind"] = shape_final["kind"]
    for index, probability in enumerate(PROBABILITIES):
        forecast_output[qname(probability)] = forecast_predictions[:, index]
    forecast_output["status"] = "experimental_not_frozen_production"
    forecast_output.to_csv(
        output / "forecast_2027_hierarchical_distribution_experimental.csv",
        index=False,
        encoding="utf-8-sig",
    )

    exact_year_counts = distributions.groupby("year").size().to_dict()
    repeat_counts = distributions.groupby("school").size()
    point = {
        "anchor": point_metrics(outer["score_q10"], outer["anchor_q10"]),
        "selected": point_metrics(outer["score_q10"], outer["selected_q10"]),
    }
    yearly = {
        str(int(year)): {
            "anchor": point_metrics(frame["score_q10"], frame["anchor_q10"]),
            "selected": point_metrics(frame["score_q10"], frame["selected_q10"]),
        }
        for year, frame in outer.groupby("year")
    }
    summary = {
        "status": "post_freeze_v5_hierarchical_distribution_experiment",
        "scope": {
            "candidate_rows": int(len(candidates)),
            "school_year_distributions": int(len(distributions)),
            "schools": int(distributions["school"].nunique()),
            "year_counts": {str(int(year)): int(count) for year, count in exact_year_counts.items()},
            "schools_with_two_or_more_years": int((repeat_counts >= 2).sum()),
            "schools_with_three_or_more_years": int((repeat_counts >= 3).sum()),
            "audited_candidate_rows_retained_all_tiers": int(len(audited_pool)),
            "audited_candidate_rows_used_in_group_models": int(len(audited_candidates)),
            "audited_rows_below_five_person_group_minimum": int(
                len(audited_pool) - len(audited_candidates)
            ),
            "audited_school_year_distributions_all_tiers": int(len(audited_distributions)),
            "soft_candidate_rows": int(
                audited_candidates["group_evidence_tier"].eq("soft_roster").sum()
            ),
            "soft_school_year_distributions": int(
                audited_distributions["candidate_evidence_tier"].eq("soft_roster").sum()
            ),
        },
        "observed_distribution": decomposition,
        "strict_outer": {
            "origins": sorted(int(value) for value in outer["year"].unique()),
            "school_years": int(len(outer)),
            "point_metrics": point,
            "year_metrics": yearly,
            "distribution_metrics": evaluate_distribution(outer, outer_candidates),
            "paired_year_school_bootstrap": paired_year_school_bootstrap(outer),
            "selection_by_origin": outer_selection,
        },
        "forecast_2027_experimental": {
            "schools": int(len(forecast_output)),
            "correction_selection": correction_final,
            "shape_selection": shape_final,
            "national_equal_school_mixture": forecast_national_mixture(forecast_output),
            "guardrail": "The frozen V4 forecast is unchanged; this branch is a separately versioned experiment.",
        },
        "model_identity": {
            "threshold": "T_s,t = frozen robust anchor + prequentially selected exact-label correction",
            "shape": "Y_i,s,t - T_s,t follows a school-year-balanced national shape, optionally shrunk toward the latest same-school shape",
            "variance": "candidate within school-year + school-year within school + between-school components",
        },
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "selection_by_origin.json").write_text(
        json.dumps(outer_selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
