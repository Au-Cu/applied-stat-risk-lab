from __future__ import annotations

"""Compare leakage-free upper-tail calibration strategies.

The short panel contains only three scored forecast origins.  This experiment
therefore treats every strategy as a candidate, evaluates 2025 and 2026 using
only earlier OOS residuals, and reports a Pareto frontier rather than selecting
the numerically best row after seeing the test set.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import train_model as base  # noqa: E402
from model.experiment_v3_validation import metric_bundle  # noqa: E402
from model.interval_calibration import (  # noqa: E402
    cross_fitted_scales,
    fit_scale_model,
    weighted_quantile,
)


OUT = ROOT / "output" / "experiments" / "calibration_candidates_20261008"
UPPER_QUANTILES = (0.80, 0.90, 0.95)


def _weights(prior: pd.DataFrame, forecast_year: int, half_life: float = 1.75) -> np.ndarray:
    age = np.maximum(forecast_year - prior["year"].to_numpy(float), 0.0)
    return np.maximum(prior["weight"].to_numpy(float), 0.05) * np.power(
        0.5, age / half_life
    )


def _origin_quantiles(
    prior: pd.DataFrame,
    value_column: str,
    quantile: float,
) -> list[float]:
    values = []
    for _, group in prior.groupby("year", sort=True):
        values.append(
            weighted_quantile(
                group[value_column].to_numpy(float),
                quantile,
                np.maximum(group["weight"].to_numpy(float), 0.05),
            )
        )
    return values


def _correction(
    prior: pd.DataFrame,
    forecast_year: int,
    target_quantile: float,
    strategy: str,
) -> tuple[str, float]:
    q = int(target_quantile * 100)
    if strategy.endswith("tail"):
        column = f"tail_residual_{q}"
    else:
        column = "center_residual"

    if strategy.startswith("recent"):
        selected = prior[prior["year"] == prior["year"].max()]
        value = weighted_quantile(
            selected[column].to_numpy(float),
            target_quantile,
            np.maximum(selected["weight"].to_numpy(float), 0.05),
        )
        return column, value

    if strategy.startswith("worst_origin"):
        values = _origin_quantiles(prior, column, target_quantile)
        return column, max(values)

    value = weighted_quantile(
        prior[column].to_numpy(float),
        target_quantile,
        _weights(prior, forecast_year),
    )
    return column, value


def apply_strategy(raw: pd.DataFrame, strategy: str) -> pd.DataFrame:
    output = []
    for year in sorted(raw["year"].unique()):
        prior = raw[raw["year"] < year].copy()
        current = raw[raw["year"] == year].copy()
        current_scales = np.ones(len(current), dtype=float)
        standardized_origin_floor: dict[int, float] = {}
        if not prior.empty and strategy in {
            "scaled_pooled_floor",
            "scaled_worst_origin_floor",
        }:
            prior_scales = cross_fitted_scales(prior.to_dict(orient="records"))
            prior["standardized_center_residual"] = (
                prior["center_residual"].to_numpy(float) / prior_scales
            )
            scale_model = fit_scale_model(prior.to_dict(orient="records"))
            current_scales = scale_model.predict(current.to_dict(orient="records"))
            for quantile in UPPER_QUANTILES:
                q = int(quantile * 100)
                if strategy == "scaled_worst_origin_floor":
                    standardized_origin_floor[q] = max(
                        _origin_quantiles(
                            prior,
                            "standardized_center_residual",
                            quantile,
                        )
                    )
                else:
                    standardized_origin_floor[q] = weighted_quantile(
                        prior["standardized_center_residual"].to_numpy(float),
                        quantile,
                        _weights(prior, int(year)),
                    )
        for row_position, (_, row) in enumerate(current.iterrows()):
            record = row.to_dict()
            record["candidate_q05"] = float(row["pred_q05"])
            record["candidate_q10"] = float(row["pred_q10"])
            record["candidate_q20"] = float(row["pred_q20"])
            record["candidate_q50"] = float(row["pred_q50"])
            record["calibration_prior_rows"] = int(len(prior))
            for quantile in UPPER_QUANTILES:
                q = int(quantile * 100)
                raw_upper = float(row[f"pred_q{q}"])
                if prior.empty or strategy == "raw":
                    calibrated = raw_upper
                elif strategy in {"scaled_pooled_floor", "scaled_worst_origin_floor"}:
                    calibrated = max(
                        raw_upper,
                        float(row["pred_q50"])
                        + standardized_origin_floor[q] * float(current_scales[row_position]),
                    )
                else:
                    _, correction = _correction(prior, int(year), quantile, strategy)
                    if strategy.endswith("tail"):
                        calibrated = raw_upper + max(correction, 0.0)
                    else:
                        calibrated = max(
                            raw_upper,
                            float(row["pred_q50"]) + correction,
                        )
                record[f"candidate_q{q}"] = float(calibrated)
            output.append(record)
    return pd.DataFrame(output)


def _json_safe(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    _, _, trainable, national_lines, _ = base.prepare_frames()
    raw = pd.DataFrame(base.rolling_backtest(trainable, national_lines))
    raw["center_residual"] = raw["actual"] - raw["pred_q50"]
    for quantile in UPPER_QUANTILES:
        q = int(quantile * 100)
        raw[f"tail_residual_{q}"] = raw["actual"] - raw[f"pred_q{q}"]

    strategies = (
        "raw",
        "pooled_floor",
        "recent_floor",
        "worst_origin_floor",
        "pooled_tail",
        "recent_tail",
        "worst_origin_tail",
        "scaled_pooled_floor",
        "scaled_worst_origin_floor",
    )
    rows = []
    yearly_rows = []
    frames = {}
    for strategy in strategies:
        frame = apply_strategy(raw, strategy)
        frames[strategy] = frame
        strict = frame[frame["calibration_prior_rows"] > 0]
        metrics = metric_bundle(strict, "candidate")
        rows.append({"strategy": strategy, **metrics})
        for year, group in strict.groupby("year", sort=True):
            yearly_rows.append(
                {"strategy": strategy, "year": int(year), **metric_bundle(group, "candidate")}
            )

    metrics_frame = pd.DataFrame(rows)
    raw_metrics = metrics_frame[metrics_frame["strategy"] == "raw"].iloc[0]
    # A candidate is Pareto useful only if it improves calibration distance
    # without worsening WIS.  We deliberately do not auto-promote a row that
    # merely wins one of the two scored years.
    metrics_frame["q90_calibration_error"] = (
        metrics_frame["q90_coverage"] - 0.90
    ).abs()
    metrics_frame["wis_non_worse"] = metrics_frame["wis"] <= float(raw_metrics["wis"])
    metrics_frame["calibration_closer"] = (
        metrics_frame["q90_calibration_error"]
        < float(abs(raw_metrics["q90_coverage"] - 0.90))
    )
    metrics_frame["promotion_eligible"] = (
        metrics_frame["wis_non_worse"] & metrics_frame["calibration_closer"]
    )

    pd.concat(
        [frame.assign(strategy=strategy) for strategy, frame in frames.items()],
        ignore_index=True,
    ).to_csv(OUT / "candidate_rows.csv", index=False, encoding="utf-8-sig")
    metrics_frame.to_csv(OUT / "metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(yearly_rows).to_csv(
        OUT / "yearly_metrics.csv", index=False, encoding="utf-8-sig"
    )

    eligible = metrics_frame[metrics_frame["promotion_eligible"]]
    recommendation = (
        "no_automatic_promotion"
        if eligible.empty
        else "candidate_requires_future_origin_confirmation"
    )
    report = {
        "experiment": "calibration_candidates_20261008",
        "strict_years": [2025, 2026],
        "strict_rows": int((raw["year"] > raw["year"].min()).sum()),
        "recommendation": recommendation,
        "promotion_rule": "q90 calibration must be closer to 0.90 and WIS must not worsen",
        "metrics": metrics_frame.to_dict(orient="records"),
        "warning": (
            "Only two strictly nested calibration origins exist. Numerical winners are hypotheses, "
            "not evidence for production superiority."
        ),
    }
    (OUT / "summary.json").write_text(
        json.dumps(_json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(metrics_frame.to_string(index=False))
    print(json.dumps(_json_safe({"recommendation": recommendation}), ensure_ascii=False))
    return report


if __name__ == "__main__":
    run()
