"""Rolling backtest for the registration-time quota feature.

This deliberately compares three information sets:

* ``base``: the current production feature set before quota data;
* ``strict_quota``: only official records published before formal registration;
* ``registration_window``: the same table with same-day registration-window
  records allowed as a sensitivity analysis, never as the production default.

The script reports the result but does not promote a feature automatically.
Promotion requires both a useful backtest change and enough out-of-time
coverage; sparse public quota observations must not be rewarded for overfit.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

import train_model as tm
from quota_features import load_quota_events


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "experiments" / "quota_features_20261007"


def _snapshot_rng():
    return copy.deepcopy(tm.RNG.bit_generator.state)


def _restore_rng(state):
    # The model functions retain the original RNG object in their default
    # arguments, so restore its state instead of rebinding the global name.
    tm.RNG.bit_generator.state = copy.deepcopy(state)


def run_variant(name: str, features: list[str], quota_events: pd.DataFrame, rng_state) -> dict:
    _restore_rng(rng_state)
    tm.NUMERIC_FEATURES = list(features)
    periods, schools, trainable, national_lines, _ = tm.prepare_frames(quota_events=quota_events)
    backtests = tm.rolling_backtest(trainable, national_lines)
    metrics = tm.backtest_metrics(backtests)
    coverage_rows = [row for row in backtests if row.get("quota_missing", 1) == 0]
    metrics["quota_rows_in_backtest"] = len(coverage_rows)
    metrics["quota_backtest_coverage"] = round(len(coverage_rows) / len(backtests), 4) if backtests else 0.0
    metrics["quota_schools_in_backtest"] = sorted({row["school"] for row in coverage_rows})
    return {
        "name": name,
        "features": list(features),
        "metrics": metrics,
        "quota_event_rows": int(len(quota_events)),
        "quota_event_schools": sorted(quota_events["school"].unique().tolist()) if not quota_events.empty else [],
    }


def main() -> int:
    base = list(tm.BASE_NUMERIC_FEATURES)
    quota = base + list(tm.QUOTA_NUMERIC_FEATURES)
    strict = load_quota_events(strict=True)
    window = load_quota_events(strict=True, include_registration_window=True)
    rng_state = _snapshot_rng()

    results = [
        run_variant("base", base, strict, rng_state),
        run_variant("strict_quota", quota, strict, rng_state),
        run_variant("registration_window_sensitivity", quota, window, rng_state),
    ]
    baseline = results[0]["metrics"]
    for result in results[1:]:
        metrics = result["metrics"]
        metrics["delta_mae_vs_base"] = round(metrics["mae"] - baseline["mae"], 2)
        metrics["delta_asymmetric_loss_vs_base"] = round(
            metrics["asymmetric_loss_3x"] - baseline["asymmetric_loss_3x"], 2
        )
        metrics["delta_q90_coverage_vs_base"] = round(
            metrics["q90_coverage"] - baseline["q90_coverage"], 3
        )

    strict_metrics = results[1]["metrics"]
    useful_change = (
        strict_metrics.get("asymmetric_loss_3x", float("inf")) <= baseline.get("asymmetric_loss_3x", float("inf"))
        and strict_metrics.get("q90_coverage", 0.0) >= baseline.get("q90_coverage", 0.0) - 0.03
    )
    enough_coverage = strict_metrics.get("quota_backtest_coverage", 0.0) >= 0.10 and strict_metrics.get("quota_rows_in_backtest", 0) >= 20
    decision = {
        "strict_candidate_useful_on_current_backtest": bool(useful_change),
        "strict_candidate_has_enough_out_of_time_coverage": bool(enough_coverage),
        "production_decision": "candidate_only" if useful_change and enough_coverage else "do_not_promote_yet",
        "reason": "名额样本覆盖不足时，不因单次 MAE 改善而上线；先扩大跨学校、跨年份的严格报名时点样本。",
    }
    payload = {
        "run_date": "2026-10-07",
        "target": "025200 全日制；成绩不确定性不纳入；滚动预测仅使用目标年份之前信息",
        "results": results,
        "decision": decision,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for result in results:
        row = {"variant": result["name"], **result["metrics"]}
        row["quota_event_rows"] = result["quota_event_rows"]
        rows.append(row)
    pd.DataFrame(rows).to_csv(OUT / "comparison.csv", index=False, encoding="utf-8-sig")
    (OUT / "README.md").write_text(
        "# 报名时名额特征实验\n\n"
        "严格模型只使用正式报名开始前发布的官方名额；registration_window 仅作敏感性分析。\n\n"
        f"生产决策：**{decision['production_decision']}**。{decision['reason']}\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
