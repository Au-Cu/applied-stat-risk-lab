"""Use audited candidate rows as distributions, not merely as exact P10 labels.

The experiment is deliberately post-freeze and writes only to a versioned
output directory.  Candidate rows remain private.  Public outputs contain
school-year aggregates and predictions only.

Two safeguards are central:

1. every candidate receives weight ``1 / n_school_year`` so a large programme
   does not masquerade as many independent forecast origins;
2. rolling tests use only exact distributions from earlier calendar years.

The candidate-level branch predicts the admitted-score distribution around the
already frozen P10 forecast.  Its P10 can therefore be compared directly with
the exact admitted-score P10, while the remaining quantiles provide new
information about spread and tail shape that a single proxy label cannot hold.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import QuantileRegressor, Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from candidate_score_layer import (
    apply_exact_candidate_labels,
    candidate_distribution_by_program,
    load_candidate_scores,
    recompute_exact_aware_features,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
PRIVATE = ROOT / "data" / "private"
DEFAULT_OUTPUT = ROOT / "output" / "experiments" / "v5_candidate_distribution_20261009"
DEFAULT_ENHANCED = ROOT / "output" / "experiments" / "v4_exact_labels_20261009" / "rolling_backtest.csv"

QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
MODEL_KINDS = ("pooled", "linear_quantile", "location_scale", "shallow_gbd")
NUMERIC_FEATURES = (
    "baseline_q50",
    "baseline_lower_width",
    "baseline_upper_width",
    "is_985",
    "lag1_margin_q10",
    "trailing_margin_median",
    "lag1_surprise_z",
    "lag1_margin_change",
    "lag1_cutoff_change",
    "log_lag1_admitted_count",
    "peer_lag1_surprise_mean",
    "history_n",
    "confidence_score",
    "lag_exact_age",
    "lag_exact_candidate_n",
    "lag_exact_score_q10",
    "lag_exact_score_q50",
    "lag_exact_score_sd",
    "lag_exact_score_iqr",
    "lag_exact_lower_tail_span_q50_q10",
    "lag_exact_upper_tail_span_q90_q50",
    "lag_exact_bowley_skewness",
)
CATEGORICAL_FEATURES = (
    "national_zone",
    "english_subject",
    "math_subject",
    "faction",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--candidate-scores", type=Path, default=PRIVATE / "candidate_initial_scores.csv")
    parser.add_argument("--enhanced-backtest", type=Path, default=DEFAULT_ENHANCED)
    return parser.parse_args()


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "可用"}


def weighted_quantile(values, quantile, weights) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[mask]
    weights = weights[mask]
    if not len(values):
        return float("nan")
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights) - 0.5 * weights
    cumulative /= np.sum(weights)
    return float(np.interp(quantile, cumulative, values))


def group_balanced_weights(frame: pd.DataFrame) -> np.ndarray:
    counts = frame.groupby(["school", "year"])["initial_score"].transform("size").to_numpy(float)
    return 1.0 / np.maximum(counts, 1.0)


def exact_candidate_rows(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("model_eligible", "full_time", "special_plan"):
        result[column] = result[column].map(_bool)
    result["initial_score"] = pd.to_numeric(result["initial_score"], errors="coerce")
    result["year"] = pd.to_numeric(result["year"], errors="coerce").astype("Int64")
    return result[
        result["model_eligible"]
        & result["candidate_type"].eq("normal_exam")
        & result["full_time"]
        & ~result["special_plan"]
        & result["initial_score"].notna()
    ].copy()


def add_latest_prior_distribution(groups: pd.DataFrame, distributions: pd.DataFrame) -> pd.DataFrame:
    result = groups.copy()
    lag_columns = [
        "candidate_n",
        "score_q10",
        "score_q50",
        "score_sd",
        "score_iqr",
        "lower_tail_span_q50_q10",
        "upper_tail_span_q90_q50",
        "bowley_skewness",
    ]
    by_school = {
        school: school_frame.sort_values("year")
        for school, school_frame in distributions.groupby("school")
    }
    for index, row in result.iterrows():
        history = by_school.get(row["school"])
        if history is None:
            continue
        history = history[history["year"] < int(row["year"])]
        if history.empty:
            continue
        latest = history.iloc[-1]
        result.at[index, "lag_exact_age"] = int(row["year"]) - int(latest["year"])
        for column in lag_columns:
            result.at[index, f"lag_exact_{column}"] = latest[column]
    return result


def historical_group_frame(candidate_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    distributions = candidate_distribution_by_program(candidate_frame)
    periods = pd.read_csv(DATA / "program_year.csv", encoding="utf-8-sig")
    periods["proxy_q10_value"] = periods["q10_value"]
    periods["proxy_q10_method"] = periods["q10_method"]
    schools = pd.read_csv(DATA / "schools.csv", encoding="utf-8-sig")
    periods = periods.merge(schools, on="school", how="left", suffixes=("", "_school"))
    periods, _ = apply_exact_candidate_labels(periods, candidate_frame)
    periods = recompute_exact_aware_features(periods)
    periods["is_985"] = periods["is_985"].map(_bool).astype(int)
    periods["log_lag1_admitted_count"] = np.log1p(
        pd.to_numeric(periods["lag1_admitted_count"], errors="coerce")
    )

    baseline = pd.read_csv(DATA / "rolling_backtest.csv", encoding="utf-8-sig")
    baseline = baseline.rename(
        columns={
            "pred_q10": "baseline_q10",
            "pred_q50": "baseline_q50",
            "pred_q90": "baseline_q90",
        }
    )
    keep = [
        "school",
        "year",
        "baseline_q10",
        "baseline_q50",
        "baseline_q90",
        "history_n",
        "confidence_score",
    ]
    groups = distributions.merge(periods, on=["school", "year"], how="left", suffixes=("_exact", ""))
    groups = groups.merge(baseline[keep], on=["school", "year"], how="left")
    groups["baseline_lower_width"] = groups["baseline_q50"] - groups["baseline_q10"]
    groups["baseline_upper_width"] = groups["baseline_q90"] - groups["baseline_q50"]
    groups["exact_minus_proxy"] = groups["score_q10"] - pd.to_numeric(
        groups["proxy_q10_value"], errors="coerce"
    )
    groups = add_latest_prior_distribution(groups, distributions)
    groups = groups[groups["baseline_q50"].notna()].reset_index(drop=True)

    candidates = exact_candidate_rows(candidate_frame).merge(
        groups[["school", "year", *NUMERIC_FEATURES, *CATEGORICAL_FEATURES]],
        on=["school", "year"],
        how="inner",
    )
    return groups, candidates, distributions


def make_preprocessor() -> ColumnTransformer:
    numeric = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        [
            ("numeric", numeric, list(NUMERIC_FEATURES)),
            ("categorical", categorical, list(CATEGORICAL_FEATURES)),
        ],
        sparse_threshold=0.0,
    )


@dataclass
class FittedDistribution:
    kind: str
    quantiles: tuple[float, ...]
    models: dict
    pooled_offsets: dict
    location_model: Pipeline | None = None
    scale_model: Pipeline | None = None
    standardized_quantiles: dict | None = None

    def predict(self, groups: pd.DataFrame) -> np.ndarray:
        baseline = groups["baseline_q50"].to_numpy(float)
        predictions = []
        if self.kind == "pooled":
            for quantile in self.quantiles:
                predictions.append(baseline + self.pooled_offsets[quantile])
        elif self.kind == "location_scale":
            location = self.location_model.predict(groups)
            scale = np.maximum(np.exp(self.scale_model.predict(groups)), 2.0)
            for quantile in self.quantiles:
                predictions.append(baseline + location + scale * self.standardized_quantiles[quantile])
        else:
            for quantile in self.quantiles:
                predictions.append(baseline + self.models[quantile].predict(groups))
        matrix = np.column_stack(predictions)
        matrix = np.clip(matrix, 0.0, 500.0)
        return np.sort(matrix, axis=1)


def fit_distribution_model(kind: str, candidate_rows: pd.DataFrame, quantiles=QUANTILES) -> FittedDistribution:
    quantiles = tuple(float(value) for value in quantiles)
    residual = candidate_rows["initial_score"].to_numpy(float) - candidate_rows["baseline_q50"].to_numpy(float)
    weights = group_balanced_weights(candidate_rows)
    if kind == "pooled":
        offsets = {quantile: weighted_quantile(residual, quantile, weights) for quantile in quantiles}
        return FittedDistribution(kind, quantiles, {}, offsets)

    if kind == "location_scale":
        location_model = Pipeline(
            [("preprocess", make_preprocessor()), ("model", Ridge(alpha=12.0))]
        )
        location_model.fit(candidate_rows, residual, model__sample_weight=weights)
        fitted_location = location_model.predict(candidate_rows)
        absolute = np.abs(residual - fitted_location)
        scale_model = Pipeline(
            [("preprocess", make_preprocessor()), ("model", Ridge(alpha=16.0))]
        )
        scale_model.fit(candidate_rows, np.log(np.maximum(absolute, 1.0)), model__sample_weight=weights)
        fitted_scale = np.maximum(np.exp(scale_model.predict(candidate_rows)), 2.0)
        standardized = (residual - fitted_location) / fitted_scale
        standardized_quantiles = {
            quantile: weighted_quantile(standardized, quantile, weights)
            for quantile in quantiles
        }
        return FittedDistribution(
            kind,
            quantiles,
            {},
            {},
            location_model=location_model,
            scale_model=scale_model,
            standardized_quantiles=standardized_quantiles,
        )

    models = {}
    for quantile in quantiles:
        if kind == "linear_quantile":
            estimator = QuantileRegressor(quantile=quantile, alpha=0.15, solver="highs")
        elif kind == "shallow_gbd":
            estimator = GradientBoostingRegressor(
                loss="quantile",
                alpha=quantile,
                n_estimators=90,
                learning_rate=0.035,
                max_depth=1,
                min_samples_leaf=35,
                subsample=0.82,
                random_state=20261009,
            )
        else:
            raise ValueError(f"Unknown distribution model: {kind}")
        pipeline = Pipeline([("preprocess", make_preprocessor()), ("model", estimator)])
        pipeline.fit(candidate_rows, residual, model__sample_weight=weights)
        models[quantile] = pipeline
    return FittedDistribution(kind, quantiles, models, {})


def qcolumn(quantile: float, prefix: str = "pred") -> str:
    return f"{prefix}_q{int(round(quantile * 100)):02d}"


def cross_validated_selection(candidate_rows: pd.DataFrame, groups: pd.DataFrame) -> dict:
    schools = candidate_rows["school"].astype(str)
    unique_schools = schools.nunique()
    if unique_schools < 4:
        return {
            "selected_model": "pooled",
            "blend_lambda": 0.0,
            "candidate_models": [],
            "warning": "too few schools for grouped inner validation",
        }
    splitter = GroupKFold(n_splits=min(5, unique_schools))
    group_truth = groups.set_index(["school", "year"])["score_q10"]
    group_baseline = groups.set_index(["school", "year"])["baseline_q50"]
    reports = []
    complexity_order = {name: index for index, name in enumerate(MODEL_KINDS)}
    for kind in MODEL_KINDS:
        pieces = []
        for train_index, validation_index in splitter.split(candidate_rows, groups=schools):
            train = candidate_rows.iloc[train_index]
            validation = candidate_rows.iloc[validation_index]
            validation_groups = validation.drop_duplicates(["school", "year"])
            fitted = fit_distribution_model(kind, train, quantiles=(0.10,))
            prediction = fitted.predict(validation_groups)[:, 0]
            piece = validation_groups[["school", "year", "baseline_q50"]].copy()
            piece["candidate_q10"] = prediction
            pieces.append(piece)
        oof = pd.concat(pieces, ignore_index=True).drop_duplicates(["school", "year"])
        keys = pd.MultiIndex.from_frame(oof[["school", "year"]])
        actual = group_truth.reindex(keys).to_numpy(float)
        baseline = group_baseline.reindex(keys).to_numpy(float)
        candidate = oof["candidate_q10"].to_numpy(float)
        best = None
        for blend in np.linspace(0.0, 1.0, 21):
            prediction = baseline + blend * (candidate - baseline)
            mae = float(np.mean(np.abs(actual - prediction)))
            pinball = float(np.mean(np.where(actual >= prediction, 0.10 * (actual - prediction), 0.90 * (prediction - actual))))
            score = mae + 0.10 * pinball
            record = (score, mae, pinball, float(blend))
            if best is None or record < best:
                best = record
        reports.append(
            {
                "model": kind,
                "inner_score": best[0],
                "inner_q10_mae": best[1],
                "inner_q10_pinball": best[2],
                "blend_lambda": best[3],
                "inner_groups": int(len(oof)),
                "complexity_rank": complexity_order[kind],
            }
        )
    selected = min(reports, key=lambda row: (row["inner_score"], row["complexity_rank"]))
    return {
        "selected_model": selected["model"],
        "blend_lambda": selected["blend_lambda"],
        "candidate_models": reports,
        "selection_rule": "school-grouped CV; minimise Q10 MAE plus 0.10 times Q10 pinball loss",
    }


def predict_all_models(train_candidates: pd.DataFrame, test_groups: pd.DataFrame) -> dict[str, np.ndarray]:
    predictions = {}
    for kind in MODEL_KINDS:
        fitted = fit_distribution_model(kind, train_candidates)
        predictions[kind] = fitted.predict(test_groups)
    return predictions


def evaluate_point(actual, prediction) -> dict:
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


def distribution_metrics(predictions: pd.DataFrame, candidate_rows: pd.DataFrame) -> dict:
    quantile_errors = {}
    coverages = {}
    pinball_by_group = []
    merged = candidate_rows.merge(
        predictions[["school", "year", *[qcolumn(q) for q in QUANTILES]]],
        on=["school", "year"],
        how="inner",
    )
    for quantile in QUANTILES:
        actual_column = f"score_q{int(round(quantile * 100)):02d}"
        predicted_column = qcolumn(quantile)
        quantile_errors[predicted_column] = float(
            np.mean(np.abs(predictions[actual_column] - predictions[predicted_column]))
        )
        group_coverage = merged.groupby(["school", "year"]).apply(
            lambda frame: float(np.mean(frame["initial_score"] <= frame[predicted_column])),
            include_groups=False,
        )
        coverages[predicted_column] = float(group_coverage.mean())
    for _, frame in merged.groupby(["school", "year"]):
        losses = []
        actual = frame["initial_score"].to_numpy(float)
        for quantile in QUANTILES:
            prediction = float(frame[qcolumn(quantile)].iloc[0])
            residual = actual - prediction
            losses.append(np.mean(np.maximum(quantile * residual, (quantile - 1.0) * residual)))
        pinball_by_group.append(float(np.mean(losses)))
    calibration_error = float(
        np.mean([abs(coverages[qcolumn(q)] - q) for q in QUANTILES])
    )
    return {
        "group_quantile_mae_mean": float(np.mean(list(quantile_errors.values()))),
        "group_quantile_mae": quantile_errors,
        "group_balanced_integrated_pinball": float(np.mean(pinball_by_group)),
        "candidate_coverage": coverages,
        "mean_absolute_calibration_error": calibration_error,
    }


def weighted_mean_and_variance(values, weights) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    weights = weights / np.sum(weights)
    mean = float(np.sum(weights * values))
    variance = float(np.sum(weights * (values - mean) ** 2))
    return mean, variance


def national_distribution_decomposition(
    candidate_rows: pd.DataFrame,
    distributions: pd.DataFrame,
) -> dict:
    """Separate within-program and between-program variation.

    Three national mixtures are reported because they answer different
    questions.  Candidate weighting represents a randomly chosen admitted
    candidate.  School-year weighting represents a randomly chosen observed
    programme-year.  School weighting gives each school equal total mass and
    each observed year within that school equal mass.
    """

    rows = candidate_rows[["school", "year", "initial_score"]].copy()
    group_size = rows.groupby(["school", "year"])["initial_score"].transform("size").to_numpy(float)
    years_per_school = rows[["school", "year"]].drop_duplicates().groupby("school").size()
    school_count = int(rows["school"].nunique())
    rows["candidate_weight"] = 1.0
    rows["school_year_weight"] = 1.0 / group_size
    rows["school_weight"] = [
        1.0 / (school_count * years_per_school.loc[school] * size)
        for school, size in zip(rows["school"], group_size)
    ]
    quantile_payload = {}
    for name, weight_column in (
        ("candidate_weighted", "candidate_weight"),
        ("school_year_balanced", "school_year_weight"),
        ("school_balanced", "school_weight"),
    ):
        weights = rows[weight_column].to_numpy(float)
        scores = rows["initial_score"].to_numpy(float)
        mean, variance = weighted_mean_and_variance(scores, weights)
        quantile_payload[name] = {
            "meaning": {
                "candidate_weighted": "random admitted candidate; large programmes receive more mass",
                "school_year_balanced": "random observed school-year; every programme-year receives equal mass",
                "school_balanced": "random school, then random observed year, then random admitted candidate",
            }[name],
            "mean": mean,
            "sd": float(math.sqrt(variance)),
            **{
                f"q{int(q * 100):02d}": weighted_quantile(scores, q, weights)
                for q in QUANTILES
            },
        }

    group_mass_schemes = {
        "candidate_weighted": distributions["candidate_n"].to_numpy(float),
        "school_year_balanced": np.ones(len(distributions), dtype=float),
    }
    variance_payload = {}
    for name, mass in group_mass_schemes.items():
        mass = mass / np.sum(mass)
        group_means = distributions["score_mean"].to_numpy(float)
        group_variances = distributions["score_sd"].fillna(0).to_numpy(float) ** 2
        grand_mean = float(np.sum(mass * group_means))
        within = float(np.sum(mass * group_variances))
        between = float(np.sum(mass * (group_means - grand_mean) ** 2))
        total = within + between
        variance_payload[name] = {
            "within_school_year_variance": within,
            "between_school_year_variance": between,
            "total_variance": total,
            "within_share": within / total if total > 0 else None,
            "between_share": between / total if total > 0 else None,
            "icc_school_year": between / total if total > 0 else None,
            "identity": "Var(Y)=E[Var(Y|school,year)]+Var(E[Y|school,year])",
        }

    # Exact three-level identity under equal school mass and equal year mass
    # within each school: candidate variation + temporal variation + persistent
    # between-school variation.
    group = distributions.copy()
    group["school_years"] = group.groupby("school")["year"].transform("size")
    group["group_mass"] = 1.0 / (school_count * group["school_years"])
    school_means = (
        group.assign(weighted_mean=group["score_mean"] / group["school_years"])
        .groupby("school")["weighted_mean"]
        .sum()
    )
    grand_mean = float(school_means.mean())
    within_candidate = float(np.sum(group["group_mass"] * group["score_sd"].fillna(0) ** 2))
    within_school_time = float(
        np.sum(
            group["group_mass"]
            * (group["score_mean"] - group["school"].map(school_means)) ** 2
        )
    )
    between_school = float(np.mean((school_means - grand_mean) ** 2))
    total = within_candidate + within_school_time + between_school
    three_level = {
        "within_school_year_candidate_variance": within_candidate,
        "within_school_across_year_variance": within_school_time,
        "between_school_variance": between_school,
        "total_variance": total,
        "shares": {
            "within_school_year_candidate": within_candidate / total if total > 0 else None,
            "within_school_across_year": within_school_time / total if total > 0 else None,
            "between_school": between_school / total if total > 0 else None,
        },
        "identity": "Y_i,s,t = national mean + school effect + school-year effect + candidate deviation",
    }
    return {
        "national_mixtures": quantile_payload,
        "two_level_variance": variance_payload,
        "three_level_school_balanced_variance": three_level,
        "scope": {
            "candidate_rows": int(len(rows)),
            "school_years": int(len(distributions)),
            "schools": school_count,
        },
    }


def paired_cluster_bootstrap(frame: pd.DataFrame, draws: int = 10000) -> dict:
    frame = frame.copy()
    frame["difference"] = (
        np.abs(frame["score_q10"] - frame["selected_q10"])
        - np.abs(frame["score_q10"] - frame["baseline_q50"])
    )
    years = sorted(frame["year"].unique())
    rng = np.random.default_rng(20261009)
    values = []
    for _ in range(draws):
        sampled_years = rng.choice(years, size=len(years), replace=True)
        pieces = []
        for year in sampled_years:
            block = frame[frame["year"] == year]
            schools = block["school"].unique()
            selected_schools = rng.choice(schools, size=len(schools), replace=True)
            pieces.extend(
                float(block[block["school"] == school]["difference"].iloc[0])
                for school in selected_schools
            )
        values.append(float(np.mean(pieces)))
    return {
        "estimate_selected_minus_baseline_mae": float(frame["difference"].mean()),
        "p05": float(np.quantile(values, 0.05)),
        "p95": float(np.quantile(values, 0.95)),
        "draws": draws,
        "resampling": "calendar-year blocks with school clusters resampled inside year",
    }


def forecast_group_frame(periods: pd.DataFrame, schools: pd.DataFrame, distributions: pd.DataFrame) -> pd.DataFrame:
    public = pd.read_csv(DATA / "forecast_2027.csv", encoding="utf-8-sig")
    public = public.rename(
        columns={
            "q10": "baseline_q10",
            "q50": "baseline_q50",
            "q90": "baseline_q90",
            "zone": "national_zone_public",
            "historyCount": "history_n",
            "confidenceScore": "confidence_score",
            "lagSurpriseZ": "lag1_surprise_z_public",
            "peerPressure": "peer_lag1_surprise_mean_public",
        }
    )
    rows = []
    for _, forecast in public.iterrows():
        history = periods[periods["school"] == forecast["school"]].sort_values("year")
        if history.empty:
            continue
        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) >= 2 else None
        margins = pd.to_numeric(history["margin_q10"], errors="coerce").dropna().to_numpy(float)
        static = schools[schools["school"] == forecast["school"]].iloc[0]
        rows.append(
            {
                "school": forecast["school"],
                "year": 2027,
                "baseline_q10": float(forecast["baseline_q10"]),
                "baseline_q50": float(forecast["baseline_q50"]),
                "baseline_q90": float(forecast["baseline_q90"]),
                "baseline_lower_width": float(forecast["baseline_q50"] - forecast["baseline_q10"]),
                "baseline_upper_width": float(forecast["baseline_q90"] - forecast["baseline_q50"]),
                "is_985": int(_bool(static["is_985"])),
                "national_zone": static["national_zone"],
                "english_subject": static["english_subject"],
                "math_subject": static["math_subject"],
                "faction": static["faction"],
                "lag1_margin_q10": latest["margin_q10"],
                "trailing_margin_median": float(np.median(margins)) if len(margins) else np.nan,
                "lag1_surprise_z": forecast["lag1_surprise_z_public"],
                "lag1_margin_change": (
                    float(latest["margin_q10"] - previous["margin_q10"])
                    if previous is not None
                    and pd.notna(latest["margin_q10"])
                    and pd.notna(previous["margin_q10"])
                    else np.nan
                ),
                "lag1_cutoff_change": (
                    float(latest["cutoff"] - previous["cutoff"])
                    if previous is not None and pd.notna(latest["cutoff"]) and pd.notna(previous["cutoff"])
                    else np.nan
                ),
                "log_lag1_admitted_count": math.log1p(float(latest["admitted_count"]))
                if pd.notna(latest["admitted_count"])
                else np.nan,
                "peer_lag1_surprise_mean": forecast["peer_lag1_surprise_mean_public"],
                "history_n": forecast["history_n"],
                "confidence_score": forecast["confidence_score"],
            }
        )
    return add_latest_prior_distribution(pd.DataFrame(rows), distributions)


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidate_frame = load_candidate_scores(args.candidate_scores)
    groups, candidates, distributions = historical_group_frame(candidate_frame)
    distributions.to_csv(output / "candidate_distribution_summary.csv", index=False, encoding="utf-8-sig")
    decomposition = national_distribution_decomposition(candidates, distributions)
    (output / "national_distribution_decomposition.json").write_text(
        json.dumps(decomposition, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    enhanced = None
    if args.enhanced_backtest.is_file():
        enhanced = pd.read_csv(args.enhanced_backtest, encoding="utf-8-sig")[
            ["school", "year", "pred_q50"]
        ].rename(columns={"pred_q50": "enhanced_q50"})

    outer_rows = []
    selection_reports = []
    for origin in sorted(year for year in groups["year"].unique() if year >= 2025):
        train_candidates = candidates[candidates["year"] < origin].copy()
        train_groups = groups[groups["year"] < origin].copy()
        test_groups = groups[groups["year"] == origin].copy()
        if train_groups.empty or test_groups.empty:
            continue
        selection = cross_validated_selection(train_candidates, train_groups)
        selection["origin"] = int(origin)
        selection["train_program_years"] = int(len(train_groups))
        selection["train_candidate_rows"] = int(len(train_candidates))
        selection["test_program_years"] = int(len(test_groups))
        selection_reports.append(selection)
        model_predictions = predict_all_models(train_candidates, test_groups)
        selected_kind = selection["selected_model"]
        blend = float(selection["blend_lambda"])
        selected_matrix = model_predictions[selected_kind]
        selected_q10_raw = selected_matrix[:, QUANTILES.index(0.10)]
        selected_q10 = test_groups["baseline_q50"].to_numpy(float) + blend * (
            selected_q10_raw - test_groups["baseline_q50"].to_numpy(float)
        )
        for row_index, (_, group) in enumerate(test_groups.iterrows()):
            row = {
                "school": group["school"],
                "year": int(group["year"]),
                "candidate_n": int(group["candidate_n"]),
                **{f"score_q{int(q * 100):02d}": float(group[f"score_q{int(q * 100):02d}"]) for q in QUANTILES},
                "baseline_q50": float(group["baseline_q50"]),
                "selected_model": selected_kind,
                "blend_lambda": blend,
                "selected_q10_raw": float(selected_q10_raw[row_index]),
                "selected_q10": float(selected_q10[row_index]),
            }
            for kind, matrix in model_predictions.items():
                row[f"{kind}_q10"] = float(matrix[row_index, QUANTILES.index(0.10)])
            for quantile_index, quantile in enumerate(QUANTILES):
                row[qcolumn(quantile)] = float(selected_matrix[row_index, quantile_index])
            outer_rows.append(row)

    outer = pd.DataFrame(outer_rows)
    if enhanced is not None:
        outer = outer.merge(enhanced, on=["school", "year"], how="left")
    outer.to_csv(output / "strict_outer_predictions.csv", index=False, encoding="utf-8-sig")

    test_candidates = candidates.merge(
        outer[["school", "year"]].drop_duplicates(), on=["school", "year"], how="inner"
    )
    point_metrics = {
        "frozen_baseline": evaluate_point(outer["score_q10"], outer["baseline_q50"]),
        "selected_candidate_distribution": evaluate_point(outer["score_q10"], outer["selected_q10"]),
    }
    if "enhanced_q50" in outer and outer["enhanced_q50"].notna().any():
        valid = outer["enhanced_q50"].notna()
        point_metrics["v4_exact_label_enhanced"] = evaluate_point(
            outer.loc[valid, "score_q10"], outer.loc[valid, "enhanced_q50"]
        )
    for kind in MODEL_KINDS:
        point_metrics[f"raw_{kind}"] = evaluate_point(
            outer["score_q10"], outer[f"{kind}_q10"]
        )
    distribution_report = distribution_metrics(outer, test_candidates)

    year_metrics = {}
    for year, frame in outer.groupby("year"):
        year_metrics[str(int(year))] = {
            "baseline": evaluate_point(frame["score_q10"], frame["baseline_q50"]),
            "selected": evaluate_point(frame["score_q10"], frame["selected_q10"]),
        }

    periods = pd.read_csv(DATA / "program_year.csv", encoding="utf-8-sig")
    periods = periods.merge(
        pd.read_csv(DATA / "schools.csv", encoding="utf-8-sig"),
        on="school",
        how="left",
        suffixes=("", "_school"),
    )
    periods, _ = apply_exact_candidate_labels(periods, candidate_frame)
    periods = recompute_exact_aware_features(periods)
    schools = pd.read_csv(DATA / "schools.csv", encoding="utf-8-sig")
    forecast_groups = forecast_group_frame(periods, schools, distributions)
    final_selection = cross_validated_selection(candidates, groups)
    final_model = fit_distribution_model(final_selection["selected_model"], candidates)
    forecast_matrix = final_model.predict(forecast_groups)
    blend = float(final_selection["blend_lambda"])
    raw_q10 = forecast_matrix[:, QUANTILES.index(0.10)]
    experimental_q10 = forecast_groups["baseline_q50"].to_numpy(float) + blend * (
        raw_q10 - forecast_groups["baseline_q50"].to_numpy(float)
    )
    forecast_output = forecast_groups[["school", "year", "baseline_q50"]].copy()
    forecast_output["candidate_distribution_model"] = final_selection["selected_model"]
    forecast_output["candidate_distribution_blend_lambda"] = blend
    for index, quantile in enumerate(QUANTILES):
        forecast_output[f"admitted_score_q{int(quantile * 100):02d}"] = forecast_matrix[:, index]
    forecast_output["experimental_q10_threshold"] = experimental_q10
    forecast_output["post_freeze_status"] = "experimental_not_production"
    forecast_output.to_csv(
        output / "candidate_distribution_forecast_2027_experimental.csv",
        index=False,
        encoding="utf-8-sig",
    )

    repeated = distributions.groupby("school").size()
    summary = {
        "status": "post_freeze_retrospective_experiment",
        "candidate_rows_used": int(len(candidates)),
        "exact_program_year_distributions": int(len(distributions)),
        "exact_schools": int(distributions["school"].nunique()),
        "years": sorted(int(value) for value in distributions["year"].unique()),
        "schools_with_two_or_more_exact_years": int((repeated >= 2).sum()),
        "schools_with_three_exact_years": int((repeated >= 3).sum()),
        "distribution_descriptives": {
            "candidate_n_median": float(distributions["candidate_n"].median()),
            "score_sd_median": float(distributions["score_sd"].median()),
            "score_iqr_median": float(distributions["score_iqr"].median()),
            "lower_tail_span_median": float(distributions["lower_tail_span_q50_q10"].median()),
            "upper_tail_span_median": float(distributions["upper_tail_span_q90_q50"].median()),
            "q10_bootstrap_sd_median": float(distributions["q10_bootstrap_sd"].median()),
        },
        "national_distribution_decomposition": decomposition,
        "strict_outer": {
            "years": sorted(int(value) for value in outer["year"].unique()),
            "program_years": int(len(outer)),
            "point_metrics": point_metrics,
            "distribution_metrics": distribution_report,
            "year_metrics": year_metrics,
            "paired_cluster_bootstrap": paired_cluster_bootstrap(outer),
            "selection_by_origin": selection_reports,
        },
        "forecast_2027_experimental": {
            "rows": int(len(forecast_output)),
            "selection": final_selection,
            "guardrail": "This distributional branch does not overwrite the frozen V4/2027 forecast.",
        },
        "interpretation_guardrails": [
            "Candidate rows are correlated within school-year; effective forecast information is the number of school-years, not the number of candidates.",
            "Only exact distributions from earlier calendar years enter each outer prediction.",
            "Admitted-score quantiles describe the composition of admitted candidates, not a deterministic institutional cutoff.",
            "The full distribution adds tail and spread information; its P10 remains the decision target used for comparison.",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "selection_by_origin.json").write_text(
        json.dumps(selection_reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
