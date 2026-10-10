"""Evaluate the frozen proxy model and an exact-label update on true Q10 rows.

The comparison is restricted to the same school-year rows with reconciled
candidate-level labels.  It does not overwrite the frozen 2027 baseline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from candidate_score_layer import exact_q10_by_program, load_candidate_scores


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-backtest",
        type=Path,
        default=ROOT / "data" / "processed" / "rolling_backtest.csv",
    )
    parser.add_argument("--enhanced-backtest", type=Path, required=True)
    parser.add_argument(
        "--program-year",
        type=Path,
        default=ROOT / "data" / "processed" / "program_year.csv",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def interval_score(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray, alpha: float) -> np.ndarray:
    return (
        upper
        - lower
        + (2.0 / alpha) * (lower - actual) * (actual < lower)
        + (2.0 / alpha) * (actual - upper) * (actual > upper)
    )


def metrics(frame: pd.DataFrame, prefix: str) -> dict:
    actual = frame["q10_exact"].to_numpy(float)
    q50 = frame[f"{prefix}_q50"].to_numpy(float)
    error = actual - q50
    result = {
        "n": int(len(frame)),
        "mae": float(np.mean(np.abs(error))),
        "median_ae": float(np.median(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias_actual_minus_prediction": float(np.mean(error)),
    }
    for q in (80, 90, 95):
        pred = frame[f"{prefix}_q{q}"].to_numpy(float)
        result[f"q{q}_coverage"] = float(np.mean(actual <= pred))
        result[f"q{q}_mean_width"] = float(np.mean(pred - q50))
    result["wis_proxy"] = float(
        np.mean(
            np.abs(error)
            + 0.10
            * interval_score(
                actual,
                frame[f"{prefix}_q10"].to_numpy(float),
                frame[f"{prefix}_q90"].to_numpy(float),
                0.20,
            )
            + 0.05
            * interval_score(
                actual,
                frame[f"{prefix}_q05"].to_numpy(float),
                frame[f"{prefix}_q95"].to_numpy(float),
                0.10,
            )
        )
    )
    return result


def year_block_ci(frame: pd.DataFrame, draws: int = 10000) -> dict:
    years = np.array(sorted(frame["year"].unique()), dtype=int)
    if len(years) < 2:
        return {"estimate": None, "p05": None, "p95": None, "years": years.tolist()}
    frame = frame.copy()
    frame["baseline_ae"] = (frame["q10_exact"] - frame["baseline_q50"]).abs()
    frame["enhanced_ae"] = (frame["q10_exact"] - frame["enhanced_q50"]).abs()
    by_year = frame.groupby("year")[["baseline_ae", "enhanced_ae"]].mean()
    difference = by_year["enhanced_ae"] - by_year["baseline_ae"]
    rng = np.random.default_rng(20261009)
    sampled = rng.integers(0, len(difference), size=(draws, len(difference)))
    values = difference.to_numpy(float)[sampled].mean(axis=1)
    return {
        "estimate": float(difference.mean()),
        "p05": float(np.quantile(values, 0.05)),
        "p95": float(np.quantile(values, 0.95)),
        "years": years.tolist(),
        "interpretation": "enhanced MAE minus frozen-baseline MAE; negative favours the exact-label update",
    }


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    exact = exact_q10_by_program(load_candidate_scores())
    baseline = read_csv(args.baseline_backtest)
    enhanced = read_csv(args.enhanced_backtest)
    quantile_columns = ["pred_q05", "pred_q10", "pred_q20", "pred_q50", "pred_q80", "pred_q90", "pred_q95"]
    baseline = baseline[["school", "year", *quantile_columns]].rename(
        columns={column: column.replace("pred_", "baseline_") for column in quantile_columns}
    )
    enhanced = enhanced[["school", "year", *quantile_columns]].rename(
        columns={column: column.replace("pred_", "enhanced_") for column in quantile_columns}
    )
    paired = exact.merge(baseline, on=["school", "year"], how="inner").merge(
        enhanced, on=["school", "year"], how="inner"
    )
    paired["baseline_error"] = paired["q10_exact"] - paired["baseline_q50"]
    paired["enhanced_error"] = paired["q10_exact"] - paired["enhanced_q50"]
    paired.to_csv(output_dir / "paired_exact_backtest.csv", index=False, encoding="utf-8-sig")

    program = read_csv(args.program_year)
    proxy = exact.merge(
        program[["school", "year", "q10_value", "q10_method", "q10_weight"]],
        on=["school", "year"],
        how="left",
    )
    proxy = proxy[proxy["q10_value"].notna()].copy()
    proxy["exact_minus_proxy"] = proxy["q10_exact"] - proxy["q10_value"]
    grouped = []
    for method, group in proxy.groupby("q10_method"):
        error = group["exact_minus_proxy"].to_numpy(float)
        grouped.append(
            {
                "q10_method": method,
                "n": int(len(group)),
                "mean_bias_exact_minus_proxy": float(np.mean(error)),
                "median_bias_exact_minus_proxy": float(np.median(error)),
                "mae_proxy_to_exact": float(np.mean(np.abs(error))),
                "rmse_proxy_to_exact": float(np.sqrt(np.mean(error**2))),
                "error_sd": float(np.std(error, ddof=1)) if len(error) > 1 else None,
                "p05_error": float(np.quantile(error, 0.05)),
                "p95_error": float(np.quantile(error, 0.95)),
            }
        )
    pd.DataFrame(grouped).to_csv(output_dir / "proxy_error_calibration.csv", index=False, encoding="utf-8-sig")
    proxy.to_csv(output_dir / "exact_proxy_pairs.csv", index=False, encoding="utf-8-sig")

    summary = {
        "exact_program_years_total": int(len(exact)),
        "exact_candidate_rows": int(exact["candidate_n"].sum()) if len(exact) else 0,
        "exact_backtest_rows": int(len(paired)),
        "exact_backtest_years": sorted(int(year) for year in paired["year"].unique()),
        "frozen_baseline_on_exact_labels": metrics(paired, "baseline") if len(paired) else {},
        "enhanced_model_on_exact_labels": metrics(paired, "enhanced") if len(paired) else {},
        "paired_year_block_mae_difference": year_block_ci(paired) if len(paired) else {},
        "proxy_pair_rows": int(len(proxy)),
        "bootstrap_sampling_sd": {
            "median": float(exact["q10_bootstrap_sd"].median()) if len(exact) else None,
            "p90": float(exact["q10_bootstrap_sd"].quantile(0.90)) if len(exact) else None,
            "max": float(exact["q10_bootstrap_sd"].max()) if len(exact) else None,
        },
        "guardrail": (
            "The enhanced model is a post-freeze retrospective experiment. It does not replace the frozen "
            "2027 forecast unless a separately versioned release is created before outcomes are known."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
