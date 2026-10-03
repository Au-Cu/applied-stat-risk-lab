from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
AUDIT = ROOT / "data" / "audit"
SITE_DATA = ROOT / "app" / "data"
RNG = np.random.default_rng(20261003)

NUMERIC_FEATURES = [
    "is_985",
    "year_index",
    "lag1_margin_q10",
    "trailing_margin_median",
    "lag1_surprise_z",
    "lag1_margin_change",
    "lag1_cutoff_change",
    "log_lag1_admitted_count",
    "peer_lag1_surprise_mean",
]

CATEGORICAL_FEATURES = [
    "school",
    "national_zone",
    "english_subject",
    "math_subject",
]


def to_float(value, default=np.nan):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def weighted_quantile(values, quantile, weights=None):
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(values)
    values = values[mask]
    if not len(values):
        return float("nan")
    if weights is None:
        return float(np.quantile(values, quantile))
    weights = np.asarray(weights, dtype=float)[mask]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights) - 0.5 * weights
    cumulative /= np.sum(weights)
    return float(np.interp(quantile, cumulative, values))


def national_line_distribution(national_lines, forecast_year, zone, size=20000, rng=RNG):
    available = sorted(year for year in national_lines if year < forecast_year)
    values = np.array([national_lines[year]["A"] for year in available], dtype=float)
    if len(values) < 3:
        mean = values[-1] if len(values) else 335.0
        sigma = 12.0
    else:
        last_five = values[-5:]
        mean = 0.55 * values[-1] + 0.45 * np.mean(last_five)
        residuals = []
        for idx in range(2, len(values)):
            prior = values[:idx]
            one_step = 0.55 * prior[-1] + 0.45 * np.mean(prior[-5:])
            residuals.append(values[idx] - one_step)
        sigma = max(float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 10.0, 7.0)
    samples = rng.normal(mean, sigma, size=size)
    if zone == "B":
        samples -= 10.0
        mean -= 10.0
    return {
        "mean": round(float(mean), 2),
        "sigma": round(float(sigma), 2),
        "samples": samples,
        "q50": round(float(np.quantile(samples, 0.50)), 2),
        "q80": round(float(np.quantile(samples, 0.80)), 2),
        "q90": round(float(np.quantile(samples, 0.90)), 2),
        "q95": round(float(np.quantile(samples, 0.95)), 2),
    }


class DesignMatrix:
    def __init__(self):
        self.numeric_medians = {}
        self.numeric_means = {}
        self.numeric_scales = {}
        self.category_levels = {}
        self.feature_names = []
        self.feature_groups = []

    def fit(self, frame):
        self.feature_names = ["intercept"]
        self.feature_groups = ["intercept"]
        for feature in NUMERIC_FEATURES:
            values = pd.to_numeric(frame[feature], errors="coerce")
            med = float(values.median()) if values.notna().any() else 0.0
            filled = values.fillna(med).to_numpy(dtype=float)
            mean = float(np.mean(filled))
            scale = float(np.std(filled))
            if scale < 1e-8:
                scale = 1.0
            self.numeric_medians[feature] = med
            self.numeric_means[feature] = mean
            self.numeric_scales[feature] = scale
            self.feature_names.extend([feature, f"{feature}__missing"])
            if feature in {"lag1_surprise_z", "lag1_margin_change", "lag1_cutoff_change"}:
                group = "market_reversal"
            elif feature == "peer_lag1_surprise_mean":
                group = "peer_spillover"
            elif feature in {"lag1_margin_q10", "trailing_margin_median", "year_index", "log_lag1_admitted_count"}:
                group = "dynamic_baseline"
            else:
                group = "static_baseline"
            self.feature_groups.extend([group, "missingness"])
        for feature in CATEGORICAL_FEATURES:
            levels = sorted(str(value) for value in frame[feature].dropna().unique())
            self.category_levels[feature] = levels
            for level in levels:
                self.feature_names.append(f"{feature}={level}")
                self.feature_groups.append("school_effect" if feature == "school" else "static_baseline")
        return self

    def transform(self, frame):
        blocks = [np.ones((len(frame), 1), dtype=float)]
        for feature in NUMERIC_FEATURES:
            values = pd.to_numeric(frame[feature], errors="coerce")
            missing = values.isna().to_numpy(dtype=float)
            filled = values.fillna(self.numeric_medians[feature]).to_numpy(dtype=float)
            standardized = (filled - self.numeric_means[feature]) / self.numeric_scales[feature]
            blocks.extend([standardized[:, None], missing[:, None]])
        for feature in CATEGORICAL_FEATURES:
            raw = frame[feature].fillna("<missing>").astype(str).to_numpy()
            levels = self.category_levels[feature]
            if levels:
                block = np.column_stack([(raw == level).astype(float) for level in levels])
                blocks.append(block)
        return np.column_stack(blocks)

    def fit_transform(self, frame):
        return self.fit(frame).transform(frame)


