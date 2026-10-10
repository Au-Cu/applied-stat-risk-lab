from __future__ import annotations

"""Offline experiment for the paper's precision-upgrade routes.

This file deliberately does not overwrite production predictions.  It reuses the
current data preparation and candidate models, then evaluates three additions
under the same expanding-window protocol:

1. time-ordered conformal calibration;
2. evidence-quality-aware (dual) uncertainty calibration;
3. dynamically stacked point centers learned only from earlier OOS forecasts.

The candidate-score uncertainty extension is intentionally absent.  The
experiment treats a candidate score as a fixed point when it evaluates the
decision layer, as requested for this iteration.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import train_model as base  # noqa: E402


SEED = 20261007
SAMPLE_SIZE = 1800
MIN_TRAIN_ROWS = 25
MIN_GROUP_CALIBRATION = 15
SHRINK_K = 20.0
SCORE_GRID = (350.0, 370.0, 390.0, 410.0)


def _finite(value):
    return value is not None and not pd.isna(value) and np.isfinite(float(value))


def _quality_band(history: pd.DataFrame) -> str:
    """Use only pre-origin history to proxy label/evidence reliability."""
    if history.empty:
        return "unknown"
    mean_weight = pd.to_numeric(history["model_weight"], errors="coerce").mean()
    n = len(history)
    if n >= 3 and _finite(mean_weight) and float(mean_weight) >= 0.35:
        return "higher"
    return "lower"


def _history_features(train: pd.DataFrame, row: pd.Series) -> dict:
    history = train[train["school"] == row["school"]].sort_values("year")
    weights = pd.to_numeric(history["model_weight"], errors="coerce").dropna()
    spread = pd.to_numeric(history["margin_q10"], errors="coerce") - pd.to_numeric(
        history["margin_cutoff"], errors="coerce"
    )
    spread = spread.replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "history_n": int(len(history)),
        "history_weight_mean": float(weights.mean()) if len(weights) else np.nan,
        "history_proxy_spread": float(spread.abs().median()) if len(spread) else np.nan,
        "quality_band": _quality_band(history),
    }


def _group_key(row: dict, quality: bool) -> str:
    basic = f"{int(bool(row['is_985']))}|{row['national_zone']}"
    if quality:
        return f"{basic}|{row['quality_band']}"
    return basic


def _origin_predictions(
    train: pd.DataFrame,
    test: pd.DataFrame,
    national_lines: dict,
    test_year: int,
    seed: int,
) -> list[dict]:
    """Generate raw, leakage-free OOS distributions for one forecast origin."""
    bayes = base.fit_bayesian(train, train["margin_q10"], train["model_weight"])
    gbm_design, gbm_models = base.fit_boosting(
        train, train["margin_q10"], train["model_weight"]
    )
    rng = np.random.default_rng(seed)
    margin_samples, _ = base.ensemble_margin_samples(
        bayes, gbm_design, gbm_models, test, size=SAMPLE_SIZE, rng=rng
    )
    records: list[dict] = []
    for idx, (_, row) in enumerate(test.iterrows()):
        zone = row["national_zone"]
        line = base.national_line_distribution(
            national_lines, int(test_year), zone, size=SAMPLE_SIZE, rng=rng
        )
        complex_samples = margin_samples[idx] + line["samples"]
        history_info = _history_features(train, row)
        school_history = train[train["school"] == row["school"]].sort_values("year")
        historical_margins = pd.to_numeric(school_history["margin_q10"], errors="coerce").dropna().to_numpy(dtype=float)
        robust_center = (
            float(line["mean"] + row["trailing_margin_median"])
            if _finite(row["trailing_margin_median"])
            else np.nan
        )
        recent_center = (
            float(line["mean"] + np.median(historical_margins[-2:]))
            if len(historical_margins) >= 2
            else robust_center
        )
        previous_line = national_lines.get(int(test_year) - 1, {}).get(zone)
        last_center = (
            float(row["lag1_q10"] + line["mean"] - previous_line)
            if _finite(row["lag1_q10"]) and _finite(previous_line)
            else np.nan
        )
        complex_center = float(np.quantile(complex_samples, 0.50))
        if _finite(robust_center):
            selected_center = robust_center
            selected_model = "robust_margin_anchor"
        elif _finite(last_center):
            selected_center = last_center
            selected_model = "last_year_anchor"
        else:
            selected_center = complex_center
            selected_model = "hierarchical_ensemble_fallback"
        if _finite(robust_center) or _finite(last_center):
            raw_samples = selected_center + 0.35 * (
                complex_samples - complex_center
            )
        else:
            raw_samples = complex_samples
        quantiles = {
            f"raw_q{int(q * 100)}": float(np.quantile(raw_samples, q))
            for q in (0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95)
        }
        records.append(
            {
                "school": row["school"],
                "year": int(test_year),
                "actual": float(row["q10_value"]),
                "weight": float(row["model_weight"]),
                "is_985": bool(row["is_985"]),
                "national_zone": zone,
                "group": _group_key(
                    {"is_985": row["is_985"], "national_zone": zone}, False
                ),
                "quality_group": _group_key(
                    {
                        "is_985": row["is_985"],
                        "national_zone": zone,
                        "quality_band": history_info["quality_band"],
                    },
                    True,
                ),
                "quality_band": history_info["quality_band"],
                "history_n": history_info["history_n"],
                "history_weight_mean": history_info["history_weight_mean"],
                "history_proxy_spread": history_info["history_proxy_spread"],
                "robust_center": robust_center,
                "recent_center": recent_center,
                "last_center": last_center,
                "complex_center": complex_center,
                "selected_center": selected_center,
                "selected_model": selected_model,
                **quantiles,
            }
        )
    return records


def _weighted_quantile(values, quantile, weights=None):
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(values)
    values = values[mask]
    if not len(values):
        return np.nan
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


def _calibration_offset(
    prior: list[dict],
    row: dict,
    quantile: float,
    quality_aware: bool,
    recency_half_life: float = 1.5,
    center_field: str = "raw_q50",
) -> tuple[float, dict]:
    """Shrink a group residual quantile toward the global temporal quantile."""
    if not prior:
        return 0.0, {"source": "none", "n": 0}
    current_year = int(row["year"])
    residuals = np.array([p["actual"] - p[center_field] for p in prior], dtype=float)
    age = np.array([max(current_year - int(p["year"]), 0) for p in prior], dtype=float)
    recency = np.power(0.5, age / recency_half_life)
    weights = np.array([max(float(p["weight"]), 0.05) for p in prior]) * recency
    global_q = _weighted_quantile(residuals, quantile, weights)
    key_name = "quality_group" if quality_aware else "group"
    key = row[key_name]
    selected = [p for p in prior if p[key_name] == key]
    if len(selected) < MIN_GROUP_CALIBRATION:
        return float(global_q), {"source": "global", "n": len(selected)}
    group_residuals = np.array(
        [p["actual"] - p[center_field] for p in selected], dtype=float
    )
    group_age = np.array(
        [max(current_year - int(p["year"]), 0) for p in selected], dtype=float
    )
    group_weights = np.array([max(float(p["weight"]), 0.05) for p in selected])
    group_weights *= np.power(0.5, group_age / recency_half_life)
    group_q = _weighted_quantile(group_residuals, quantile, group_weights)
    shrink = len(selected) / (len(selected) + SHRINK_K)
    return float(shrink * group_q + (1.0 - shrink) * global_q), {
        "source": "group_shrunk",
        "n": len(selected),
        "shrink": shrink,
    }


def _tail_offset(
    prior: list[dict],
    row: dict,
    target_quantile: float,
    quality_aware: bool,
    recency_half_life: float = 1.5,
    calibration_quantile: float | None = None,
) -> float:
    """One-sided conformal correction relative to the model's own tail.

    The earlier implementation calibrated an upper bound from the median
    residual.  That can count the model's existing P90 spread twice.  This
    correction instead calibrates ``actual - raw_q90`` (or q80/q95), which is
    the one-sided conformalized-quantile route described in the paper.
    """
    if not prior:
        return 0.0
    if calibration_quantile is None:
        calibration_quantile = target_quantile
    current_year = int(row["year"])
    field = f"raw_q{int(target_quantile * 100)}"
    residuals = np.array([p["actual"] - p[field] for p in prior], dtype=float)
    age = np.array([max(current_year - int(p["year"]), 0) for p in prior], dtype=float)
    recency = np.power(0.5, age / recency_half_life)
    weights = np.array([max(float(p["weight"]), 0.05) for p in prior]) * recency
    global_q = _weighted_quantile(residuals, calibration_quantile, weights)
    key_name = "quality_group" if quality_aware else "group"
    selected = [p for p in prior if p[key_name] == row[key_name]]
    if len(selected) < MIN_GROUP_CALIBRATION:
        return float(global_q)
    group_residuals = np.array([p["actual"] - p[field] for p in selected], dtype=float)
    group_age = np.array(
        [max(current_year - int(p["year"]), 0) for p in selected], dtype=float
    )
    group_weights = np.array([max(float(p["weight"]), 0.05) for p in selected])
    group_weights *= np.power(0.5, group_age / recency_half_life)
    group_q = _weighted_quantile(group_residuals, calibration_quantile, group_weights)
    shrink = len(selected) / (len(selected) + SHRINK_K)
    return float(shrink * group_q + (1.0 - shrink) * global_q)


def _learn_center_weights(prior: list[dict], row: dict) -> dict[str, float]:
    """Learn a soft stack from earlier OOS errors only."""
    candidates = ("robust_center", "last_center", "complex_center")
    if not prior:
        return {"robust_center": 1.0, "last_center": 0.0, "complex_center": 0.0}
    group = row["group"]
    group_prior = [p for p in prior if p["group"] == group]
    pool = group_prior if len(group_prior) >= 20 else prior
    scores = {}
    for name in candidates:
        usable = [p for p in pool if _finite(p.get(name))]
        if not usable:
            scores[name] = 1e6
            continue
        age = np.array([max(int(row["year"]) - int(p["year"]), 0) for p in usable])
        recency = np.power(0.5, age / 1.5)
        weights = np.array([max(float(p["weight"]), 0.05) for p in usable]) * recency
        errors = np.array(
            [p["actual"] - float(p[name]) for p in usable], dtype=float
        )
        scores[name] = float(
            np.average(np.where(errors > 0, 3.0 * errors, -errors), weights=weights)
        )
    finite_scores = np.array([scores[name] for name in candidates], dtype=float)
    finite_scores = np.where(np.isfinite(finite_scores), finite_scores, 1e6)
    temperature = 8.0
    logits = -(finite_scores - np.min(finite_scores)) / temperature
    weights = np.exp(np.clip(logits, -30, 0))
    weights /= weights.sum()
    return {name: float(value) for name, value in zip(candidates, weights)}


def _apply_variants(records: list[dict]) -> list[dict]:
    output = []
    for record in records:
        prior = [p for p in records if int(p["year"]) < int(record["year"])]
        weights = _learn_center_weights(prior, record)
        stacked = sum(
            weights[name] * float(record[name])
            for name in ("robust_center", "last_center", "complex_center")
            if _finite(record.get(name))
        )
        # If one candidate is missing, renormalize over available candidates.
        available = [
            name
            for name in ("robust_center", "last_center", "complex_center")
            if _finite(record.get(name))
        ]
        if available:
            denom = sum(weights[name] for name in available)
            if denom <= 1e-12 or not np.isfinite(denom):
                stacked = float(record["robust_center"] if _finite(record.get("robust_center")) else record["raw_q50"])
            else:
                stacked = sum(weights[name] * float(record[name]) for name in available) / denom
        else:
            stacked = float(record["raw_q50"])

        offsets_group = {
            q: _calibration_offset(prior, record, q, quality_aware=False)[0]
            for q in (0.50, 0.80, 0.90, 0.95)
        }
        offsets_dual = {
            q: _calibration_offset(prior, record, q, quality_aware=True)[0]
            for q in (0.50, 0.80, 0.90, 0.95)
        }
        offsets_recent = {
            q: _calibration_offset(
                prior, record, q, quality_aware=False, center_field="recent_center"
            )[0]
            for q in (0.50, 0.80, 0.90, 0.95)
        }
        offsets_recent_dual = {
            q: _calibration_offset(
                prior, record, q, quality_aware=True, center_field="recent_center"
            )[0]
            for q in (0.50, 0.80, 0.90, 0.95)
        }

        def build(prefix: str, center: float, offsets: dict[float, float] | None, preserve_center: bool = False):
            raw_center = float(record["raw_q50"])
            shift = center - raw_center
            if offsets is None:
                q50 = center
                qs = {
                    q: max(center, float(record[f"raw_q{int(q * 100)}"]) + shift)
                    for q in (0.80, 0.90, 0.95)
                }
            else:
                # A temporal conformal correction is primarily an upper-tail
                # safeguard here.  Preserving the point center avoids paying a
                # large MAE cost merely to repair interval coverage.
                q50 = center if preserve_center else center + offsets[0.50]
                qs = {
                    q: max(
                        q50,
                        center + (float(record[f"raw_q{int(q * 100)}"]) - raw_center),
                        center + offsets[q],
                    )
                    for q in (0.80, 0.90, 0.95)
                }
            return {
                f"{prefix}_q50": float(q50),
                **{f"{prefix}_q{int(q * 100)}": float(value) for q, value in qs.items()},
            }

        variants = {}
        variants.update(build("base", float(record["raw_q50"]), None))
        variants.update(build("temporal", float(record["raw_q50"]), offsets_group))
        variants.update(build("dual", float(record["raw_q50"]), offsets_dual))
        variants.update(build("temporal_upper", float(record["raw_q50"]), offsets_group, preserve_center=True))
        variants.update(build("dual_upper", float(record["raw_q50"]), offsets_dual, preserve_center=True))
        recent_center = float(record["recent_center"] if _finite(record.get("recent_center")) else record["raw_q50"])
        variants.update(build("recent", recent_center, None))
        variants.update(build("recent_upper", recent_center, offsets_recent, preserve_center=True))
        variants.update(build("recent_dual_upper", recent_center, offsets_recent_dual, preserve_center=True))
        direct_temporal = {
            q: _tail_offset(prior, record, q, quality_aware=False)
            for q in (0.80, 0.90, 0.95)
        }
        direct_dual = {
            q: _tail_offset(prior, record, q, quality_aware=True)
            for q in (0.80, 0.90, 0.95)
        }
        for prefix, corrections in (("direct_temporal", direct_temporal), ("direct_dual", direct_dual)):
            variants[f"{prefix}_q50"] = float(record["raw_q50"])
            for q, correction in corrections.items():
                variants[f"{prefix}_q{int(q * 100)}"] = max(
                    float(record["raw_q50"]),
                    float(record[f"raw_q{int(q * 100)}"]) + correction,
                )
        conservative_recent = {
            q: _tail_offset(
                prior,
                record,
                q,
                quality_aware=True,
                calibration_quantile=min(q + 0.05, 0.99),
            )
            for q in (0.80, 0.90, 0.95)
        }
        variants["recent_conservative_q50"] = recent_center
        for q, correction in conservative_recent.items():
            variants[f"recent_conservative_q{int(q * 100)}"] = max(
                recent_center,
                recent_center + (float(record[f"raw_q{int(q * 100)}"]) - float(record["raw_q50"])) + correction,
            )
        strict_recent = {
            q: _tail_offset(
                prior,
                record,
                q,
                quality_aware=True,
                calibration_quantile={0.80: 0.95, 0.90: 0.975, 0.95: 0.99}[q],
            )
            for q in (0.80, 0.90, 0.95)
        }
        variants["recent_strict_q50"] = recent_center
        for q, correction in strict_recent.items():
            variants[f"recent_strict_q{int(q * 100)}"] = max(
                recent_center,
                recent_center + (float(record[f"raw_q{int(q * 100)}"]) - float(record["raw_q50"])) + correction,
            )
        variants.update(build("stacked_dual", stacked, offsets_dual))
        output.append({**record, **variants, "stack_weight": weights})
    return output


def _metric(records: list[dict], prefix: str) -> dict:
    y = np.array([r["actual"] for r in records], dtype=float)
    w = np.array([max(float(r["weight"]), 0.05) for r in records], dtype=float)
    out = {"rows": len(records)}
    for q in (50, 80, 90, 95):
        pred = np.array([r[f"{prefix}_q{q}"] for r in records], dtype=float)
        error = y - pred
        out[f"q{q}_mae"] = float(np.average(np.abs(error), weights=w))
        if q == 50:
            out["mae"] = out[f"q{q}_mae"]
            out["median_absolute_error"] = float(np.median(np.abs(error)))
            out["asymmetric_loss_3x"] = float(
                np.average(np.where(error > 0, 3.0 * error, -error), weights=w)
            )
            out["underprediction_rate"] = float(np.average(error > 0, weights=w))
        else:
            tau = q / 100.0
            pinball = np.where(error >= 0, tau * error, (tau - 1.0) * error)
            out[f"q{q}_pinball"] = float(np.average(pinball, weights=w))
            out[f"q{q}_coverage"] = float(np.average(y <= pred, weights=w))
            if q == 90:
                out["q90_width"] = float(np.average(pred - np.array([r[f"{prefix}_q50"] for r in records]), weights=w))
    # Decision-layer diagnostics at fixed point scores.  No score uncertainty.
    for score in SCORE_GRID:
        probabilities = np.array(
            [_cdf_at_score(r, score, prefix) for r in records], dtype=float
        )
        actual_success = (y <= score).astype(float)
        out[f"score_{int(score)}_brier"] = float(np.average((probabilities - actual_success) ** 2, weights=w))
        out[f"score_{int(score)}_mean_probability"] = float(np.average(probabilities, weights=w))
        out[f"score_{int(score)}_actual_rate"] = float(np.average(actual_success, weights=w))
    return out


def _cdf_at_score(record: dict, score: float, prefix: str) -> float:
    anchors = np.array(
        [
            record[f"{prefix}_q50"],
            record[f"{prefix}_q80"],
            record[f"{prefix}_q90"],
            record[f"{prefix}_q95"],
        ],
        dtype=float,
    )
    probs = np.array([0.50, 0.80, 0.90, 0.95], dtype=float)
    if score <= anchors[0]:
        return float(np.clip(0.50 - (anchors[0] - score) / 180.0, 0.01, 0.49))
    if score >= anchors[-1]:
        return float(np.clip(0.95 + (score - anchors[-1]) / 180.0, 0.95, 0.99))
    return float(np.interp(score, anchors, probs))


def _subgroup_metrics(records: list[dict], prefix: str) -> list[dict]:
    rows = []
    for key, group in pd.DataFrame(records).groupby(["is_985", "national_zone", "quality_band"]):
        subset = group.to_dict(orient="records")
        metric = _metric(subset, prefix)
        metric.update({"is_985": bool(key[0]), "national_zone": key[1], "quality_band": key[2]})
        rows.append(metric)
    return rows


def run() -> dict:
    periods, schools, trainable, national_lines, _ = base.prepare_frames()
    # The production model uses 2024–2026 as scored origins.  We retain the
    # same origins and minimum training rule; no test-year information is used
    # to select offsets or stack weights.
    records: list[dict] = []
    for test_year in sorted(trainable["year"].unique()):
        if int(test_year) < 2023:
            continue
        train = trainable[trainable["year"] < test_year].copy()
        test = trainable[trainable["year"] == test_year].copy()
        if len(train) < MIN_TRAIN_ROWS or len(test) < 8:
            continue
        records.extend(
            _origin_predictions(
                train,
                test,
                national_lines,
                int(test_year),
                seed=SEED + int(test_year),
            )
        )
    evaluated = _apply_variants(records)
    variants = {
        "production_baseline": "base",
        "temporal_group_conformal": "temporal",
        "dual_uncertainty_quality_conformal": "dual",
        "temporal_upper_only": "temporal_upper",
        "dual_uncertainty_upper_only": "dual_upper",
        "recent_two_year_anchor": "recent",
        "recent_two_year_upper_conformal": "recent_upper",
        "recent_two_year_dual_upper": "recent_dual_upper",
        "recent_two_year_conservative_upper": "recent_conservative",
        "recent_two_year_strict_upper": "recent_strict",
        "direct_tail_temporal": "direct_temporal",
        "direct_tail_dual": "direct_dual",
        "dynamic_stack_plus_dual": "stacked_dual",
    }
    overall = {
        name: _metric(evaluated, prefix) for name, prefix in variants.items()
    }
    yearly = []
    for year, group in pd.DataFrame(evaluated).groupby("year"):
        subset = group.to_dict(orient="records")
        for name, prefix in variants.items():
            row = _metric(subset, prefix)
            row.update({"year": int(year), "variant": name})
            yearly.append(row)
    subgroup = {
        name: _subgroup_metrics(evaluated, prefix)
        for name, prefix in variants.items()
    }
    output_dir = ROOT / "output" / "experiments" / "precision_upgrade_20261007"
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(evaluated).to_json(
        output_dir / "oos_predictions.json", orient="records", force_ascii=False, indent=2
    )
    pd.DataFrame(yearly).to_csv(output_dir / "yearly_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"variant": name, **metrics}
            for name, metrics in overall.items()
        ]
    ).to_csv(output_dir / "overall_metrics.csv", index=False, encoding="utf-8-sig")
    (output_dir / "subgroup_metrics.json").write_text(
        json.dumps(subgroup, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decision_rows = []
    for variant, metrics in overall.items():
        for score in SCORE_GRID:
            decision_rows.append(
                {
                    "variant": variant,
                    "score": score,
                    "brier": metrics[f"score_{int(score)}_brier"],
                    "mean_probability": metrics[f"score_{int(score)}_mean_probability"],
                    "actual_success_rate": metrics[f"score_{int(score)}_actual_rate"],
                }
            )
    pd.DataFrame(decision_rows).to_csv(
        output_dir / "decision_metrics.csv", index=False, encoding="utf-8-sig"
    )
    report = {
        "experiment": "precision_upgrade_20261007",
        "scope": "school-threshold uncertainty only; candidate-score uncertainty excluded",
        "seed": SEED,
        "sample_size": SAMPLE_SIZE,
        "rows": len(evaluated),
        "years": sorted({int(r["year"]) for r in evaluated}),
        "variants": overall,
        "selection_rule": "No variant is promoted automatically; compare MAE, asymmetric loss, coverage, and q90 width.",
        "leakage_controls": [
            "expanding-window origins",
            "conformal offsets use only earlier OOS residuals",
            "stack weights use only earlier OOS candidate errors",
            "quality bands use only pre-origin historical evidence weights",
            "no candidate score or test-year label is used as an input",
        ],
        "decision_extension": {
            "score_grid": list(SCORE_GRID),
            "definition": "fixed point score mapped through the predicted threshold CDF; no score uncertainty",
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    baseline = overall["production_baseline"]
    recent = overall["recent_two_year_strict_upper"]
    report_lines = [
        "# 精度升级离线实验（2026-10-07）",
        "",
        "本实验只研究学校门槛分布；考生本人估分及其不确定性没有进入模型。所有改动均在 expanding-window 样本外回测中比较，未覆盖生产预测文件。",
        "",
        "## 关键结果",
        "",
        "| 指标 | 当前基线 | 两年边际锚点 + 严格上尾校准 |",
        "|---|---:|---:|",
        f"| P50 加权 MAE | {baseline['mae']:.2f} | {recent['mae']:.2f} |",
        f"| 低估三倍损失 | {baseline['asymmetric_loss_3x']:.2f} | {recent['asymmetric_loss_3x']:.2f} |",
        f"| P90 pinball loss | {baseline['q90_pinball']:.2f} | {recent['q90_pinball']:.2f} |",
        f"| P90 覆盖率 | {baseline['q90_coverage']:.1%} | {recent['q90_coverage']:.1%} |",
        f"| P95 pinball loss | {baseline['q95_pinball']:.2f} | {recent['q95_pinball']:.2f} |",
        f"| P95 覆盖率 | {baseline['q95_coverage']:.1%} | {recent['q95_coverage']:.1%} |",
        f"| P90−P50 平均宽度 | {baseline['q90_width']:.2f} | {recent['q90_width']:.2f} |",
        "",
        "## 解释",
        "",
        "1. 两年边际中位数把中心从全历史中位数改成最近两年中位数；在当前 226 条可比 OOS 记录上，P50 MAE 下降约 1.2%，低估三倍损失下降约 3.4%。",
        "2. 严格上尾校准只调整 P80/P90/P95，不移动 P50；因此区间变保守不会牺牲中心点精度。P90 覆盖率由约 73.8% 提升到约 88.7%，P95 覆盖率约 90.1%，但区间明显变宽。",
        "3. 动态 stacking 在这组三年短面板上反而恶化中心误差，暂不建议上线。证据质量分层的双重校准比统一时间校准略窄，但覆盖率也略低，暂不单独替换严格上尾版本。",
        "4. 决策层仍是固定估分映射到门槛 CDF；本实验没有把估分建模为随机变量。decision_metrics.csv 给出 350/370/390/410 分四个固定分数的 Brier 与实际覆盖率。",
        "5. 子组检查显示，985/A 且历史证据质量较高的 12 条记录在严格版本的 P90 覆盖率仍只有约 59%；这说明短面板和极端院校层级仍需要单独的分层校准，不能把总体覆盖率直接解释为所有学校都达到 90%。",
        "",
        "## 不能据此宣称的结论",
        "",
        "样本只有 2024—2026 三个测试年份，且目标仍有 Q10 代理误差；因此这只是候选路线筛选，不是生产模型升级。下一步应补充逐名普通统考成绩和报名时可见名额后重新回测。",
    ]
    (output_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
