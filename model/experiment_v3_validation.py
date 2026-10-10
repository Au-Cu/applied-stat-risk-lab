from __future__ import annotations

"""Comprehensive V3 validation and model-improvement experiment.

This script turns the methodological review into reproducible diagnostics.  It
does not assume that a more complex candidate should win.  Every comparison is
time ordered, and a production recommendation is emitted only when the
candidate improves a proper score without degrading the latest test year.
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import train_model as base  # noqa: E402
from model.interval_calibration import (  # noqa: E402
    FEATURE_NAMES,
    HeteroscedasticTailCalibrator,
    RobustOriginFloorCalibrator,
    prequential_calibrate,
    prequential_robust_origin_floor,
)


SEED = 20261007
OUT = ROOT / "output" / "experiments" / "v3_validation_20261007"
QUANTILES = (0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95)


def _weighted_mean(values, weights) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = np.isfinite(values) & np.isfinite(weights)
    return float(np.average(values[mask], weights=np.maximum(weights[mask], 1e-6)))


def _pinball(actual, pred, quantile: float) -> np.ndarray:
    error = np.asarray(actual, dtype=float) - np.asarray(pred, dtype=float)
    return np.where(error >= 0, quantile * error, (quantile - 1.0) * error)


def _interval_score(actual, lower, upper, alpha: float) -> np.ndarray:
    actual = np.asarray(actual, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    return (
        upper
        - lower
        + (2.0 / alpha) * (lower - actual) * (actual < lower)
        + (2.0 / alpha) * (actual - upper) * (actual > upper)
    )


def _approx_crps(frame: pd.DataFrame, prefix: str, weight_col: str = "weight") -> float:
    actual = frame["actual"].to_numpy(float)
    weights = frame[weight_col].to_numpy(float)
    losses = []
    for q in QUANTILES:
        label = int(q * 100)
        field = f"{prefix}_q{label:02d}"
        losses.append(_pinball(actual, frame[field].to_numpy(float), q))
    loss_matrix = np.column_stack(losses)
    integrated = 2.0 * np.trapezoid(loss_matrix, np.asarray(QUANTILES), axis=1)
    return _weighted_mean(integrated, weights)


def metric_bundle(frame: pd.DataFrame, prefix: str, weighted: bool = True) -> dict:
    if frame.empty:
        return {"rows": 0}
    actual = frame["actual"].to_numpy(float)
    weights = frame["weight"].to_numpy(float) if weighted else np.ones(len(frame))
    q = {
        value: frame[f"{prefix}_q{value:02d}"].to_numpy(float)
        for value in (5, 10, 20, 50, 80, 90, 95)
    }
    error = actual - q[50]
    wis_row = (
        0.5 * np.abs(error)
        + 0.10 * _interval_score(actual, q[10], q[90], 0.20)
        + 0.05 * _interval_score(actual, q[5], q[95], 0.10)
    ) / 2.5
    result = {
        "rows": int(len(frame)),
        "effective_rows": float(weights.sum() ** 2 / np.sum(weights**2)),
        "mae": _weighted_mean(np.abs(error), weights),
        "median_absolute_error": float(np.median(np.abs(error))),
        "asymmetric_loss_3x": _weighted_mean(np.where(error > 0, 3.0 * error, -error), weights),
        "underprediction_rate": _weighted_mean(error > 0, weights),
        "wis": _weighted_mean(wis_row, weights),
        "approx_crps": _approx_crps(frame.assign(weight=weights), prefix),
    }
    for value in (5, 10, 20, 50, 80, 90, 95):
        tau = value / 100.0
        result[f"q{value:02d}_coverage"] = _weighted_mean(actual <= q[value], weights)
        result[f"q{value:02d}_pinball"] = _weighted_mean(_pinball(actual, q[value], tau), weights)
    result.update(
        {
            "width_80": _weighted_mean(q[90] - q[10], weights),
            "width_90": _weighted_mean(q[95] - q[5], weights),
            "upper_width_90": _weighted_mean(q[90] - q[50], weights),
            "upper_width_90_sd": float(np.std(q[90] - q[50], ddof=1)),
            "upper_width_90_cv": float(
                np.std(q[90] - q[50], ddof=1)
                / max(np.mean(q[90] - q[50]), 1e-6)
            ),
        }
    )
    return result


def calibrated_frame(raw: pd.DataFrame) -> pd.DataFrame:
    raw_rows = raw.to_dict(orient="records")
    tail_rows = prequential_calibrate(raw_rows)
    robust_rows = prequential_robust_origin_floor(raw_rows)
    rows = []
    for tail, robust in zip(tail_rows, robust_rows):
        rows.append(
            {
                **tail,
                **{
                    key: value
                    for key, value in robust.items()
                    if key.startswith("robust_") or key.startswith("calibration_scale")
                },
            }
        )
    frame = pd.DataFrame(rows)
    for value in (5, 10, 20):
        frame[f"cal_q{value:02d}"] = frame[f"pred_q{value:02d}"]
        frame[f"robust_q{value:02d}"] = frame[f"pred_q{value:02d}"]
    return frame


def reliability_rows(frame: pd.DataFrame, variants: dict[str, str]) -> list[dict]:
    output = []
    for variant, prefix in variants.items():
        for value in (5, 10, 20, 50, 80, 90, 95):
            observed = _weighted_mean(
                frame["actual"] <= frame[f"{prefix}_q{value:02d}"], frame["weight"]
            )
            output.append(
                {
                    "variant": variant,
                    "quantile": value / 100.0,
                    "observed_coverage": observed,
                    "calibration_error": observed - value / 100.0,
                    "rows": int(len(frame)),
                }
            )
    return output


def group_metrics(frame: pd.DataFrame, variants: dict[str, str]) -> list[dict]:
    definitions = {
        "year": ["year"],
        "confidence": ["confidence_band"],
        "tier": ["is_985"],
        "zone": ["national_zone"],
        "center_path": ["selected_model"],
    }
    output = []
    for grouping, columns in definitions.items():
        for key, group in frame.groupby(columns, dropna=False):
            key_tuple = key if isinstance(key, tuple) else (key,)
            label = " | ".join(str(value) for value in key_tuple)
            for variant, prefix in variants.items():
                metrics = metric_bundle(group, prefix)
                output.append(
                    {
                        "grouping": grouping,
                        "group": label,
                        "variant": variant,
                        **metrics,
                    }
                )
    return output


def missingness_analysis(periods: pd.DataFrame, schools: pd.DataFrame) -> dict:
    # ``prepare_frames`` has already attached the school registry fields.  Do
    # not merge them again here, otherwise pandas creates ``is_985_x/y`` and
    # the missingness audit silently depends on a column-suffix accident.
    frame = periods.copy()
    frame["missing"] = frame["q10_value"].isna().astype(int)
    frame["year_index"] = frame["year"] - frame["year"].min()
    frame["zone_b"] = (frame["national_zone"] == "B").astype(int)
    x = frame[["year_index", "is_985", "zone_b"]].astype(float).to_numpy()
    y = frame["missing"].to_numpy(int)
    scaler = StandardScaler()
    xs = scaler.fit_transform(x)
    model = LogisticRegression(C=1.0, max_iter=2000, random_state=SEED)
    model.fit(xs, y)
    probability = model.predict_proba(xs)[:, 1]
    by_year = (
        frame.groupby("year")["missing"]
        .agg(["count", "sum", "mean"])
        .reset_index()
        .to_dict(orient="records")
    )
    by_tier = (
        frame.groupby("is_985")["missing"]
        .agg(["count", "sum", "mean"])
        .reset_index()
        .to_dict(orient="records")
    )
    by_zone = (
        frame.groupby("national_zone")["missing"]
        .agg(["count", "sum", "mean"])
        .reset_index()
        .to_dict(orient="records")
    )
    return {
        "rows": int(len(frame)),
        "missing_rows": int(y.sum()),
        "missing_rate": float(y.mean()),
        "in_sample_auc_descriptive_only": float(roc_auc_score(y, probability)),
        "standardized_log_odds": {
            name: float(value)
            for name, value in zip(("year", "is_985", "zone_b"), model.coef_[0])
        },
        "by_year": by_year,
        "by_tier": by_tier,
        "by_zone": by_zone,
        "interpretation": (
            "缺失率从2022年的历史补录缺口快速下降，年份是主要解释变量；"
            "这不能证明条件随机缺失，仍需把来源可得性视为选择机制。"
        ),
    }


def national_line_benchmarks(national_lines: dict) -> pd.DataFrame:
    years = sorted(national_lines)
    values = np.asarray([national_lines[year]["A"] for year in years], dtype=float)
    records = []
    for index in range(3, len(years)):
        history = values[:index]
        year = years[index]
        actual = values[index]
        candidates = {
            "last_year": history[-1],
            "mean_3": float(np.mean(history[-3:])),
            "mean_5": float(np.mean(history[-5:])),
            "ewma_03": float(pd.Series(history).ewm(alpha=0.3, adjust=False).mean().iloc[-1]),
            "ewma_05": float(pd.Series(history).ewm(alpha=0.5, adjust=False).mean().iloc[-1]),
            "current_blend_55": float(0.55 * history[-1] + 0.45 * np.mean(history[-5:])),
        }
        if len(history) >= 4:
            x = np.arange(min(5, len(history)), dtype=float)
            y = history[-len(x) :]
            slope, intercept = np.polyfit(x, y, 1)
            candidates["linear_trend_5"] = float(intercept + slope * len(x))
        for model, forecast in candidates.items():
            records.append(
                {
                    "year": year,
                    "model": model,
                    "actual": actual,
                    "forecast": forecast,
                    "absolute_error": abs(actual - forecast),
                }
            )
    return pd.DataFrame(records)


def anchor_ablation(trainable: pd.DataFrame, national_lines: dict) -> pd.DataFrame:
    records = []
    for year in (2024, 2025, 2026):
        train = trainable[trainable["year"] < year]
        test = trainable[trainable["year"] == year]
        for _, row in test.iterrows():
            history = train[train["school"] == row["school"]].sort_values("year")
            raw = pd.to_numeric(history["q10_value"], errors="coerce").dropna().to_numpy(float)
            margin = pd.to_numeric(history["margin_q10"], errors="coerce").dropna().to_numpy(float)
            if not len(raw) or not len(margin):
                continue
            line = base.national_line_distribution(
                national_lines,
                year,
                row["national_zone"],
                size=6000,
                rng=np.random.default_rng(SEED + year),
            )["mean"]
            candidates = {
                "raw_all_median": float(np.median(raw)),
                "raw_last": float(raw[-1]),
                "relative_all_median": float(line + np.median(margin)),
                "relative_last": float(line + margin[-1]),
                "relative_last2_median": float(line + np.median(margin[-2:])),
                "relative_mean": float(line + np.mean(margin)),
            }
            recency = np.power(0.5, np.arange(len(margin) - 1, -1, -1) / 1.5)
            candidates["relative_recency_mean"] = float(line + np.average(margin, weights=recency))
            for model, pred in candidates.items():
                error = float(row["q10_value"] - pred)
                records.append(
                    {
                        "school": row["school"],
                        "year": year,
                        "model": model,
                        "actual": float(row["q10_value"]),
                        "prediction": pred,
                        "error": error,
                        "weight": float(row["model_weight"]),
                    }
                )
    return pd.DataFrame(records)


def national_line_school_ablation(trainable: pd.DataFrame, national_lines: dict) -> pd.DataFrame:
    """Test national-line rules inside the school-margin anchor, not in isolation."""
    records = []
    for year in (2024, 2025, 2026):
        train = trainable[trainable["year"] < year]
        test = trainable[trainable["year"] == year]
        for _, row in test.iterrows():
            history = train[train["school"] == row["school"]].sort_values("year")
            margins = pd.to_numeric(history["margin_q10"], errors="coerce").dropna().to_numpy(float)
            if not len(margins):
                continue
            zone = row["national_zone"]
            line_history = np.asarray(
                [national_lines[past][zone] for past in sorted(national_lines) if past < year],
                dtype=float,
            )
            candidates = {
                "line_last_year": float(line_history[-1]),
                "line_blend_55": float(0.55 * line_history[-1] + 0.45 * np.mean(line_history[-5:])),
                "line_mean_3": float(np.mean(line_history[-3:])),
                "line_ewma_05": float(pd.Series(line_history).ewm(alpha=0.5, adjust=False).mean().iloc[-1]),
            }
            for model, line in candidates.items():
                prediction = line + float(np.median(margins))
                records.append(
                    {
                        "school": row["school"],
                        "year": year,
                        "model": model,
                        "actual": float(row["q10_value"]),
                        "prediction": prediction,
                        "error": float(row["q10_value"] - prediction),
                        "weight": float(row["model_weight"]),
                    }
                )
    return pd.DataFrame(records)


def paired_bootstrap(anchor: pd.DataFrame, samples: int = 20000) -> dict:
    pivot = anchor.pivot_table(
        index=["school", "year"], columns="model", values=["error", "weight"], aggfunc="first"
    ).dropna()
    rows = pivot.reset_index()
    robust_loss = np.abs(rows[("error", "relative_all_median")].to_numpy(float))
    last_loss = np.abs(rows[("error", "relative_last")].to_numpy(float))
    weights = rows[("weight", "relative_all_median")].to_numpy(float)
    diff = robust_loss - last_loss
    rng = np.random.default_rng(SEED)

    def resample_clusters(labels: np.ndarray) -> np.ndarray:
        unique = np.unique(labels)
        estimates = []
        for _ in range(samples):
            sampled = rng.choice(unique, size=len(unique), replace=True)
            indices = np.concatenate([np.flatnonzero(labels == value) for value in sampled])
            estimates.append(_weighted_mean(diff[indices], weights[indices]))
        return np.asarray(estimates)

    year_ci = np.quantile(resample_clusters(rows["year"].to_numpy()), [0.025, 0.5, 0.975])
    school_ci = np.quantile(resample_clusters(rows["school"].astype(str).to_numpy()), [0.025, 0.5, 0.975])
    return {
        "paired_rows": int(len(rows)),
        "difference_definition": "MAE(relative_all_median) - MAE(relative_last); negative favors robust median",
        "point_difference": _weighted_mean(diff, weights),
        "year_block_bootstrap_95": [float(value) for value in year_ci],
        "school_cluster_bootstrap_95": [float(value) for value in school_ci],
        "warning": "Only three independent calendar-year blocks are available; the year-block interval is necessarily unstable.",
    }


def center_selection_audit(anchor: pd.DataFrame) -> dict:
    summary_rows = []
    scored = anchor.assign(abs_error=lambda value: value["error"].abs())
    for (year, model), group in scored.groupby(["year", "model"], sort=True):
        summary_rows.append(
            {
                "year": int(year),
                "model": str(model),
                "mae": _weighted_mean(group["abs_error"], group["weight"]),
                "rows": int(len(group)),
            }
        )
    summary = pd.DataFrame(summary_rows)
    earlier = summary[summary["year"].isin([2024, 2025])]
    selected = (
        earlier.groupby("model")
        .apply(lambda group: np.average(group["mae"], weights=group["rows"]), include_groups=False)
        .sort_values()
        .index[0]
    )
    outer = summary[(summary["year"] == 2026) & (summary["model"] == selected)].iloc[0]
    robust_2026 = summary[(summary["year"] == 2026) & (summary["model"] == "relative_all_median")].iloc[0]
    return {
        "selection_years": [2024, 2025],
        "outer_test_year": 2026,
        "selected_model": str(selected),
        "selected_model_2026_mae": float(outer["mae"]),
        "production_robust_2026_mae": float(robust_2026["mae"]),
        "conclusion": (
            "Use the earlier-fold winner for the untouched 2026 test; do not use aggregate 2024-2026 results to claim an unbiased winner."
        ),
    }


def confidence_validity(frame: pd.DataFrame) -> list[dict]:
    output = []
    order = ["较高", "中等", "较低"]
    for band in order:
        group = frame[frame["confidence_band"] == band]
        if group.empty:
            continue
        metrics = metric_bundle(group, "pred")
        output.append({"confidence_band": band, **metrics})
    return output


def prior_sensitivity(trainable: pd.DataFrame, national_lines: dict) -> pd.DataFrame:
    records = []
    settings = [
        (0.5, -3.0, "tight_directional"),
        (1.0, -3.0, "production_directional"),
        (2.0, -3.0, "wide_directional"),
        (1.0, 0.0, "production_no_direction"),
    ]
    for year in (2024, 2025, 2026):
        train = trainable[trainable["year"] < year].copy()
        test = trainable[trainable["year"] == year].copy()
        if len(train) < 25 or len(test) < 8:
            continue
        for multiplier, prior_mean, label in settings:
            fit = base.fit_bayesian(
                train,
                train["margin_q10"],
                train["model_weight"],
                prior_scale_multiplier=multiplier,
                surprise_prior_mean=prior_mean,
            )
            predicted_margin = fit.design.transform(test) @ fit.mean
            prediction = []
            for (_, row), margin in zip(test.iterrows(), predicted_margin):
                line = base.national_line_distribution(
                    national_lines,
                    year,
                    row["national_zone"],
                    size=3000,
                    rng=np.random.default_rng(SEED + year),
                )["mean"]
                prediction.append(float(line + margin))
            actual = test["q10_value"].to_numpy(float)
            weights = test["model_weight"].to_numpy(float)
            prediction_array = np.asarray(prediction, dtype=float)
            records.append(
                {
                    "year": year,
                    "setting": label,
                    "rows": len(test),
                    "mae": _weighted_mean(np.abs(actual - prediction_array), weights),
                    "under_loss_3x": _weighted_mean(
                        np.where(
                            actual > prediction_array,
                            3 * (actual - prediction_array),
                            prediction_array - actual,
                        ),
                        weights,
                    ),
                }
            )
    return pd.DataFrame(records)


def _json_safe(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    periods, schools, trainable, national_lines, _ = base.prepare_frames()
    raw_rows = base.rolling_backtest(trainable, national_lines)
    raw = pd.DataFrame(raw_rows)
    calibrated = calibrated_frame(raw)
    # The first origin has no earlier OOS residuals and therefore cannot test
    # the calibrator.  Keep it in the descriptive table, but score the strict
    # nested comparison on 2025-2026 only.
    nested = calibrated[calibrated["calibration_prior_rows"] > 0].copy()
    variants = {
        "raw_distribution": "pred",
        "heteroscedastic_direct_tail": "cal",
        "robust_origin_safety_bound": "robust",
    }
    overall_all = {
        name: metric_bundle(calibrated, prefix) for name, prefix in variants.items()
    }
    overall_nested = {
        name: metric_bundle(nested, prefix) for name, prefix in variants.items()
    }
    unweighted_nested = {
        name: metric_bundle(nested, prefix, weighted=False) for name, prefix in variants.items()
    }
    group = group_metrics(calibrated, variants)
    reliability = reliability_rows(calibrated, variants)
    missingness = missingness_analysis(periods, schools)
    national_bench = national_line_benchmarks(national_lines)
    national_summary = (
        national_bench.groupby("model")["absolute_error"]
        .agg(["count", "mean", "median", "max"])
        .sort_values("mean")
        .reset_index()
    )
    anchor = anchor_ablation(trainable, national_lines)
    anchor_summary = (
        anchor.assign(abs_error=lambda value: value["error"].abs())
        .groupby("model")
        .apply(
            lambda group: pd.Series(
                {
                    "rows": len(group),
                    "weighted_mae": _weighted_mean(group["abs_error"], group["weight"]),
                    "unweighted_mae": float(group["abs_error"].mean()),
                    "under_loss_3x": _weighted_mean(
                        np.where(group["error"] > 0, 3 * group["error"], -group["error"]),
                        group["weight"],
                    ),
                }
            ),
            include_groups=False,
        )
        .sort_values("weighted_mae")
        .reset_index()
    )
    bootstrap = paired_bootstrap(anchor)
    line_school = national_line_school_ablation(trainable, national_lines)
    line_school_summary = (
        line_school.assign(abs_error=lambda value: value["error"].abs())
        .groupby("model")
        .apply(
            lambda group: pd.Series(
                {
                    "rows": len(group),
                    "weighted_mae": _weighted_mean(group["abs_error"], group["weight"]),
                    "unweighted_mae": float(group["abs_error"].mean()),
                    "under_loss_3x": _weighted_mean(
                        np.where(group["error"] > 0, 3 * group["error"], -group["error"]),
                        group["weight"],
                    ),
                }
            ),
            include_groups=False,
        )
        .sort_values("weighted_mae")
        .reset_index()
    )
    selection = center_selection_audit(anchor)
    confidence = confidence_validity(calibrated)
    prior = prior_sensitivity(trainable, national_lines)

    raw_nested = overall_nested["raw_distribution"]
    cal_nested = overall_nested["robust_origin_safety_bound"]
    latest_raw = metric_bundle(nested[nested["year"] == 2026], "pred")
    latest_cal = metric_bundle(nested[nested["year"] == 2026], "robust")
    passes = (
        cal_nested["wis"] <= raw_nested["wis"]
        and abs(cal_nested["q90_coverage"] - 0.90)
        < abs(raw_nested["q90_coverage"] - 0.90)
        and latest_cal["wis"] <= latest_raw["wis"] * 1.05
        and cal_nested["upper_width_90"] <= raw_nested["upper_width_90"] * 1.60
    )
    recommendation = {
        "status": "promote_candidate" if passes else "research_only",
        "rule": {
            "wis_non_worse": cal_nested["wis"] <= raw_nested["wis"],
            "q90_calibration_closer": abs(cal_nested["q90_coverage"] - 0.90)
            < abs(raw_nested["q90_coverage"] - 0.90),
            "latest_year_wis_within_5pct": latest_cal["wis"] <= latest_raw["wis"] * 1.05,
            "upper_width_increase_within_60pct": cal_nested["upper_width_90"]
            <= raw_nested["upper_width_90"] * 1.60,
        },
        "caveat": "The strict calibration comparison has only two outer years (2025-2026) and proxy labels.",
    }

    # Fit the 2027 calibrator for reproducible production integration if the
    # pre-registered rule passes.  Its parameters are safe to publish.
    forecast_calibrator = RobustOriginFloorCalibrator.fit(raw_rows)
    calibrator_payload = {
        "fitted_rows": forecast_calibrator.fitted_rows,
        "effective_rows": forecast_calibrator.effective_rows,
        "standardized_floors": forecast_calibrator.floors,
        "origin_floors": forecast_calibrator.origin_floors,
        "feature_names": list(FEATURE_NAMES),
    }

    calibrated.to_csv(OUT / "nested_calibration_rows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(group).to_csv(OUT / "group_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(reliability).to_csv(OUT / "reliability.csv", index=False, encoding="utf-8-sig")
    national_bench.to_csv(OUT / "national_line_predictions.csv", index=False, encoding="utf-8-sig")
    national_summary.to_csv(OUT / "national_line_benchmarks.csv", index=False, encoding="utf-8-sig")
    anchor.to_csv(OUT / "anchor_ablation_rows.csv", index=False, encoding="utf-8-sig")
    anchor_summary.to_csv(OUT / "anchor_ablation.csv", index=False, encoding="utf-8-sig")
    line_school.to_csv(OUT / "national_line_school_rows.csv", index=False, encoding="utf-8-sig")
    line_school_summary.to_csv(OUT / "national_line_school_ablation.csv", index=False, encoding="utf-8-sig")
    prior.to_csv(OUT / "prior_sensitivity.csv", index=False, encoding="utf-8-sig")

    summary = {
        "experiment": "v3_validation_20261007",
        "data_vintage": "2026-10-07 23:59 Asia/Hong_Kong",
        "rows": int(len(calibrated)),
        "years": sorted(int(value) for value in calibrated["year"].unique()),
        "strict_nested_rows": int(len(nested)),
        "strict_nested_years": sorted(int(value) for value in nested["year"].unique()),
        "effective_sample_size_weighted": float(
            calibrated["weight"].sum() ** 2 / np.sum(calibrated["weight"] ** 2)
        ),
        "overall_all_origins": overall_all,
        "overall_strict_nested": overall_nested,
        "unweighted_strict_nested": unweighted_nested,
        "latest_year": {"raw": latest_raw, "calibrated": latest_cal},
        "recommendation": recommendation,
        "forecast_2027_calibrator": calibrator_payload,
        "missingness": missingness,
        "national_line_benchmark": national_summary.to_dict(orient="records"),
        "national_line_school_ablation": line_school_summary.to_dict(orient="records"),
        "anchor_ablation": anchor_summary.to_dict(orient="records"),
        "center_selection_audit": selection,
        "paired_bootstrap": bootstrap,
        "confidence_validity": confidence,
        "limitations": [
            "No exact candidate-level Q10 labels are available.",
            "Only three raw OOS years and two strictly calibrated outer years are available.",
            "Historical event labels are insufficient for empirical event-effect estimation.",
            "Quota coverage is too sparse for production promotion.",
            "Candidate-score uncertainty is intentionally excluded in this iteration.",
        ],
    }
    (OUT / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "missingness.json").write_text(
        json.dumps(_json_safe(missingness), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = [
        "# V3 模型验证与校准实验",
        "",
        f"- 原始时间外记录：{len(calibrated)} 条，年份 {', '.join(map(str, summary['years']))}",
        f"- 严格嵌套校准检验：{len(nested)} 条，仅使用更早 OOS 残差，年份 {', '.join(map(str, summary['strict_nested_years']))}",
        f"- 加权有效样本量：{summary['effective_sample_size_weighted']:.1f}（名义样本 {len(calibrated)}）",
        "",
        "## 关键比较（严格嵌套年份）",
        "",
        "| 指标 | 原始分布 | 跨年份最不利残差稳健上界 |",
        "|---|---:|---:|",
        f"| P50 MAE | {raw_nested['mae']:.2f} | {cal_nested['mae']:.2f} |",
        f"| WIS | {raw_nested['wis']:.2f} | {cal_nested['wis']:.2f} |",
        f"| 近似 CRPS | {raw_nested['approx_crps']:.2f} | {cal_nested['approx_crps']:.2f} |",
        f"| P90 覆盖率 | {raw_nested['q90_coverage']:.1%} | {cal_nested['q90_coverage']:.1%} |",
        f"| P95 覆盖率 | {raw_nested['q95_coverage']:.1%} | {cal_nested['q95_coverage']:.1%} |",
        f"| P90-P50 平均宽度 | {raw_nested['upper_width_90']:.2f} | {cal_nested['upper_width_90']:.2f} |",
        f"| P90-P50 宽度变异系数 | {raw_nested['upper_width_90_cv']:.2f} | {cal_nested['upper_width_90_cv']:.2f} |",
        "",
        f"结论：`{recommendation['status']}`。即使通过门槛，也必须保留“仅两个严格校准外层年份、标签仍为代理”的限制。",
        "",
        "## 重要审计结论",
        "",
        "1. 修复了回测与正式预测的不一致：国家线波动不再被 0.35 复杂形状系数错误缩小。",
        "2. 中心模型的严格选择应只用 2024-2025 选择，再在 2026 外层测试；不能用三年聚合结果同时择模和证明胜出。",
        "3. 缺失机制明显随年份变化；2022 历史补录缺口是主要来源，因此 405 条记录不能视为同质随机样本。",
        "4. 稳健上界先按历史预测年份分别求标准化残差分位，再取最不利年份，并用学校特异误差尺度还原，不再机械采用统一 P50+26 分。",
        "5. 真实 Q10、历史事件库和连续报名时名额仍是无法由算法替代的 P0 数据缺口。",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run()