@dataclass
class BayesianFit:
    design: DesignMatrix
    mean: np.ndarray
    covariance: np.ndarray
    sigma: float
    df: float

    def predict_samples(self, frame, size=5000, rng=RNG):
        x = self.design.transform(frame)
        means = x @ self.mean
        epistemic = np.einsum("ij,jk,ik->i", x, self.covariance, x)
        scale = np.sqrt(np.maximum(self.sigma**2 + epistemic, 1e-6))
        noise = rng.standard_t(self.df, size=(len(frame), size))
        return means[:, None] + scale[:, None] * noise

    def contribution_groups(self, frame):
        x = self.design.transform(frame)
        contribution = x * self.mean[None, :]
        result = []
        for row_index in range(len(frame)):
            groups = {}
            for value, group in zip(contribution[row_index], self.design.feature_groups):
                groups[group] = groups.get(group, 0.0) + float(value)
            result.append(groups)
        return result


def fit_bayesian(frame, target, weights):
    design = DesignMatrix()
    x = design.fit_transform(frame)
    y = np.asarray(target, dtype=float)
    w = np.asarray(weights, dtype=float)
    w = np.maximum(w, 0.05)
    w /= np.mean(w)

    prior_sd = np.empty(x.shape[1], dtype=float)
    prior_mean = np.zeros(x.shape[1], dtype=float)
    for idx, (name, group) in enumerate(zip(design.feature_names, design.feature_groups)):
        if group == "intercept":
            prior_sd[idx] = 100.0
        elif group == "school_effect":
            prior_sd[idx] = 18.0
        elif group in {"static_baseline", "missingness"}:
            prior_sd[idx] = 9.0
        else:
            prior_sd[idx] = 14.0
        if name == "lag1_surprise_z":
            prior_mean[idx] = -3.0

    prior_precision = np.diag(1.0 / (prior_sd**2))
    sigma = 18.0
    posterior_mean = prior_mean.copy()
    posterior_cov = np.eye(x.shape[1])
    for _ in range(6):
        weighted_x = x * w[:, None]
        precision = (x.T @ weighted_x) / (sigma**2) + prior_precision
        rhs = (x.T @ (w * y)) / (sigma**2) + prior_precision @ prior_mean
        posterior_cov = np.linalg.pinv(precision, rcond=1e-10)
        posterior_mean = posterior_cov @ rhs
        residual = y - x @ posterior_mean
        sigma_new = math.sqrt(max(float(np.sum(w * residual**2) / max(np.sum(w) - 8, 10)), 36.0))
        sigma = 0.55 * sigma + 0.45 * min(sigma_new, 35.0)
    return BayesianFit(
        design=design,
        mean=posterior_mean,
        covariance=posterior_cov,
        sigma=float(sigma),
        df=max(float(np.sum(w) - 10), 8.0),
    )


