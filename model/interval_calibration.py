from __future__ import annotations

"""Leakage-controlled, heteroscedastic upper-tail calibration.

The production model predicts a school-specific raw distribution.  This module
does not replace that distribution with a global ``P50 + constant`` rule.
Instead it learns a residual scale from earlier out-of-sample errors and then
conformalizes each upper quantile relative to the model's own raw quantile.

The scale model only uses information available before the forecast origin:
raw interval width, prior-history length/volatility, prior evidence quality,
school tier/zone, and whether a transparent anchor was available.
"""

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold


QUANTILES = (0.80, 0.90, 0.95)
FEATURE_NAMES = (
    "log_raw_q90_width",
    "log_history_n",
    "history_weight_mean",
    "log_history_margin_mad",
    "history_interpolation_share",
    "history_minimum_share",
    "history_official_share",
    "is_985",
    "zone_b",
    "complex_fallback",
)


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def weighted_quantile(values, quantile: float, weights=None) -> float:
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(values)
    values = values[mask]
    if not len(values):
        return 0.0
    if weights is None:
        return float(np.quantile(values, quantile))
    weights = np.asarray(weights, dtype=float)[mask]
    weights = np.maximum(weights, 1e-6)
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights) - 0.5 * weights
    cumulative /= np.sum(weights)
    return float(np.interp(quantile, cumulative, values))


def history_uncertainty_features(history) -> dict:
    """Summarize pre-origin history without using the target-year outcome."""
    margins = np.asarray(
        [float(v) for v in history.get("margin_q10", []) if _finite(v)], dtype=float
    )
    weights = np.asarray(
        [float(v) for v in history.get("model_weight", []) if _finite(v)], dtype=float
    )
    methods = [str(v) for v in history.get("q10_method", [])]
    mad = (
        float(np.median(np.abs(margins - np.median(margins))) * 1.4826)
        if len(margins) >= 2
        else np.nan
    )
    return {
        "history_n": int(len(margins)),
        "history_weight_mean": float(np.mean(weights)) if len(weights) else np.nan,
        "history_margin_mad": mad,
        "history_interpolation_share": (
            float(np.mean(np.asarray(methods) == "order_stat_interpolation"))
            if methods
            else 0.0
        ),
        "history_minimum_share": (
            float(
                np.mean(
                    np.isin(
                        np.asarray(methods),
                        ["minimum_only", "small_n_minimum"],
                    )
                )
            )
            if methods
            else 0.0
        ),
        "history_official_share": (
            float(np.mean(np.asarray(history.get("admission_official_url_present", []), dtype=float)))
            if len(history.get("admission_official_url_present", []))
            else 0.0
        ),
    }


def _feature_vector(row: dict) -> list[float]:
    q50 = float(row.get("pred_q50", row.get("q50", 0.0)))
    q90 = float(row.get("pred_q90", row.get("q90", q50)))
    return [
        np.log1p(max(q90 - q50, 0.0)),
        np.log1p(max(float(row.get("history_n") or 0.0), 0.0)),
        float(row.get("history_weight_mean")) if _finite(row.get("history_weight_mean")) else np.nan,
        np.log1p(max(float(row.get("history_margin_mad")), 0.0)) if _finite(row.get("history_margin_mad")) else np.nan,
        float(row.get("history_interpolation_share") or 0.0),
        float(row.get("history_minimum_share") or 0.0),
        float(row.get("history_official_share") or 0.0),
        float(bool(row.get("is_985", row.get("is985", False)))),
        float(str(row.get("national_zone", row.get("zone", "A"))) == "B"),
        float("fallback" in str(row.get("selected_model", row.get("selectedModel", ""))).lower()),
    ]


@dataclass
class ResidualScaleModel:
    medians: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    model: Ridge | None
    constant: float

    def predict(self, rows: Iterable[dict]) -> np.ndarray:
        rows = list(rows)
        if not rows:
            return np.asarray([], dtype=float)
        matrix = np.asarray([_feature_vector(row) for row in rows], dtype=float)
        matrix = np.where(np.isfinite(matrix), matrix, self.medians[None, :])
        standardized = (matrix - self.means[None, :]) / self.scales[None, :]
        if self.model is None:
            prediction = np.full(len(rows), np.log1p(self.constant), dtype=float)
        else:
            prediction = self.model.predict(standardized)
        return np.clip(np.expm1(prediction), 5.0, 55.0)


