from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import train_model as base  # noqa: E402


def main():
    _, _, trainable, national_lines, _ = base.prepare_frames()
    rows = []
    for year in sorted(trainable["year"].unique()):
        train = trainable[trainable["year"] < year]
        test = trainable[trainable["year"] == year]
        for _, row in test.iterrows():
            history = train[train["school"] == row["school"]].sort_values("year")["margin_q10"].dropna().to_numpy(dtype=float)
            if not len(history):
                continue
            line = base.national_line_distribution(
                national_lines,
                int(year),
                row["national_zone"],
                size=1,
                rng=np.random.default_rng(1),
            )["mean"]
            weighted = np.power(0.5, np.arange(len(history) - 1, -1, -1) / 1.5)
            centers = {
                "all_median": np.median(history),
                "last2_median": np.median(history[-2:]),
                "last3_median": np.median(history[-3:]),
                "mean": np.mean(history),
                "recency_mean": np.average(history, weights=weighted),
                "blend25": 0.75 * np.median(history) + 0.25 * history[-1],
                "blend50": 0.50 * np.median(history) + 0.50 * history[-1],
                "last": history[-1],
            }
            for variant, margin in centers.items():
                error = float(row["q10_value"] - (line + margin))
                rows.append({"year": int(year), "variant": variant, "error": error, "weight": float(row["model_weight"])})
    frame = pd.DataFrame(rows)
    summary = []
    for variant, group in frame.groupby("variant"):
        error = group["error"].to_numpy(float)
        weight = group["weight"].to_numpy(float)
        summary.append({
            "variant": variant,
            "mae": np.average(np.abs(error), weights=weight),
            "asymmetric_loss_3x": np.average(np.where(error > 0, 3 * error, -error), weights=weight),
        })
    print(pd.DataFrame(summary).sort_values("mae").to_string(index=False))
    print("\\nYearly MAE")
    yearly = []
    for (year, variant), group in frame.groupby(["year", "variant"]):
        yearly.append({"year": year, "variant": variant, "mae": np.average(np.abs(group.error), weights=group.weight)})
    print(pd.DataFrame(yearly).pivot(index="variant", columns="year", values="mae").sort_values(2026).to_string())


if __name__ == "__main__":
    main()