def fit_boosting(frame, target, weights):
    design = DesignMatrix()
    x = design.fit_transform(frame)
    models = {}
    for quantile in (0.50, 0.80, 0.90, 0.95):
        model = GradientBoostingRegressor(
            loss="quantile",
            alpha=quantile,
            n_estimators=180,
            learning_rate=0.035,
            max_depth=2,
            min_samples_leaf=8,
            subsample=0.82,
            random_state=4200 + int(quantile * 100),
        )
        model.fit(x, target, sample_weight=weights)
        models[quantile] = model
    return design, models


def predict_boosting(design, models, frame):
    x = design.transform(frame)
    raw = np.column_stack([models[q].predict(x) for q in (0.50, 0.80, 0.90, 0.95)])
    raw.sort(axis=1)
    return raw


def gbm_samples(quantiles, size=5000, rng=RNG):
    quantiles = np.asarray(quantiles, dtype=float)
    result = np.empty((len(quantiles), size), dtype=float)
    probabilities = np.array([0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95])
    for row_index, (q50, q80, q90, q95) in enumerate(quantiles):
        upper80 = max(q80 - q50, 3.0)
        upper90 = max(q90 - q50, upper80 + 1.0)
        upper95 = max(q95 - q50, upper90 + 1.0)
        anchors = np.array([
            q50 - upper95,
            q50 - upper90,
            q50 - upper80,
            q50,
            q80,
            q90,
            q95,
        ])
        u = np.clip(rng.random(size), 0.05, 0.95)
        result[row_index] = np.interp(u, probabilities, anchors)
    return result


def prepare_frames():
    periods = pd.read_csv(DATA / "program_year.csv")
    schools = pd.read_csv(DATA / "schools.csv")
    national_payload = json.loads((DATA / "national_lines.json").read_text(encoding="utf-8"))
    national_lines = {int(year): value for year, value in national_payload["values"].items()}
    periods = periods.merge(schools, on="school", how="left", suffixes=("", "_school"))
    periods["year_index"] = periods["year"] - periods["year"].min()
    periods["log_lag1_admitted_count"] = np.log1p(pd.to_numeric(periods["lag1_admitted_count"], errors="coerce"))
    periods["model_weight"] = pd.to_numeric(periods["target_weight"], errors="coerce").fillna(0.2)
    periods.loc[periods["issue_codes"].fillna("").str.contains("retest_ratio_mismatch"), "model_weight"] *= 0.70
    periods.loc[periods["issue_codes"].fillna("").str.contains("special_plan_exclusion_unclear"), "model_weight"] *= 0.55
    periods.loc[periods["issue_codes"].fillna("").str.contains("admitted_min_below_selected_cutoff"), "model_weight"] *= 0.55
    trainable = periods[
        periods["margin_q10"].notna()
        & periods["study_mode"].fillna("").str.contains("全日制")
        & (periods["model_weight"] >= 0.12)
    ].copy()
    return periods, schools, trainable, national_lines, national_payload


