"""Audit published V6 claims without refitting or changing any forecast.

This analysis verifies annual coverage counts, center drift, risk-scale
interpolation and raw/safety width heterogeneity. Figures are views of these
audited calculations, never decorative drawings or additional fitted models.
Only school-year aggregates are read; no candidate rows are accessed.
"""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "output/experiments/v6_statistical_inference_20261011"
OUT = ROOT / "output/experiments/v6_1_interpretation_20261011"
ASSETS = ROOT / "paper/assets/v6_1"


def risk_scale(row, scores):
    """Frozen seven-anchor display scale, not an independently calibrated CDF."""
    anchors = [row[f"q{q:02d}"] for q in (5, 10, 20, 50, 80, 90, 95)]
    if np.any(np.diff(anchors) <= 0):
        raise ValueError("Expected distinct ordered anchors for this example")
    return np.interp(scores, anchors, [.05, .1, .2, .5, .8, .9, .95])


def save_figure(fig, name):
    path = ASSETS / name
    fig.tight_layout()
    fig.savefig(path, metadata={"Date": "2026-10-11"}, bbox_inches="tight")
    # Matplotlib emits trailing spaces in SVG path lines; normalize only them.
    path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    forecast_path = ROOT / "app/data/forecast.json"
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    rows = pd.read_csv(EXP / "rolling_predictions.csv")
    published = pd.read_csv(EXP / "yearly_metrics.csv")
    annual = []
    for year, group in rows[rows.kind == "random_intercept"].groupby("year"):
        actual = group.actual.to_numpy()
        center = group.pred_q50.to_numpy()
        covered = int(np.sum(actual <= group.pred_q90.to_numpy()))
        record = {"year": int(year), "n": len(group), "covered": covered,
                  "coverage": covered / len(group),
                  "bias_actual_minus_prediction": float(np.mean(actual - center)),
                  "mae": float(np.mean(np.abs(actual - center))),
                  "mean_upper_width": float(np.mean(group.pred_q90 - group.pred_q50))}
        check = published[(published.kind == "random_intercept") & (published.year == year)].iloc[0]
        for field, column in (("coverage", "q90_coverage"), ("bias_actual_minus_prediction", "bias_actual_minus_prediction"), ("mae", "mae")):
            if not np.isclose(record[field], check[column], atol=1e-10, rtol=1e-10):
                raise AssertionError(f"Published V6 metric disagrees: {year} {field}")
        record["wis"] = float(check.wis)
        annual.append(record)
    raw = np.array([r["rawUpperWidth"] for r in forecast["predictions"]])
    safety = np.array([r["robustUpperWidth"] for r in forecast["predictions"]])
    example = next(r for r in forecast["predictions"] if r["school"] == "华东师范大学")
    query = np.arange(375, 406, 5)
    audit = {
        "version": "V6.1", "scope": "Interpretation audit only; no refitting, no new candidate forecast",
        "forecast_sha256": hashlib.sha256(forecast_path.read_bytes()).hexdigest(),
        "random_intercept_annual": annual,
        "pooled_coverage": sum(r["covered"] for r in annual) / sum(r["n"] for r in annual),
        "independent_calendar_origins": len(annual),
        "raw_width_cv_ddof0": float(np.std(raw) / np.mean(raw)),
        "safety_width_cv_ddof0": float(np.std(safety) / np.mean(safety)),
        "upper_width_guardrail": forecast["meta"]["upperWidthGuardrail"],
        "flagged_schools": [r["school"] for r in forecast["predictions"] if r["upperWidthStatus"] == "information_limited"],
        "example": {"school": example["school"], "raw_q90": example["rawQ90"], "safety_q90": example["q90"],
                    "risk_scale": {str(int(x)): float(v) for x, v in zip(query, risk_scale(example, query))}},
        "limitations": ["exact denotes empirical calculation within audited roster, not official-source infallibility",
                        "annual coverage proportions are not independent-binomial coverage guarantees",
                        "safety interpolation R(x) is not a verified CDF G(x)",
                        "frozen 2027 baseline exists; V6 candidates have retrospective outputs only"]}
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(annual).to_csv(OUT / "annual_coverage.csv", index=False)
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                        "axes.unicode_minus": False, "svg.fonttype": "none", "svg.hashsalt": "v6-1-interpretation",
                        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.5))
    years = [r["year"] for r in annual]
    coverage = [r["coverage"] * 100 for r in annual]
    axes[0].plot(years, coverage, "o-", color="#169c8d", linewidth=2)
    axes[0].axhline(90, color="#bf7837", linestyle="--", label="名义 90%（非保证）")
    for r in annual:
        axes[0].annotate(f'{r["covered"]}/{r["n"]}', (r["year"], r["coverage"]*100), xytext=(0, 10), textcoords="offset points", ha="center")
    axes[0].set(ylim=(70, 107), xticks=years, ylabel="P90 实际覆盖 / %", title="总体 50/54 ≠ 每年稳定校准")
    axes[0].legend(fontsize=8, loc="lower left")
    bias = [r["bias_actual_minus_prediction"] for r in annual]
    axes[1].bar(years, bias, width=.5, color=["#377aa9" if b < 0 else "#bf7837" for b in bias])
    axes[1].axhline(0, color="#8696a5", linewidth=1)
    for year, b in zip(years, bias):
        axes[1].text(year, b + (-.8 if b < 0 else .8), f"{b:+.2f}", ha="center", va="top" if b < 0 else "bottom")
    axes[1].set(xticks=years, ylim=(-18, 10), ylabel="实际 − 预测中心 / 分", title="覆盖变化须同时检查位置偏差")
    for ax in axes:
        ax.grid(axis="y", color="#e1e7ec", linewidth=.6)
        ax.set_axisbelow(True)
    save_figure(fig, "01_annual_coverage_and_bias.svg")
    fig, ax = plt.subplots(figsize=(8.5, 4))
    anchors = np.array([example[f"q{q:02d}"] for q in (5, 10, 20, 50, 80, 90, 95)])
    scores = np.linspace(anchors[0], anchors[-1], 240)
    ax.plot(scores, risk_scale(example, scores), color="#377aa9", linewidth=2)
    ax.scatter(anchors, [.05,.1,.2,.5,.8,.9,.95], color="#377aa9", edgecolor="white", zorder=3)
    ax.axhline(.9, color="#bf7837", linestyle="--", linewidth=1)
    ax.axvline(example["q90"], color="#bf7837", linestyle=":", linewidth=1)
    ax.annotate("安全 P90* 锚点\n不是经验证的 90% 概率", (example["q90"], .9), xytext=(anchors[0]+3, .94), fontsize=9,
                arrowprops={"arrowstyle": "->", "color": "#bf7837"}, color="#9c662f")
    ax.set(xlim=(scores[0], scores[-1]+2), ylim=(0, 1.08), xlabel="固定估分 / 分", ylabel="保守风险刻度 R(x)",
           title="华东师范大学：安全锚点插值不等于概率校准")
    ax.grid(color="#e1e7ec", linewidth=.6)
    save_figure(fig, "02_safety_risk_scale.svg")
    print(json.dumps({"coverage": audit["pooled_coverage"], "annual": annual,
                      "raw_cv": audit["raw_width_cv_ddof0"], "safety_cv": audit["safety_width_cv_ddof0"],
                      "flagged": audit["flagged_schools"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
