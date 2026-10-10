from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from candidate_score_layer import (
    apply_exact_candidate_labels,
    load_candidate_scores,
    recompute_exact_aware_features,
)
from interval_calibration import (
    RobustOriginFloorCalibrator,
    history_uncertainty_features,
    prequential_robust_origin_floor,
)
from quota_features import attach_quota_features, load_quota_events, quota_coverage


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
AUDIT = ROOT / "data" / "audit"
SITE_DATA = ROOT / "app" / "data"
RNG = np.random.default_rng(20261003)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train, backtest, and forecast the applied-statistics risk model.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA,
        help="Directory for forecast CSV/JSON and rolling backtest (default: data/processed).",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=AUDIT,
        help="Directory for model_run.json (default: data/audit).",
    )
    parser.add_argument(
        "--site-json",
        type=Path,
        default=SITE_DATA / "forecast.json",
        help="JSON payload path (set inside an experiment directory to preserve the frozen site baseline).",
    )
    return parser.parse_args()

BASE_NUMERIC_FEATURES = [
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

# 名额特征只在严格报名时点信息集内计算。它们的先验会被强收缩，
# 并且只有通过滚动回测和覆盖率门槛后才允许进入生产预测。
QUOTA_NUMERIC_FEATURES = [
    "log_regular_quota",
    "quota_shock_log",
    "quota_age",
    "quota_missing",
    "quota_direct",
    "quota_is_current",
    "quota_quality",
]

# 目前严格名额事件只覆盖约 2% 的滚动回测行，因此先保留为候选特征：
# 数据进入每所院校的输出和审计，但生产点预测默认不因稀疏样本改变。
ENABLE_QUOTA_FEATURES = False
NUMERIC_FEATURES = BASE_NUMERIC_FEATURES + (QUOTA_NUMERIC_FEATURES if ENABLE_QUOTA_FEATURES else [])

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
            elif feature == "quota_missing":
                # 缺失本身是信息质量信号，不把它误当成名额供给方向。
                group = "missingness"
            elif feature in QUOTA_NUMERIC_FEATURES:
                group = "quota_supply"
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


def fit_bayesian(
    frame,
    target,
    weights,
    prior_scale_multiplier: float = 1.0,
    surprise_prior_mean: float = -3.0,
):
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
        elif group == "quota_supply":
            # 公开名额样本目前很稀疏，使用较窄先验防止少数学校事件过拟合。
            prior_sd[idx] = 6.0
        elif group in {"static_baseline", "missingness"}:
            prior_sd[idx] = 9.0
        else:
            prior_sd[idx] = 14.0
        if group != "intercept":
            prior_sd[idx] *= max(float(prior_scale_multiplier), 0.1)
        if name == "lag1_surprise_z":
            prior_mean[idx] = float(surprise_prior_mean)

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


def prepare_frames(quota_events=None):
    periods = pd.read_csv(DATA / "program_year.csv")
    schools = pd.read_csv(DATA / "schools.csv")
    candidate_scores = load_candidate_scores()
    if quota_events is None:
        quota_events = load_quota_events()
    national_payload = json.loads((DATA / "national_lines.json").read_text(encoding="utf-8"))
    national_lines = {int(year): value for year, value in national_payload["values"].items()}
    periods = periods.merge(schools, on="school", how="left", suffixes=("", "_school"))
    periods, exact_candidate_report = apply_exact_candidate_labels(periods, candidate_scores)
    periods = recompute_exact_aware_features(periods)
    periods = attach_quota_features(periods, quota_events)
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
    # attrs 只用于调试/审计；调用方也可以重新从 CSV 加载，避免依赖 pandas
    # 在 merge/slice 后是否保留元数据。
    periods.attrs["quota_events"] = quota_events
    periods.attrs["exact_candidate_report"] = exact_candidate_report
    return periods, schools, trainable, national_lines, national_payload


def make_forecast_rows(periods, schools, forecast_year=2027, quota_events=None):
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
    forecast = attach_quota_features(forecast, quota_events)
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
            school_history = train[train["school"] == row["school"]].sort_values("year")
            history_margins = pd.to_numeric(school_history["margin_q10"], errors="coerce").dropna().to_numpy(dtype=float)
            history_weights = pd.to_numeric(school_history["model_weight"], errors="coerce").dropna().to_numpy(dtype=float)
            history_mad = (
                float(np.median(np.abs(history_margins - np.median(history_margins))) * 1.4826)
                if len(history_margins) >= 2
                else np.nan
            )
            history_methods = school_history["q10_method"].fillna("missing").astype(str)
            history_official_share = (
                float(pd.to_numeric(school_history["admission_official_url_present"], errors="coerce").fillna(0).mean())
                if len(school_history)
                else 0.0
            )
            latest_issue_count = (
                int(school_history.iloc[-1]["issue_count"])
                if len(school_history) and not pd.isna(school_history.iloc[-1]["issue_count"])
                else 0
            )
            confidence_score = min(len(history_margins) / 4.0, 1.0) * 55 + history_official_share * 30 + (
                15 if latest_issue_count == 0 else max(0, 15 - latest_issue_count * 7)
            )
            confidence_band = "较高" if confidence_score >= 72 else "中等" if confidence_score >= 48 else "较低"
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
                # Keep the backtest generative path identical to the production
                # forecast: shrink only the complex school-margin shape.  The
                # national-line distribution remains at full scale because it is
                # an independently forecast common shock, not part of the 0.35
                # model-shape coefficient.
                margin_center = float(np.quantile(margin_samples[idx], 0.50))
                margin_shape = 0.35 * (margin_samples[idx] - margin_center)
                national_shape = line_dist["samples"] - line_dist["mean"]
                raw_samples = point_anchor + margin_shape + national_shape
                selected_model = "robust_margin_anchor" if robust_baseline is not None else "last_year_anchor"
            actual = float(row["q10_value"])
            raw_quantiles = {
                q: round(float(np.quantile(raw_samples, q / 100.0)), 2)
                for q in (5, 10, 20, 50, 80, 90, 95)
            }
            record = {
                "school": row["school"],
                "year": int(test_year),
                "actual": round(actual, 2),
                **{f"pred_q{q:02d}": value for q, value in raw_quantiles.items()},
                "complex_q50": round(float(np.quantile(complex_samples, 0.50)), 2),
                "selected_model": selected_model,
                "weight": round(float(row["model_weight"]), 3),
                "is_985": bool(row["is_985"]),
                "national_zone": zone,
                "history_n": int(len(history_margins)),
                "history_weight_mean": round(float(np.mean(history_weights)), 4) if len(history_weights) else None,
                "history_margin_mad": None if not np.isfinite(history_mad) else round(history_mad, 3),
                "history_interpolation_share": round(float((history_methods == "order_stat_interpolation").mean()), 4) if len(history_methods) else 0.0,
                "history_minimum_share": round(float(history_methods.isin(["minimum_only", "small_n_minimum"]).mean()), 4) if len(history_methods) else 0.0,
                "history_official_share": round(history_official_share, 4),
                "confidence_score": round(float(confidence_score), 1),
                "confidence_band": confidence_band,
                "baseline": None if baseline is None else round(baseline, 2),
                "robust_baseline": None if robust_baseline is None else round(robust_baseline, 2),
                "quota_regular_value": None if pd.isna(row.get("quota_regular_value")) else round(float(row["quota_regular_value"]), 2),
                "quota_missing": int(row.get("quota_missing", 1.0)),
                "quota_source_year": None if pd.isna(row.get("quota_source_year")) else int(row["quota_source_year"]),
                "quota_status": row.get("quota_status", "未找到严格报名时点名额"),
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


def robust_calibration_metrics(backtests):
    """Score the robust upper-bound candidate on strictly earlier origins."""
    calibrated = prequential_robust_origin_floor(backtests)
    strict = [
        row for row in calibrated if int(row.get("robust_calibration_prior_rows", 0)) > 0
    ]
    if not strict:
        return {"rows": 0, "years": []}, calibrated
    actual = np.asarray([row["actual"] for row in strict], dtype=float)
    weights = np.asarray([row.get("weight", 1.0) for row in strict], dtype=float)
    q05 = np.asarray([row["pred_q05"] for row in strict], dtype=float)
    q10 = np.asarray([row["pred_q10"] for row in strict], dtype=float)
    q50 = np.asarray([row["pred_q50"] for row in strict], dtype=float)
    q80 = np.asarray([row["robust_q80"] for row in strict], dtype=float)
    q90 = np.asarray([row["robust_q90"] for row in strict], dtype=float)
    q95 = np.asarray([row["robust_q95"] for row in strict], dtype=float)

    def interval_score(lower, upper, alpha):
        return (
            upper
            - lower
            + (2.0 / alpha) * (lower - actual) * (actual < lower)
            + (2.0 / alpha) * (actual - upper) * (actual > upper)
        )

    wis = (
        0.5 * np.abs(actual - q50)
        + 0.10 * interval_score(q10, q90, 0.20)
        + 0.05 * interval_score(q05, q95, 0.10)
    ) / 2.5
    return {
        "rows": len(strict),
        "years": sorted({int(row["year"]) for row in strict}),
        "q80_coverage": round(float(np.average(actual <= q80, weights=weights)), 3),
        "q90_coverage": round(float(np.average(actual <= q90, weights=weights)), 3),
        "q95_coverage": round(float(np.average(actual <= q95, weights=weights)), 3),
        "wis": round(float(np.average(wis, weights=weights)), 2),
        "q90_minus_q50": round(float(np.average(q90 - q50, weights=weights)), 2),
        "warning": "仅两个严格嵌套外层年份；稳健安全上界不等于已证明的频率分位数。",
    }, calibrated


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
    args = parse_args()
    output_dir = args.output_dir.resolve()
    audit_dir = args.audit_dir.resolve()
    site_json = args.site_json.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    site_json.parent.mkdir(parents=True, exist_ok=True)
    run_mode = (
        "production_default"
        if output_dir == DATA.resolve() and site_json == (SITE_DATA / "forecast.json").resolve()
        else "experimental_preserve_frozen_baseline"
    )
    periods, schools, trainable, national_lines, national_payload = prepare_frames()
    quota_events = periods.attrs.get("quota_events")
    if quota_events is None:
        quota_events = load_quota_events()
    exact_candidate_report = periods.attrs.get("exact_candidate_report", {"applied_rows": 0})
    backtests = rolling_backtest(trainable, national_lines)
    metrics = backtest_metrics(backtests)
    robust_metrics, robust_backtests = robust_calibration_metrics(backtests)
    robust_calibrator = RobustOriginFloorCalibrator.fit(backtests)
    offsets = calibration_offsets(backtests)
    quota_report = quota_coverage(quota_events, periods)
    quota_backtest_rows = int(sum(row.get("quota_missing", 1) == 0 for row in backtests))

    bayes = fit_bayesian(trainable, trainable["margin_q10"], trainable["model_weight"])
    gbm_design, gbm_models = fit_boosting(trainable, trainable["margin_q10"], trainable["model_weight"])
    forecast, histories = make_forecast_rows(periods, schools, forecast_year=2027, quota_events=quota_events)
    quota_forecast_report = quota_coverage(quota_events, forecast)
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
            selected_model_key = "robust_margin_anchor"
        elif latest_anchor is not None and not pd.isna(latest_anchor):
            anchor_center = float(latest_anchor) + national["mean"] - national_lines[2026][zone]
            margin_shape = 0.35 * (margin_samples[idx] - np.quantile(margin_samples[idx], 0.50))
            national_shape = national["samples"] - national["mean"]
            raw = anchor_center + margin_shape + national_shape + event_draws + unknown_event_noise
            selected_model = "上一年锚定（稳健锚点缺失时回退）"
            selected_model_key = "last_year_anchor"
        else:
            raw = margin_samples[idx] + national["samples"] + event_draws + unknown_event_noise
            selected_model = "分层贝叶斯与提升树集成（锚点缺失）"
            selected_model_key = "hierarchical_ensemble_fallback"
        raw_q = {q: float(np.quantile(raw, q / 100)) for q in (5, 10, 20, 50, 80, 90, 95)}
        history_features = history_uncertainty_features(histories[school])
        robust_input = {
            "school": school,
            "pred_q50": raw_q[50],
            "pred_q80": raw_q[80],
            "pred_q90": raw_q[90],
            "pred_q95": raw_q[95],
            "is_985": bool(row["is_985"]),
            "national_zone": zone,
            "selected_model": selected_model_key,
            **history_features,
        }
        robust_result = robust_calibrator.apply([robust_input])[0]
        calibrated_median = raw_q[50]
        calibrated = {
            5: raw_q[5],
            10: raw_q[10],
            20: raw_q[20],
            50: calibrated_median,
            80: robust_result["robust_q80"],
            90: robust_result["robust_q90"],
            95: robust_result["robust_q95"],
        }
        grade, grade_score = confidence_grade(row, histories[school])
        bayes_groups = contributions[idx]
        bayes_margin_mean = sum(bayes_groups.values())
        quota_regular = to_float(row.get("quota_regular_value"))
        quota_lower = to_float(row.get("quota_lower"))
        quota_upper = to_float(row.get("quota_upper"))
        quota_age = to_float(row.get("quota_age"))
        quota_quality = to_float(row.get("quota_quality"))
        quota_source_year = to_float(row.get("quota_source_year"))
        quota_payload = {
            "regular": None if not np.isfinite(quota_regular) else round(quota_regular, 1),
            "lower": None if not np.isfinite(quota_lower) else round(quota_lower, 1),
            "upper": None if not np.isfinite(quota_upper) else round(quota_upper, 1),
            "age": None if not np.isfinite(quota_age) else int(quota_age),
            "quality": None if not np.isfinite(quota_quality) else round(quota_quality, 2),
            "sourceYear": None if not np.isfinite(quota_source_year) else int(quota_source_year),
            "status": row.get("quota_status", "未找到严格报名时点名额"),
            "sourceUrl": row.get("quota_source_url") or None,
            "sourceTitle": row.get("quota_source_title") or None,
        }
        decomposition = {
            "national_line": round(national["mean"], 1),
            "school_and_static": round(bayes_groups.get("intercept", 0.0) + bayes_groups.get("school_effect", 0.0) + bayes_groups.get("static_baseline", 0.0), 1),
            "dynamic_baseline": round(bayes_groups.get("dynamic_baseline", 0.0), 1),
            "market_reversal": round(bayes_groups.get("market_reversal", 0.0), 1),
            "peer_spillover": round(bayes_groups.get("peer_spillover", 0.0), 1),
            "quota_supply": round(bayes_groups.get("quota_supply", 0.0), 1),
            "event_expected": round(expected_event, 1),
            "ensemble_delta": round(calibrated_median - national["mean"] - expected_event - bayes_margin_mean, 1),
        }
        predictions.append({
            "school": school,
            "is985": bool(row["is_985"]),
            "zone": zone,
            "faction": row["faction"],
            "factionSource": row["faction_source"],
            "unit": None if pd.isna(row["unit_2026"]) else row["unit_2026"],
            "english": None if pd.isna(row["english_subject"]) else row["english_subject"],
            "math": None if pd.isna(row["math_subject"]) else row["math_subject"],
            "location": None if pd.isna(row["location"]) else row["location"],
            "latitude": None if pd.isna(row["latitude"]) else round(float(row["latitude"]), 7),
            "longitude": None if pd.isna(row["longitude"]) else round(float(row["longitude"]), 7),
            "locationMatchedName": None if pd.isna(row["location_matched_name"]) else row["location_matched_name"],
            "locationPrecision": None if pd.isna(row["location_precision"]) else row["location_precision"],
            "locationSource": None if pd.isna(row["location_source"]) else row["location_source"],
            "locationSourceUrl": None if pd.isna(row["location_source_url"]) else row["location_source_url"],
            "locationReviewStatus": None if pd.isna(row["location_review_status"]) else row["location_review_status"],
            "officeHub": None if pd.isna(row["office_hub"]) else row["office_hub"],
            "officeHubLatitude": None if pd.isna(row["office_hub_latitude"]) else round(float(row["office_hub_latitude"]), 7),
            "officeHubLongitude": None if pd.isna(row["office_hub_longitude"]) else round(float(row["office_hub_longitude"]), 7),
            "officeHubDefinition": None if pd.isna(row["office_hub_definition"]) else row["office_hub_definition"],
            "officeHubReviewStatus": None if pd.isna(row["office_hub_review_status"]) else row["office_hub_review_status"],
            "transitMode": None if pd.isna(row["transit_mode"]) else row["transit_mode"],
            "transitLines": None if pd.isna(row["transit_lines"]) else row["transit_lines"],
            "transitSummary": None if pd.isna(row["transit_summary"]) else row["transit_summary"],
            "transitReviewStatus": None if pd.isna(row["transit_review_status"]) else row["transit_review_status"],
            "liveRouteUrl": None if pd.isna(row["live_route_url"]) else row["live_route_url"],
            "routeSource": None if pd.isna(row["route_source"]) else row["route_source"],
            "latestCutoff": row["latest_cutoff"],
            "latestQ10Proxy": None if pd.isna(row["latest_q10_proxy"]) else float(row["latest_q10_proxy"]),
            "quota": quota_payload,
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
            "rawQ05": round(raw_q[5], 1),
            "rawQ10": round(raw_q[10], 1),
            "rawQ20": round(raw_q[20], 1),
            "rawQ50": round(raw_q[50], 1),
            "rawQ80": round(raw_q[80], 1),
            "rawQ90": round(raw_q[90], 1),
            "rawQ95": round(raw_q[95], 1),
            "upperBoundKind": "跨历史预测年份最不利残差 + 学校特异误差尺度（稳健安全上界）",
            "calibrationScale": round(float(robust_result["calibration_scale"]), 2),
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
            "selectedModelKey": selected_model_key,
            "decomposition": decomposition,
            "sourceRow": int(histories[school].iloc[-1]["source_row"]),
        })

    # A very wide robust upper bound can lose comparative decision value.  Do
    # not cap it (which would silently remove protection); instead, mark widths
    # beyond Tukey's standard upper fence as information-limited.  This rule
    # depends only on the frozen forecast distribution, never on 2027 outcomes.
    robust_widths = np.asarray(
        [item["q90"] - item["q50"] for item in predictions], dtype=float
    )
    upper_width_q1, upper_width_q3 = np.quantile(robust_widths, [0.25, 0.75])
    upper_width_iqr = upper_width_q3 - upper_width_q1
    upper_width_threshold = upper_width_q3 + 1.5 * upper_width_iqr
    flagged_upper_width_schools: list[str] = []
    for item in predictions:
        raw_width = float(item["rawQ90"] - item["rawQ50"])
        robust_width = float(item["q90"] - item["q50"])
        information_limited = robust_width > upper_width_threshold
        item["rawUpperWidth"] = round(raw_width, 1)
        item["robustUpperWidth"] = round(robust_width, 1)
        item["upperWidthStatus"] = (
            "information_limited" if information_limited else "decision_informative"
        )
        item["upperWidthWarning"] = (
            "稳健安全上界极宽，反映证据或历史波动不足；不宜把该上界与其他院校作精确难度排序。"
            if information_limited
            else None
        )
        if information_limited:
            flagged_upper_width_schools.append(item["school"])

    upper_width_guardrail = {
        "method": "tukey_upper_fence",
        "q1": round(float(upper_width_q1), 2),
        "q3": round(float(upper_width_q3), 2),
        "iqr": round(float(upper_width_iqr), 2),
        "threshold": round(float(upper_width_threshold), 2),
        "flaggedSchools": flagged_upper_width_schools,
        "interpretation": "超过阈值表示上界信息量不足，不等同于学校真实风险或难度更高；上界不作裁剪。",
        "outcomeFree": True,
    }

    predictions.sort(key=lambda item: item["q90"])
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "title": "应用统计择校风险实验室",
            "forecastYear": 2027,
            "runMode": run_mode,
            "asOf": "2026-10-07",
            "scope": "传统985/211院校中开设全日制025200应用统计的学校",
            "schoolCount": len(predictions),
            "trainingRows": len(trainable),
            "exactCandidateLabels": exact_candidate_report,
            "target": "正常统考录取初试成绩10%分位数；当前数据多数为透明代理值",
            "steadyThreshold": 0.90,
            "backtest": metrics,
            "robustUpperBacktest": robust_metrics,
            "quotaCoverage": {
                **quota_report,
                "forecastRowsWithQuota": quota_forecast_report.get("frame_rows_with_quota", 0),
                "forecastCoverage": quota_forecast_report.get("frame_coverage", 0.0),
                "backtestRowsWithQuota": quota_backtest_rows,
                "backtestCoverage": round(quota_backtest_rows / len(backtests), 4) if backtests else 0.0,
                "policy": "strict_pre_registration_only",
            },
            "legacyCalibrationOffsetsNotUsed": offsets,
            "robustUpperCalibration": {
                "method": "scaled_worst_origin_floor",
                "fittedRows": robust_calibrator.fitted_rows,
                "effectiveRows": round(robust_calibrator.effective_rows, 1),
                "standardizedFloors": {
                    f"q{q}": round(value, 4)
                    for q, value in robust_calibrator.floors.items()
                },
                "originFloors": robust_calibrator.origin_floors,
                "status": "provisional_safety_bound",
                "warning": "严格嵌套验证只有2025和2026两个外层年份；输出是稳健安全上界，不宣称精确频率保证。",
            },
            "upperWidthGuardrail": upper_width_guardrail,
            "forecastFreeze": {
                "status": "frozen_for_prospective_2027_test",
                "informationCutoff": "2026-10-07 23:59 Asia/Hong_Kong",
                "freezeDate": "2026-10-08",
                "rule": "2027结果揭示后，不得据此修改中心模型、校准规则、阈值或事件先验；任何偏离均须另建版本并保留本基线。",
                "primaryEvaluation": ["weighted_mae", "wis", "q90_coverage", "q95_coverage", "interval_width"],
            },
            "modelSelection": {
                "pointForecast": "逐年滚动回测选择历史国家线以上边际分中位数作为稳健锚点；历史不足时依次回退上一年锚点与复杂集成。",
                "uncertaintyAndExplanation": "分层贝叶斯动态模型、梯度提升分位数模型、国家线与事件情景共同生成原始分布；稳健安全上界再采用跨历史预测年份最不利标准化残差校准。",
                "pointWeights": {"robustMarginAnchor": 1.0, "lastYearFallback": 1.0, "bayesian": 0.0, "gradientBoosting": 0.0},
                "reason": "稳健边际分锚点在滚动回测中优于上一年锚点和复杂候选模型，因此不以复杂度换取表面精度。",
                "quotaFeature": {
                    "status": "candidate_not_promoted",
                    "reason": "严格名额样本仅覆盖当前滚动回测的约2%，现阶段仅展示和审计，不改变生产预测。",
                },
            },
            "nationalLineForecast": {
                zone: {key: value for key, value in national_line_distribution(national_lines, 2027, zone, size=12000).items() if key != "samples"}
                for zone in ("A", "B")
            },
            "dataWarnings": [
                f"原始表没有逐人Q10；当前精确普通统考标签覆盖 {exact_candidate_report.get('applied_rows', 0)} 条，其他可用标签由最低分、中位数和录取人数估计，网页会明确标注。",
                "370条复试线中，仅46条在原表中标为官方或官方二次来源；第三方记录已降权。",
                "当前事件表只收录已检索到的官方变化；未发现不等于确认无变化。",
                "报名时名额采用严格时间截断：仅纳入正式报名开始前发布且已人工核验的全日制025200统考名额；当前覆盖很低，名额特征仅作为收缩后的辅助信号。",
                "五大派系来自原工作簿的机构分类，并非院校官方分类；3所未覆盖院校标为待核实。",
                "81所院校均已配置培养校区坐标；坐标来自公开地图数据，仍需逐校人工复核。",
                "办公集聚区为研究用代表性节点，静态通勤线路为候选方案；点击实时规划链接核对当日线路。",
                "稳健安全上界若超过预先声明的Tukey上围栏，只解释为信息不足，不据此把学校判为异常高风险，也不人为裁剪。",
                "预测用于比较择校风险，不构成录取保证。",
            ],
            "factionCounts": schools["faction"].value_counts().to_dict(),
            "coordinateCoverage": int(schools[["latitude", "longitude"]].notna().all(axis=1).sum()),
            "commuteReferenceCoverage": int(schools[["office_hub", "transit_lines"]].notna().all(axis=1).sum()),
        },
        "predictions": predictions,
        "featureEffects": feature_effects(bayes)[:20],
        "backtestRows": backtests,
        "robustBacktestRows": robust_backtests,
        "nationalLineHistory": national_payload,
    }
    site_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "forecast_2027.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(backtests).to_csv(output_dir / "rolling_backtest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(predictions).to_csv(output_dir / "forecast_2027.csv", index=False, encoding="utf-8-sig")
    summary = {
        "run_mode": run_mode,
        "output_dir": str(output_dir),
        "site_json": str(site_json),
        "training_rows": len(trainable),
        "schools_forecast": len(predictions),
        "bayesian_sigma_margin": round(bayes.sigma, 2),
        "backtest": metrics,
        "robust_upper_backtest": robust_metrics,
        "quota_coverage": quota_report,
        "quota_backtest_rows": quota_backtest_rows,
        "quota_feature_status": "candidate_not_promoted",
        "exact_candidate_labels": exact_candidate_report,
        "calibration_offsets": offsets,
        "robust_upper_calibration": {
            "method": "scaled_worst_origin_floor",
            "fitted_rows": robust_calibrator.fitted_rows,
            "effective_rows": robust_calibrator.effective_rows,
            "standardized_floors": robust_calibrator.floors,
            "origin_floors": robust_calibrator.origin_floors,
            "status": "provisional_safety_bound",
        },
        "upper_width_guardrail": upper_width_guardrail,
        "forecast_freeze": {
            "status": "frozen_for_prospective_2027_test",
            "information_cutoff": "2026-10-07 23:59 Asia/Hong_Kong",
            "freeze_date": "2026-10-08",
            "rule": "No tuning on 2027 outcomes; preserve this baseline and version any deviation.",
        },
        "official_event_schools": sorted(events_by_school),
    }
    (audit_dir / "model_run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