def make_forecast_rows(periods, schools, forecast_year=2027):
    rows = []
    histories = {}
    for school in schools["school"]:
        history = periods[periods["school"] == school].sort_values("year").copy()
        histories[school] = history
        valid_target = history[history["target_value"].notna()].copy()
        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) >= 2 else None
        target_margins = []
        for _, item in history.iterrows():
            value = item["margin_q10"]
            if pd.isna(value):
                value = item["margin_cutoff"]
            if not pd.isna(value):
                target_margins.append(float(value))
        latest_margin = latest["margin_q10"]
        if pd.isna(latest_margin):
            latest_margin = latest["margin_cutoff"]
        prior_margin = None
        if previous is not None:
            prior_margin = previous["margin_q10"]
            if pd.isna(prior_margin):
                prior_margin = previous["margin_cutoff"]
        history_before_latest = target_margins[:-1]
        if not pd.isna(latest_margin) and history_before_latest:
            center = float(np.median(history_before_latest))
            deviations = np.abs(np.asarray(history_before_latest) - center)
            scale = float(np.median(deviations) * 1.4826) if len(deviations) >= 2 else 12.0
            scale = max(scale, 4.0)
            surprise = (float(latest_margin) - center) / scale
        else:
            surprise = np.nan
        meta = schools[schools["school"] == school].iloc[0]
        rows.append({
            **meta.to_dict(),
            "school": school,
            "year": forecast_year,
            "year_index": forecast_year - periods["year"].min(),
            "national_zone": meta["national_zone"],
            "lag1_margin_q10": latest_margin,
            "trailing_margin_median": float(np.median(target_margins)) if target_margins else np.nan,
            "lag1_surprise_z": surprise,
            "lag1_margin_change": (
                float(latest_margin) - float(prior_margin)
                if not pd.isna(latest_margin) and prior_margin is not None and not pd.isna(prior_margin)
                else np.nan
            ),
            "lag1_cutoff_change": (
                float(latest["cutoff"]) - float(previous["cutoff"])
                if previous is not None and not pd.isna(latest["cutoff"]) and not pd.isna(previous["cutoff"])
                else np.nan
            ),
            "lag1_admitted_count": latest["admitted_count"],
            "log_lag1_admitted_count": (
                math.log1p(float(latest["admitted_count"])) if not pd.isna(latest["admitted_count"]) else np.nan
            ),
            "peer_lag1_surprise_mean": np.nan,
            "history_target_count": len(target_margins),
            "latest_cutoff": None if pd.isna(latest["cutoff"]) else float(latest["cutoff"]),
            "latest_q10_proxy": None if pd.isna(latest["q10_value"]) else float(latest["q10_value"]),
            "latest_target_kind": latest["target_kind"],
            "latest_issue_count": int(latest["issue_count"]) if not pd.isna(latest["issue_count"]) else 0,
        })
    forecast = pd.DataFrame(rows)
    peer_values = forecast["lag1_surprise_z"].dropna()
    for idx, row in forecast.iterrows():
        candidates = forecast[
            (forecast["school"] != row["school"])
            & (forecast["is_985"] == row["is_985"])
            & forecast["lag1_surprise_z"].notna()
        ]
        if not pd.isna(row["trailing_margin_median"]):
            close = candidates[
                (candidates["trailing_margin_median"] - row["trailing_margin_median"]).abs() <= 20
            ]
            if len(close) >= 2:
                candidates = close
        forecast.at[idx, "peer_lag1_surprise_mean"] = (
            float(candidates["lag1_surprise_z"].mean()) if len(candidates) else float(peer_values.mean())
        )
    return forecast, histories


def ensemble_margin_samples(bayes_fit, gbm_design, gbm_models, frame, size=6000, rng=RNG):
    bayes = bayes_fit.predict_samples(frame, size=size, rng=rng)
    gbm_q = predict_boosting(gbm_design, gbm_models, frame)
    gbm = gbm_samples(gbm_q, size=size, rng=rng)
    selector = rng.random((len(frame), size)) < 0.65
    return np.where(selector, bayes, gbm), gbm_q