def fit_scale_model(rows: list[dict], alpha: float = 12.0) -> ResidualScaleModel:
    matrix = np.asarray([_feature_vector(row) for row in rows], dtype=float)
    if not len(matrix):
        zeros = np.zeros(len(FEATURE_NAMES), dtype=float)
        ones = np.ones(len(FEATURE_NAMES), dtype=float)
        return ResidualScaleModel(zeros, zeros, ones, None, 18.0)
    medians = np.nanmedian(matrix, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    matrix = np.where(np.isfinite(matrix), matrix, medians[None, :])
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0)
    scales = np.where(scales < 1e-8, 1.0, scales)
    errors = np.asarray(
        [abs(float(row["actual"]) - float(row["pred_q50"])) for row in rows],
        dtype=float,
    )
    weights = np.asarray([max(float(row.get("weight", 1.0)), 0.05) for row in rows])
    constant = weighted_quantile(errors, 0.50, weights)
    if len(rows) < 24 or float(np.std(errors)) < 1e-8:
        return ResidualScaleModel(medians, means, scales, None, max(constant, 5.0))
    model = Ridge(alpha=alpha)
    model.fit((matrix - means[None, :]) / scales[None, :], np.log1p(errors), sample_weight=weights)
    return ResidualScaleModel(medians, means, scales, model, max(constant, 5.0))


def cross_fitted_scales(rows: list[dict]) -> np.ndarray:
    if len(rows) < 24:
        model = fit_scale_model(rows)
        return model.predict(rows)
    groups = np.asarray([str(row.get("school", index)) for index, row in enumerate(rows)])
    unique_groups = np.unique(groups)
    if len(unique_groups) < 4:
        return fit_scale_model(rows).predict(rows)
    splits = min(5, len(unique_groups))
    result = np.full(len(rows), np.nan, dtype=float)
    placeholder = np.zeros((len(rows), 1), dtype=float)
    for train_index, test_index in GroupKFold(n_splits=splits).split(placeholder, groups=groups):
        model = fit_scale_model([rows[index] for index in train_index])
        result[test_index] = model.predict([rows[index] for index in test_index])
    fallback = fit_scale_model(rows).predict(rows)
    return np.where(np.isfinite(result), result, fallback)


@dataclass
class HeteroscedasticTailCalibrator:
    scale_model: ResidualScaleModel
    corrections: dict[int, float]
    fitted_rows: int
    effective_rows: float

    @classmethod
    def fit(
        cls,
        rows: list[dict],
        forecast_year: int,
        recency_half_life: float = 1.75,
    ) -> "HeteroscedasticTailCalibrator":
        if not rows:
            return cls(fit_scale_model([]), {80: 0.0, 90: 0.0, 95: 0.0}, 0, 0.0)
        scales = cross_fitted_scales(rows)
        ages = np.asarray(
            [max(forecast_year - int(row.get("year", forecast_year)), 0) for row in rows],
            dtype=float,
        )
        weights = np.asarray([max(float(row.get("weight", 1.0)), 0.05) for row in rows])
        weights *= np.power(0.5, ages / recency_half_life)
        corrections: dict[int, float] = {}
        for quantile in QUANTILES:
            q = int(quantile * 100)
            scores = np.asarray(
                [
                    (float(row["actual"]) - float(row[f"pred_q{q}"])) / scale
                    for row, scale in zip(rows, scales)
                ],
                dtype=float,
            )
            # Never narrow the raw model interval in production.  A negative
            # correction is evidence that the raw tail was already conservative.
            corrections[q] = max(0.0, weighted_quantile(scores, quantile, weights))
        effective_rows = float(weights.sum() ** 2 / np.sum(weights**2))
        return cls(
            scale_model=fit_scale_model(rows),
            corrections=corrections,
            fitted_rows=len(rows),
            effective_rows=effective_rows,
        )

    def apply(self, rows: Iterable[dict]) -> list[dict]:
        rows = list(rows)
        scales = self.scale_model.predict(rows)
        output = []
        for row, scale in zip(rows, scales):
            calibrated = {50: float(row.get("pred_q50", row.get("q50")))}
            for q in (80, 90, 95):
                raw = float(row.get(f"pred_q{q}", row.get(f"q{q}")))
                calibrated[q] = raw + self.corrections[q] * float(scale)
            calibrated[80] = max(calibrated[50], calibrated[80])
            calibrated[90] = max(calibrated[80], calibrated[90])
            calibrated[95] = max(calibrated[90], calibrated[95])
            output.append(
                {
                    **row,
                    "calibration_scale": float(scale),
                    **{f"cal_q{q}": float(value) for q, value in calibrated.items()},
                }
            )
        return output