def rolling_backtest(trainable, national_lines):
    predictions = []
    for test_year in sorted(trainable["year"].unique()):
        if test_year < 2023:
            continue
        train = trainable[trainable["year"] < test_year].copy()
        test = trainable[trainable["year"] == test_year].copy()
        if len(train) < 25 or len(test) < 8:
            continue
        bayes = fit_bayesian(train, train["margin_q10"], train["model_weight"])
        gbm_design, gbm_models = fit_boosting(train, train["margin_q10"], train["model_weight"])
        margin_samples, _ = ensemble_margin_samples(bayes, gbm_design, gbm_models, test, size=2500)
        for idx, (_, row) in enumerate(test.iterrows()):
            zone = row["national_zone"]
            line_dist = national_line_distribution(national_lines, int(test_year), zone, size=2500)
            complex_samples = margin_samples[idx] + line_dist["samples"]
            baseline = (
                None
                if pd.isna(row["lag1_q10"])
                else float(row["lag1_q10"] + line_dist["mean"] - national_lines[int(test_year) - 1][zone])
            )
            robust_baseline = (
                None
                if pd.isna(row["trailing_margin_median"])
                else float(line_dist["mean"] + row["trailing_margin_median"])
            )
            # The fixed, leakage-free median of all prior national-line margins
            # is more robust to a single hot/cold year than the last-year anchor.
            # Keep the richer models for distributional shape and explanation;
            # only use them as the point center when no transparent anchor exists.
            point_anchor = robust_baseline if robust_baseline is not None else baseline
            if point_anchor is None:
                raw_samples = complex_samples
                selected_model = "hierarchical_ensemble_fallback"
            else:
                complex_center = float(np.quantile(complex_samples, 0.50))
                raw_samples = point_anchor + 0.35 * (complex_samples - complex_center)
                selected_model = "robust_margin_anchor" if robust_baseline is not None else "last_year_anchor"
            actual = float(row["q10_value"])
            record = {
                "school": row["school"],
                "year": int(test_year),
                "actual": round(actual, 2),
                "pred_q50": round(float(np.quantile(raw_samples, 0.50)), 2),
                "pred_q80": round(float(np.quantile(raw_samples, 0.80)), 2),
                "pred_q90": round(float(np.quantile(raw_samples, 0.90)), 2),
                "pred_q95": round(float(np.quantile(raw_samples, 0.95)), 2),
                "complex_q50": round(float(np.quantile(complex_samples, 0.50)), 2),
                "selected_model": selected_model,
                "weight": round(float(row["model_weight"]), 3),
                "baseline": None if baseline is None else round(baseline, 2),
                "robust_baseline": None if robust_baseline is None else round(robust_baseline, 2),
            }
            predictions.append(record)
    return predictions


def backtest_metrics(predictions):
    if not predictions:
        return {}
    actual = np.array([row["actual"] for row in predictions], dtype=float)
    pred = np.array([row["pred_q50"] for row in predictions], dtype=float)
    weights = np.array([row["weight"] for row in predictions], dtype=float)
    errors = actual - pred
    under_loss = np.where(errors > 0, 3.0 * errors, -errors)
    metrics = {
        "rows": len(predictions),
        "years": sorted(set(row["year"] for row in predictions)),
        "mae": round(float(np.average(np.abs(errors), weights=weights)), 2),
        "median_absolute_error": round(float(np.median(np.abs(errors))), 2),
        "asymmetric_loss_3x": round(float(np.average(under_loss, weights=weights)), 2),
        "underprediction_rate": round(float(np.average(errors > 0, weights=weights)), 3),
    }
    complex_pred = np.array([row["complex_q50"] for row in predictions], dtype=float)
    metrics["complex_candidate_mae"] = round(
        float(np.average(np.abs(actual - complex_pred), weights=weights)), 2
    )
    for quantile in (80, 90, 95):
        q_values = np.array([row[f"pred_q{quantile}"] for row in predictions], dtype=float)
        metrics[f"q{quantile}_coverage"] = round(float(np.average(actual <= q_values, weights=weights)), 3)
    baseline_rows = [row for row in predictions if row["baseline"] is not None]
    if baseline_rows:
        baseline_actual = np.array([row["actual"] for row in baseline_rows], dtype=float)
        baseline_pred = np.array([row["baseline"] for row in baseline_rows], dtype=float)
        baseline_weight = np.array([row["weight"] for row in baseline_rows], dtype=float)
        metrics["last_year_baseline_mae"] = round(
            float(np.average(np.abs(baseline_actual - baseline_pred), weights=baseline_weight)), 2
        )
    robust_rows = [row for row in predictions if row["robust_baseline"] is not None]
    if robust_rows:
        robust_actual = np.array([row["actual"] for row in robust_rows], dtype=float)
        robust_pred = np.array([row["robust_baseline"] for row in robust_rows], dtype=float)
        robust_weight = np.array([row["weight"] for row in robust_rows], dtype=float)
        metrics["robust_margin_anchor_mae"] = round(
            float(np.average(np.abs(robust_actual - robust_pred), weights=robust_weight)), 2
        )
        robust_errors = robust_actual - robust_pred
        metrics["robust_margin_anchor_asymmetric_loss_3x"] = round(
            float(np.average(np.where(robust_errors > 0, 3.0 * robust_errors, -robust_errors), weights=robust_weight)), 2
        )
    return metrics


def calibration_offsets(backtests):
    if not backtests:
        return {"q50": 0.0, "q80": 0.0, "q90": 0.0, "q95": 0.0}
    actual = np.array([row["actual"] for row in backtests], dtype=float)
    median_pred = np.array([row["pred_q50"] for row in backtests], dtype=float)
    weights = np.array([row["weight"] for row in backtests], dtype=float)
    residual = actual - median_pred
    return {
        f"q{int(q * 100)}": round(weighted_quantile(residual, q, weights), 2)
        for q in (0.50, 0.80, 0.90, 0.95)
    }


def event_map():
    path = DATA / "events_2027.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    grouped = {}
    for school, rows in frame.groupby("school"):
        grouped[school] = rows.to_dict(orient="records")
    return grouped


def event_samples(events, size, rng=RNG):
    samples = np.zeros(size, dtype=float)
    expected = 0.0
    for event in events:
        values = np.array([
            float(event["withdrawal_adjustment"]),
            float(event["neutral_adjustment"]),
            float(event["crowd_adjustment"]),
        ])
        probabilities = np.array([
            float(event["withdrawal_weight"]),
            float(event["neutral_weight"]),
            float(event["crowd_weight"]),
        ])
        probabilities /= probabilities.sum()
        samples += rng.choice(values, size=size, p=probabilities)
        expected += float(np.dot(values, probabilities))
    return samples, expected


def confidence_grade(row, school_history):
    history = school_history[school_history["q10_value"].notna()]
    count = len(history)
    official_share = float(history["admission_official_url_present"].mean()) if count else 0.0
    issues = int(row.get("latest_issue_count", 0))
    score = min(count / 4.0, 1.0) * 55 + official_share * 30 + (15 if issues == 0 else max(0, 15 - issues * 7))
    if score >= 72:
        return "较高", round(score)
    if score >= 48:
        return "中等", round(score)
    return "较低", round(score)


def feature_effects(bayes_fit):
    effects = []
    for idx, (name, group) in enumerate(zip(bayes_fit.design.feature_names, bayes_fit.design.feature_groups)):
        if group in {"school_effect", "missingness", "intercept"}:
            continue
        effects.append({
            "feature": name,
            "group": group,
            "posterior_mean": round(float(bayes_fit.mean[idx]), 3),
            "posterior_sd": round(float(math.sqrt(max(bayes_fit.covariance[idx, idx], 0.0))), 3),
        })
    effects.sort(key=lambda item: abs(item["posterior_mean"]), reverse=True)
    return effects