def prequential_calibrate(rows: list[dict]) -> list[dict]:
    """Calibrate each test year using only earlier OOS residuals."""
    output: list[dict] = []
    years = sorted({int(row["year"]) for row in rows})
    for year in years:
        current = [dict(row) for row in rows if int(row["year"]) == year]
        prior = [dict(row) for row in rows if int(row["year"]) < year]
        calibrator = HeteroscedasticTailCalibrator.fit(prior, forecast_year=year)
        calibrated = calibrator.apply(current)
        for row in calibrated:
            row["calibration_prior_rows"] = calibrator.fitted_rows
            row["calibration_effective_rows"] = calibrator.effective_rows
            row["calibration_corrections"] = dict(calibrator.corrections)
        output.extend(calibrated)
    return output

@dataclass
class RobustOriginFloorCalibrator:
    """Distributionally robust upper bounds across historical forecast origins.

    A pooled conformal correction can disappear after one unusually easy
    calibration year.  With only a few calendar origins, that behaviour is
    undesirable for a high-cost-underprediction decision.  This calibrator
    estimates a standardized upper residual quantile inside every historical
    origin and uses the largest origin-specific value as a safety floor.  A
    ridge scale model then maps that common standardized floor back to a
    school-specific number of score points.

    The result is deliberately named a robust upper bound rather than a
    frequency-guaranteed predictive quantile: only two strictly nested outer
    years are currently available.
    """

    scale_model: ResidualScaleModel
    floors: dict[int, float]
    origin_floors: dict[int, dict[int, float]]
    fitted_rows: int
    effective_rows: float

    @classmethod
    def fit(cls, rows: list[dict]) -> "RobustOriginFloorCalibrator":
        if not rows:
            return cls(
                scale_model=fit_scale_model([]),
                floors={80: 0.0, 90: 0.0, 95: 0.0},
                origin_floors={},
                fitted_rows=0,
                effective_rows=0.0,
            )
        scales = cross_fitted_scales(rows)
        residuals = np.asarray(
            [float(row["actual"]) - float(row["pred_q50"]) for row in rows],
            dtype=float,
        )
        standardized = residuals / np.maximum(scales, 1e-6)
        weights = np.asarray(
            [max(float(row.get("weight", 1.0)), 0.05) for row in rows],
            dtype=float,
        )
        years = np.asarray([int(row.get("year", 0)) for row in rows], dtype=int)
        origin_floors: dict[int, dict[int, float]] = {}
        floors: dict[int, float] = {}
        for q_value in QUANTILES:
            q = int(q_value * 100)
            by_origin: dict[int, float] = {}
            for year in sorted(np.unique(years)):
                selected = years == year
                by_origin[int(year)] = weighted_quantile(
                    standardized[selected], q_value, weights[selected]
                )
            origin_floors[q] = by_origin
            floors[q] = max(0.0, max(by_origin.values()))
        return cls(
            scale_model=fit_scale_model(rows),
            floors=floors,
            origin_floors=origin_floors,
            fitted_rows=len(rows),
            effective_rows=float(weights.sum() ** 2 / np.sum(weights**2)),
        )

    def apply(self, rows: Iterable[dict]) -> list[dict]:
        rows = list(rows)
        scales = self.scale_model.predict(rows)
        output = []
        for row, scale in zip(rows, scales):
            q50 = float(row.get("pred_q50", row.get("q50")))
            calibrated = {50: q50}
            for q in (80, 90, 95):
                raw = float(row.get(f"pred_q{q}", row.get(f"q{q}")))
                calibrated[q] = max(raw, q50 + self.floors[q] * float(scale))
            calibrated[80] = max(q50, calibrated[80])
            calibrated[90] = max(calibrated[80], calibrated[90])
            calibrated[95] = max(calibrated[90], calibrated[95])
            output.append(
                {
                    **row,
                    "calibration_scale": float(scale),
                    **{f"robust_q{q}": float(value) for q, value in calibrated.items()},
                }
            )
        return output


def prequential_robust_origin_floor(rows: list[dict]) -> list[dict]:
    """Apply the robust-origin floor using only earlier OOS origins."""
    output: list[dict] = []
    years = sorted({int(row["year"]) for row in rows})
    for year in years:
        current = [dict(row) for row in rows if int(row["year"]) == year]
        prior = [dict(row) for row in rows if int(row["year"]) < year]
        calibrator = RobustOriginFloorCalibrator.fit(prior)
        calibrated = calibrator.apply(current)
        for row in calibrated:
            row["robust_calibration_prior_rows"] = calibrator.fitted_rows
            row["robust_calibration_effective_rows"] = calibrator.effective_rows
            row["robust_calibration_floors"] = dict(calibrator.floors)
        output.extend(calibrated)
    return output