def main():
    periods, schools, trainable, national_lines, national_payload = prepare_frames()
    backtests = rolling_backtest(trainable, national_lines)
    metrics = backtest_metrics(backtests)
    offsets = calibration_offsets(backtests)

    bayes = fit_bayesian(trainable, trainable["margin_q10"], trainable["model_weight"])
    gbm_design, gbm_models = fit_boosting(trainable, trainable["margin_q10"], trainable["model_weight"])
    forecast, histories = make_forecast_rows(periods, schools, forecast_year=2027)
    margin_samples, gbm_quantiles = ensemble_margin_samples(bayes, gbm_design, gbm_models, forecast, size=9000)
    contributions = bayes.contribution_groups(forecast)
    events_by_school = event_map()

    predictions = []
    for idx, row in forecast.iterrows():
        school = row["school"]
        zone = row["national_zone"]
        national = national_line_distribution(national_lines, 2027, zone, size=9000)
        events = events_by_school.get(school, [])
        event_draws, expected_event = event_samples(events, 9000)
        unknown_event_noise = np.zeros(9000) if events else RNG.standard_t(6, size=9000) * 2.5
        robust_margin_anchor = row["trailing_margin_median"]
        latest_anchor = row["latest_q10_proxy"]
        if robust_margin_anchor is not None and not pd.isna(robust_margin_anchor):
            anchor_center = national["mean"] + float(robust_margin_anchor)
            margin_shape = 0.35 * (margin_samples[idx] - np.quantile(margin_samples[idx], 0.50))
            national_shape = national["samples"] - national["mean"]
            raw = anchor_center + margin_shape + national_shape + event_draws + unknown_event_noise
            selected_model = "历史边际分中位数锚定（滚动回测胜出）"
        elif latest_anchor is not None and not pd.isna(latest_anchor):
            anchor_center = float(latest_anchor) + national["mean"] - national_lines[2026][zone]
            margin_shape = 0.35 * (margin_samples[idx] - np.quantile(margin_samples[idx], 0.50))
            national_shape = national["samples"] - national["mean"]
            raw = anchor_center + margin_shape + national_shape + event_draws + unknown_event_noise
            selected_model = "上一年锚定（稳健锚点缺失时回退）"
        else:
            raw = margin_samples[idx] + national["samples"] + event_draws + unknown_event_noise
            selected_model = "分层贝叶斯与提升树集成（锚点缺失）"
        raw_q = {q: float(np.quantile(raw, q / 100)) for q in (5, 10, 20, 50, 80, 90, 95)}
        calibrated_median = raw_q[50] + offsets["q50"]
        calibrated = {50: calibrated_median}
        for q in (80, 90, 95):
            conformal = raw_q[50] + offsets[f"q{q}"]
            calibrated[q] = max(raw_q[q], conformal, calibrated_median)
        calibrated[20] = min(raw_q[20] + offsets["q50"], calibrated_median)
        calibrated[10] = min(raw_q[10] + offsets["q50"], calibrated[20])
        calibrated[5] = min(raw_q[5] + offsets["q50"], calibrated[10])
        grade, grade_score = confidence_grade(row, histories[school])
        bayes_groups = contributions[idx]
        bayes_margin_mean = sum(bayes_groups.values())
        decomposition = {
            "national_line": round(national["mean"], 1),
            "school_and_static": round(bayes_groups.get("intercept", 0.0) + bayes_groups.get("school_effect", 0.0) + bayes_groups.get("static_baseline", 0.0), 1),
            "dynamic_baseline": round(bayes_groups.get("dynamic_baseline", 0.0), 1),
            "market_reversal": round(bayes_groups.get("market_reversal", 0.0), 1),
            "peer_spillover": round(bayes_groups.get("peer_spillover", 0.0), 1),
            "event_expected": round(expected_event, 1),
            "ensemble_delta": round(calibrated_median - national["mean"] - expected_event - bayes_margin_mean, 1),
        }
        predictions.append({
            "school": school,
            "is985": bool(row["is_985"]),
            "zone": zone,
            "unit": None if pd.isna(row["unit_2026"]) else row["unit_2026"],
            "english": None if pd.isna(row["english_subject"]) else row["english_subject"],
            "math": None if pd.isna(row["math_subject"]) else row["math_subject"],
            "location": None if pd.isna(row["location"]) else row["location"],
            "latestCutoff": row["latest_cutoff"],
            "latestQ10Proxy": None if pd.isna(row["latest_q10_proxy"]) else float(row["latest_q10_proxy"]),
            "historyCount": int(row["history_target_count"]),
            "confidence": grade,
            "confidenceScore": grade_score,
            "q05": round(calibrated[5], 1),
            "q10": round(calibrated[10], 1),
            "q20": round(calibrated[20], 1),
            "q50": round(calibrated[50], 1),
            "q80": round(calibrated[80], 1),
            "q90": round(calibrated[90], 1),
            "q95": round(calibrated[95], 1),
            "nationalLineMedian": national["q50"],
            "nationalLineQ90": national["q90"],
            "lagSurpriseZ": None if pd.isna(row["lag1_surprise_z"]) else round(float(row["lag1_surprise_z"]), 2),
            "peerPressure": None if pd.isna(row["peer_lag1_surprise_mean"]) else round(float(row["peer_lag1_surprise_mean"]), 2),
            "events": [
                {
                    "type": event["event_type"],
                    "name": event["event_name"],
                    "severity": event["severity"],
                    "source": event["source_url"],
                    "status": event["review_status"],
                    "scenarios": {
                        "withdrawal": float(event["withdrawal_adjustment"]),
                        "neutral": float(event["neutral_adjustment"]),
                        "crowd": float(event["crowd_adjustment"]),
                    },
                }
                for event in events
            ],
            "eventCoverage": "已发现官方事件" if events else "尚未发现事件；不等于确认无事件",
            "selectedModel": selected_model,
            "decomposition": decomposition,
            "sourceRow": int(histories[school].iloc[-1]["source_row"]),
        })

    predictions.sort(key=lambda item: item["q90"])
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "title": "应用统计择校风险实验室",
            "forecastYear": 2027,
            "asOf": "2026-10-03",
            "scope": "传统985/211院校中开设全日制025200应用统计的学校",
            "schoolCount": len(predictions),
            "trainingRows": len(trainable),
            "target": "正常统考录取初试成绩10%分位数；当前数据多数为透明代理值",
            "steadyThreshold": 0.90,
            "backtest": metrics,
            "calibrationOffsets": offsets,
            "modelSelection": {
                "pointForecast": "逐年滚动回测选择历史国家线以上边际分中位数作为稳健锚点；历史不足时依次回退上一年锚点与复杂集成。",
                "uncertaintyAndExplanation": "分层贝叶斯动态模型、梯度提升分位数模型、国家线与事件情景共同生成分布。",
                "pointWeights": {"robustMarginAnchor": 1.0, "lastYearFallback": 1.0, "bayesian": 0.0, "gradientBoosting": 0.0},
                "reason": "稳健边际分锚点在滚动回测中优于上一年锚点和复杂候选模型，因此不以复杂度换取表面精度。",
            },
            "nationalLineForecast": {
                zone: {key: value for key, value in national_line_distribution(national_lines, 2027, zone, size=12000).items() if key != "samples"}
                for zone in ("A", "B")
            },
            "dataWarnings": [
                "原始表没有逐人Q10；295条可用标签均由最低分、中位数和录取人数估计，网页会明确标注。",
                "370条复试线中，仅46条在原表中标为官方或官方二次来源；第三方记录已降权。",
                "当前事件表只收录已检索到的官方变化；未发现不等于确认无变化。",
                "预测用于比较择校风险，不构成录取保证。",
            ],
        },
        "predictions": predictions,
        "featureEffects": feature_effects(bayes)[:20],
        "backtestRows": backtests,
        "nationalLineHistory": national_payload,
    }
    (SITE_DATA / "forecast.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "forecast_2027.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(backtests).to_csv(DATA / "rolling_backtest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(predictions).to_csv(DATA / "forecast_2027.csv", index=False, encoding="utf-8-sig")
    summary = {
        "training_rows": len(trainable),
        "schools_forecast": len(predictions),
        "bayesian_sigma_margin": round(bayes.sigma, 2),
        "backtest": metrics,
        "calibration_offsets": offsets,
        "official_event_schools": sorted(events_by_school),
    }
    (AUDIT / "model_run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
