"""Build thesis figures from the audited candidate-level distribution experiment.

Every chart is a view of model inputs, validation results, or identified
uncertainty.  Candidate identifiers never enter the outputs: the public
figures contain only aggregates or empirical distribution functions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import PercentFormatter


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from candidate_score_layer import audited_candidate_pool, load_candidate_scores  # noqa: E402
from experiment_candidate_distribution import exact_candidate_rows  # noqa: E402


DEFAULT_EXPERIMENT = ROOT / "output" / "experiments" / "v5_hierarchical_distribution_20261009"
DEFAULT_SELECTION_EXPERIMENT = ROOT / "output" / "experiments" / "v5_retest_selection_20261009"
DEFAULT_EXACT_EXPERIMENT = ROOT / "output" / "experiments" / "v5_exact_labels_20261009" / "exact_evaluation"
DEFAULT_OUTPUT = ROOT / "paper" / "assets" / "v5"
PROBABILITIES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
INK = "#183153"
BLUE = "#2f6f9f"
TEAL = "#2a9d8f"
GOLD = "#e9c46a"
ORANGE = "#f4a261"
RED = "#d95d39"
MUTED = "#708090"
GRID = "#d9e2ec"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument(
        "--selection-experiment-dir", type=Path, default=DEFAULT_SELECTION_EXPERIMENT
    )
    parser.add_argument("--exact-experiment-dir", type=Path, default=DEFAULT_EXACT_EXPERIMENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def configure() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#a8b3c2",
            "axes.labelcolor": INK,
            "xtick.color": "#425466",
            "ytick.color": "#425466",
            "text.color": INK,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
            "axes.labelsize": 10,
        }
    )


def finish(fig: plt.Figure, output: Path, stem: str) -> None:
    fig.savefig(output / f"{stem}.png", dpi=240, bbox_inches="tight", facecolor="white")
    fig.savefig(output / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def weighted_cdf(values: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(values)
    values = values[order]
    weights = weights[order].astype(float)
    weights /= weights.sum()
    return values, np.cumsum(weights)


def weighted_quantile(values: np.ndarray, probability: float, weights: np.ndarray) -> float:
    x, cdf = weighted_cdf(values, weights)
    return float(np.interp(probability, cdf, x))


def candidate_weights(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    group = frame.groupby(["school", "year"])["initial_score"].transform("size").to_numpy(float)
    school_years = frame[["school", "year"]].drop_duplicates().groupby("school").size()
    years_per_school = frame["school"].map(school_years).to_numpy(float)
    return {
        "录取考生等权": np.ones(len(frame), dtype=float),
        "校年等权": 1.0 / group,
        "院校等权": 1.0 / (group * years_per_school),
    }


def plot_source_audit(output: Path) -> dict:
    provenance = json.loads(
        (ROOT / "data" / "audit" / "provenance_coverage.json").read_text(encoding="utf-8")
    )
    bibliography = json.loads(
        (ROOT / "data" / "audit" / "public_source_bibliography.json").read_text(encoding="utf-8")
    )
    extraction = json.loads(
        (ROOT / "data" / "audit" / "candidate_score_extraction.json").read_text(encoding="utf-8")
    )
    field = provenance["program_year"]
    fig, axes = plt.subplots(1, 3, figsize=(12.2, 4.4), gridspec_kw={"width_ratios": [1, 1.08, 1.14]})

    coverage = float(field["field_url_coverage"])
    axes[0].barh([0], [1], color="#e7edf3", height=0.54)
    axes[0].barh([0], [coverage], color=TEAL, height=0.54)
    axes[0].text(
        coverage / 2,
        0,
        f"{field['field_values_with_public_url']:,} / {field['field_value_count']:,}\n{coverage:.2%}",
        ha="center",
        va="center",
        color="white",
        fontsize=10,
        weight="bold",
    )
    axes[0].set_xlim(0, 1)
    axes[0].xaxis.set_major_formatter(PercentFormatter(1.0))
    axes[0].set_yticks([])
    axes[0].set_xlabel("非空校年核心字段的 URL 覆盖率")
    axes[0].set_title("字段可追溯")

    reach = bibliography["reachability"]
    reach_labels = ["可访问", "未检查", "失效/受阻"]
    reach_values = [reach["reachable"], reach["not_checked"], reach["failed"]]
    left = 0
    for value, label, colour in zip(reach_values, reach_labels, [TEAL, GOLD, RED]):
        axes[1].barh([0], [value], left=left, color=colour, height=0.54)
        axes[1].text(left + value / 2, 0, f"{label}\n{value}", ha="center", va="center", fontsize=9, color="white" if colour != GOLD else INK, weight="bold")
        left += value
    axes[1].set_xlim(0, sum(reach_values))
    axes[1].set_yticks([])
    axes[1].set_xlabel("去重后的公开 URL 数")
    axes[1].set_title("940 个底层来源有独立目录")

    stages = ["名单图片", "可解析", "精确核对", "建模样本"]
    values = [
        extraction["images"],
        extraction["images_parsed"],
        extraction["validated_exact_programs"],
        extraction["model_eligible_exact_programs"],
    ]
    y = np.arange(len(stages))
    for yi, value, colour, alpha in zip(
        y, values, [BLUE, BLUE, TEAL, TEAL], [0.72, 0.92, 0.72, 0.95]
    ):
        axes[2].barh([yi], [value], color=colour, alpha=alpha)
    for yi, value in zip(y, values):
        axes[2].text(value + 7, yi, str(value), va="center", fontsize=9, color=INK)
    axes[2].set_yticks(y, stages)
    axes[2].invert_yaxis()
    axes[2].set_xlabel("证据单元数")
    axes[2].set_title("可解析不等于可作精确标签")
    for ax in axes:
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.grid(axis="x", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
    fig.suptitle("数据来源审计把“有来源、能访问、可解析、可核对”分开", fontsize=14, weight="bold", y=0.985)
    fig.subplots_adjust(top=0.80, wspace=0.35)
    finish(fig, output, "17_source_evidence_audit")
    return {
        "field_values": int(field["field_value_count"]),
        "field_values_with_public_url": int(field["field_values_with_public_url"]),
        "unique_public_urls": int(bibliography["unique_public_urls"]),
        "roster_images": int(extraction["images"]),
        "parsed_images": int(extraction["images_parsed"]),
        "validated_exact_programmes": int(extraction["validated_exact_programs"]),
        "model_eligible_programmes": int(extraction["model_eligible_exact_programs"]),
    }


def plot_nested_intervals(distributions: pd.DataFrame, output: Path) -> dict:
    latest = (
        distributions.sort_values(["school", "year"])
        .groupby("school", as_index=False)
        .tail(1)
        .sort_values("score_q50")
        .reset_index(drop=True)
    )
    maximum = 28
    if len(latest) > maximum:
        indices = np.unique(np.round(np.linspace(0, len(latest) - 1, maximum)).astype(int))
        view = latest.iloc[indices].copy()
    else:
        view = latest.copy()
    view = view.sort_values("score_q50").reset_index(drop=True)
    y = np.arange(len(view))
    fig, ax = plt.subplots(figsize=(10.8, max(7.0, 0.30 * len(view) + 1.8)))
    ax.hlines(y, view["score_q10"], view["score_q90"], color="#9fb3c8", lw=2.1, zorder=1)
    ax.hlines(y, view["score_q25"], view["score_q75"], color=BLUE, lw=6.2, zorder=2)
    ax.scatter(view["score_q50"], y, s=31, color=RED, edgecolor="white", linewidth=0.7, zorder=3)
    ax.scatter(view["score_q10"], y, s=18, color=TEAL, zorder=3)
    ax.set_yticks(y, [f"{row.school} ({int(row.year)})" for row in view.itertuples()])
    ax.set_xlabel("拟录取者初试总分")
    ax.set_title("同一院校内部有分布，院校之间又有位置差异")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    finish(fig, output, "19_within_between_school_intervals")
    return {"schools_total": int(len(latest)), "schools_displayed": int(len(view))}


def plot_evidence_utilisation(
    all_candidate_rows: pd.DataFrame,
    audited_pool: pd.DataFrame,
    retest_summary: dict,
    output: Path,
) -> dict:
    exact = int(audited_pool["candidate_evidence_tier"].eq("exact").sum())
    soft = int(audited_pool["candidate_evidence_tier"].eq("soft_roster").sum())
    diagnostic = int(len(all_candidate_rows) - exact - soft)
    input_audit = retest_summary["input_audit"]
    all_values = [
        int(input_audit["raw_admitted_rows"]),
        int(input_audit["raw_not_admitted_rows"]),
        int(input_audit["raw_unknown_outcome_rows"]),
    ]
    all_labels = ["已录取", "明确未录取", "状态未知/分数可用"]
    all_colours = [TEAL, RED, "#95a5b5"]
    admitted_values = [exact, soft, diagnostic]
    admitted_labels = ["精确标签", "降权软证据", "诊断/待复核"]
    admitted_colours = [TEAL, BLUE, "#b8c2cc"]
    fig, ax = plt.subplots(figsize=(11.4, 4.6))
    for y, values, labels, colours in (
        (1, all_values, all_labels, all_colours),
        (0, admitted_values, admitted_labels, admitted_colours),
    ):
        left = 0
        for value, label, colour in zip(values, labels, colours):
            ax.barh([y], [value], left=left, height=0.54, color=colour, edgecolor="white", lw=1.4)
            ax.text(
                left + value / 2,
                y,
                f"{label}\n{value:,}行",
                ha="center",
                va="center",
                color="white" if colour not in {"#b8c2cc", "#95a5b5"} else INK,
                fontsize=9.4,
                weight="bold",
            )
            left += value
    ax.set_xlim(0, max(sum(all_values), 1))
    ax.set_yticks([0, 1], ["已录取子集的证据层级", "全部可读成绩的结果状态"])
    ax.set_xlabel("OCR 抽取且保留审计链的初试总分行")
    ax.set_title("14,317 条成绩按信息强度分工，而不是作“通过/删除”二元筛选")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    finish(fig, output, "18_candidate_evidence_utilisation")
    return {
        "all_readable_rows": int(sum(all_values)),
        "admitted_rows": int(all_values[0]),
        "not_admitted_rows": int(all_values[1]),
        "unknown_outcome_rows": int(all_values[2]),
        "exact_rows": exact,
        "soft_rows": soft,
        "diagnostic_rows": diagnostic,
    }


def plot_selection_gradient(selection_experiment: Path, output: Path) -> dict:
    cohorts = pd.read_csv(
        selection_experiment / "qualified_selection_cohorts.csv", encoding="utf-8-sig"
    )
    curve = pd.read_csv(
        selection_experiment / "selection_decile_balanced_curve.csv", encoding="utf-8-sig"
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.0), gridspec_kw={"width_ratios": [1.15, 1]})
    x = curve["score_decile"].to_numpy(float)
    mean = curve["mean_admission_rate"].to_numpy(float)
    low = curve["p10_admission_rate"].to_numpy(float)
    high = curve["p90_admission_rate"].to_numpy(float)
    axes[0].fill_between(x, low, high, color=BLUE, alpha=0.14, label="校年间 P10–P90")
    axes[0].plot(x, mean, marker="o", lw=2.3, color=BLUE, label="校年等权均值")
    axes[0].set_xticks(np.arange(1, 11), [f"D{i}" for i in range(1, 11)])
    axes[0].set_ylim(0, 1.02)
    axes[0].yaxis.set_major_formatter(PercentFormatter(1.0))
    axes[0].set_xlabel("本校本年复试队列内的成绩十分位组")
    axes[0].set_ylabel("录取比例")
    axes[0].set_title("分数越高，录取比例通常越高")
    axes[0].grid(color=GRID, lw=0.8)
    axes[0].legend(frameon=False, loc="lower right")

    auc = cohorts["selection_auc"].dropna().to_numpy(float)
    bins = np.linspace(0.35, 1.0, 14)
    axes[1].hist(auc, bins=bins, color=TEAL, alpha=0.88, edgecolor="white")
    median = float(np.median(auc))
    axes[1].axvline(0.5, color="#9aa8b7", ls="--", lw=1.5, label="无排序信息 0.50")
    axes[1].axvline(median, color=RED, lw=2.2, label=f"中位数 {median:.2f}")
    axes[1].set_xlabel("校年内分数区分录取结果的 AUC")
    axes[1].set_ylabel("校年数")
    axes[1].set_title("但各校年区分强度并不相同")
    axes[1].grid(axis="y", color=GRID, lw=0.8)
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("复试队列中的选择关系：Q10 是风险指标，不是制度性录取线", fontsize=14, weight="bold", y=0.985)
    fig.subplots_adjust(top=0.83, wspace=0.28)
    finish(fig, output, "25_retest_selection_gradient")
    return {
        "qualified_school_years": int(len(cohorts)),
        "candidate_rows": int(cohorts["cohort_n"].sum()),
        "median_selection_auc": median,
        "median_admission_rate": float(cohorts["admission_rate"].median()),
    }


def plot_exact_label_upgrade(exact_experiment: Path, output: Path) -> dict:
    pairs = pd.read_csv(exact_experiment / "exact_proxy_pairs.csv", encoding="utf-8-sig")
    backtest = pd.read_csv(
        exact_experiment / "paired_exact_backtest.csv", encoding="utf-8-sig"
    )
    summary = json.loads((exact_experiment / "summary.json").read_text(encoding="utf-8"))
    methods = ["order_stat_interpolation", "minimum_only"]
    labels = ["顺序统计插值", "仅最低分"]
    values = [
        pairs.loc[pairs["q10_method"].eq(method), "exact_minus_proxy"].dropna().to_numpy(float)
        for method in methods
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.0), gridspec_kw={"width_ratios": [1, 1.18]})
    parts = axes[0].violinplot(values, positions=[1, 2], showmeans=False, showmedians=False, showextrema=False)
    for body, colour in zip(parts["bodies"], [BLUE, TEAL]):
        body.set_facecolor(colour)
        body.set_edgecolor("white")
        body.set_alpha(0.72)
    box = axes[0].boxplot(values, positions=[1, 2], widths=0.22, patch_artist=True, showfliers=False)
    for patch in box["boxes"]:
        patch.set_facecolor("white")
        patch.set_edgecolor(INK)
    for item in box["whiskers"] + box["caps"] + box["medians"]:
        item.set_color(INK)
    axes[0].axhline(0, color="#9aa8b7", ls="--", lw=1.2)
    axes[0].set_xticks([1, 2], [f"{label}\n(n={len(value)})" for label, value in zip(labels, values)])
    axes[0].set_ylabel("精确 Q10 − 代理 Q10（分）")
    axes[0].set_title("原始名单校准了两类代理误差")
    axes[0].grid(axis="y", color=GRID, lw=0.8)

    years = sorted(int(value) for value in backtest["year"].unique())
    baseline = [
        float(backtest.loc[backtest["year"].eq(year), "baseline_error"].abs().mean())
        for year in years
    ]
    enhanced = [
        float(backtest.loc[backtest["year"].eq(year), "enhanced_error"].abs().mean())
        for year in years
    ]
    baseline.append(float(summary["frozen_baseline_on_exact_labels"]["mae"]))
    enhanced.append(float(summary["enhanced_model_on_exact_labels"]["mae"]))
    x = np.arange(len(years) + 1)
    width = 0.34
    axes[1].bar(x - width / 2, baseline, width, color="#9aa8b7", label="冻结基线")
    axes[1].bar(x + width / 2, enhanced, width, color=RED, label="精确标签增强")
    axes[1].set_xticks(x, [str(year) for year in years] + ["总体"])
    axes[1].set_ylabel("精确 Q10 上的 MAE（分）")
    axes[1].set_title("总体误差下降，但年度结果并不一致")
    axes[1].grid(axis="y", color=GRID, lw=0.8)
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("逐人原始分数不仅替换代理，还能校准代理测量误差", fontsize=14, weight="bold", y=0.985)
    fig.subplots_adjust(top=0.83, wspace=0.30)
    finish(fig, output, "26_exact_label_proxy_and_backtest")
    return {
        "proxy_pairs": int(len(pairs)),
        "exact_backtest_rows": int(len(backtest)),
        "baseline_mae": float(summary["frozen_baseline_on_exact_labels"]["mae"]),
        "enhanced_mae": float(summary["enhanced_model_on_exact_labels"]["mae"]),
        "year_block_difference_p05": float(summary["paired_year_block_mae_difference"]["p05"]),
        "year_block_difference_p95": float(summary["paired_year_block_mae_difference"]["p95"]),
    }


def plot_national_mixtures(
    candidates: pd.DataFrame,
    audited_pool: pd.DataFrame,
    output: Path,
) -> dict:
    values = candidates["initial_score"].to_numpy(float)
    schemes = candidate_weights(candidates)
    colours = [BLUE, TEAL, RED]
    medians = {}
    fig, ax = plt.subplots(figsize=(10.5, 5.9))
    for (label, weights), colour in zip(schemes.items(), colours):
        x, cdf = weighted_cdf(values, weights)
        median = weighted_quantile(values, 0.50, weights)
        medians[label] = median
        ax.step(x, cdf, where="post", lw=2.3, label=f"{label}（P50={median:.0f}）", color=colour)
    audited_values = audited_pool["initial_score"].to_numpy(float)
    audited_count = audited_pool.groupby(["school", "year"])["initial_score"].transform("size").to_numpy(float)
    audited_weights = audited_pool["programme_evidence_weight"].to_numpy(float) / audited_count
    x, cdf = weighted_cdf(audited_values, audited_weights)
    median = weighted_quantile(audited_values, 0.50, audited_weights)
    medians["审计扩展软权重"] = median
    ax.step(x, cdf, where="post", lw=1.8, ls="--", label=f"审计扩展软权重（P50={median:.0f}）", color=ORANGE)
    ax.axhline(0.50, color="#9aa8b7", ls="--", lw=1)
    ax.set_xlabel("拟录取者初试总分")
    ax.set_ylabel("累积概率")
    ax.set_title("“全国分布”取决于抽样对象：考生、校年还是院校")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlim(max(250, np.quantile(values, 0.005) - 5), min(500, np.quantile(values, 0.995) + 5))
    ax.set_ylim(0, 1)
    ax.grid(color=GRID, lw=0.8)
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    finish(fig, output, "20_national_mixture_estimands")
    return {"medians": medians}


def plot_variance_decomposition(decomposition: dict, output: Path) -> dict:
    block = decomposition["three_level_school_balanced_variance"]
    shares = block["shares"]
    values = [
        shares["within_school_year_candidate"],
        shares["within_school_across_year"],
        shares["between_school"],
    ]
    labels = ["校年内个体差异", "同校跨年波动", "院校间差异"]
    colours = [BLUE, GOLD, RED]
    fig, ax = plt.subplots(figsize=(10.5, 3.6))
    left = 0.0
    for value, label, colour in zip(values, labels, colours):
        ax.barh([0], [value], left=left, height=0.42, color=colour, edgecolor="white", linewidth=1.5)
        ax.text(left + value / 2, 0, f"{label}\n{value:.1%}", ha="center", va="center", color="white" if colour != GOLD else INK, fontsize=10, weight="bold")
        left += value
    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("总方差份额（院校等权口径）")
    ax.set_title("三层方差分解：不能把个体行当成独立的预测年份")
    ax.spines[["top", "right", "left"]].set_visible(False)
    finish(fig, output, "21_three_level_variance_decomposition")
    return {label: float(value) for label, value in zip(labels, values)}


def plot_sampling_uncertainty(distributions: pd.DataFrame, output: Path) -> dict:
    frame = distributions.dropna(subset=["candidate_n", "q10_bootstrap_sd"]).copy()
    fig, ax = plt.subplots(figsize=(9.8, 5.8))
    years = sorted(frame["year"].unique())
    palette = plt.cm.viridis(np.linspace(0.12, 0.88, max(len(years), 2)))
    for year, colour in zip(years, palette):
        group = frame[frame["year"] == year]
        ax.scatter(group["candidate_n"], group["q10_bootstrap_sd"], s=35, alpha=0.72, color=colour, label=str(int(year)), edgecolor="white", linewidth=0.4)
    n_grid = np.linspace(max(10, frame["candidate_n"].min()), frame["candidate_n"].max(), 200)
    scale = float(np.median(frame["q10_bootstrap_sd"] * np.sqrt(frame["candidate_n"])))
    ax.plot(n_grid, scale / np.sqrt(n_grid), color=RED, lw=2.0, ls="--", label=r"参考线 $c/\sqrt{n}$")
    ax.set_xlabel("普通统考全日制拟录取样本量")
    ax.set_ylabel("Q10 bootstrap 标准差（分）")
    ax.set_title("精确名单也有抽样误差：小招生项目的 Q10 更不稳定")
    ax.grid(color=GRID, lw=0.8)
    ax.legend(frameon=False, ncol=min(4, len(years) + 1))
    ax.spines[["top", "right"]].set_visible(False)
    finish(fig, output, "22_q10_sampling_uncertainty")
    return {
        "school_years": int(len(frame)),
        "median_bootstrap_sd": float(frame["q10_bootstrap_sd"].median()),
        "p90_bootstrap_sd": float(frame["q10_bootstrap_sd"].quantile(0.90)),
    }


def plot_validation(outer: pd.DataFrame, summary: dict, output: Path) -> dict:
    years = sorted(int(year) for year in outer["year"].unique())
    anchor = []
    selected = []
    for year in years:
        block = outer[outer["year"] == year]
        anchor.append(float(np.mean(np.abs(block["score_q10"] - block["anchor_q10"]))))
        selected.append(float(np.mean(np.abs(block["score_q10"] - block["selected_q10"]))))
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 5.0), gridspec_kw={"width_ratios": [1.05, 1]})
    x = np.arange(len(years))
    axes[0].plot(x, anchor, marker="o", lw=2.2, color=INK, label="冻结稳健锚点")
    if np.allclose(anchor, selected):
        axes[0].text(
            0.03,
            0.06,
            "校正候选未通过预序护栏，\n最终预测与稳健锚点相同",
            transform=axes[0].transAxes,
            fontsize=9,
            color=RED,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "#fff5ef", "edgecolor": "#f3c4ae"},
        )
    else:
        axes[0].plot(x, selected, marker="o", lw=2.2, color=RED, label="预序选择校正")
    for index, value in enumerate(anchor):
        axes[0].annotate(
            f"{value:.1f}",
            (index, value),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=INK,
        )
    axes[0].set_xticks(x, years)
    axes[0].set_ylabel("Q10 MAE（分）")
    axes[0].set_title("严格时间外中心预测")
    axes[0].grid(axis="y", color=GRID, lw=0.8)
    axes[0].legend(frameon=False)
    axes[0].margins(y=0.16)

    metrics = summary["strict_outer"]["distribution_metrics"]
    coverage = metrics["candidate_coverage"]
    nominal = np.array(PROBABILITIES)
    observed = np.array([coverage[f"pred_q{int(probability * 100):02d}"] for probability in PROBABILITIES])
    axes[1].plot([0, 1], [0, 1], color="#9aa8b7", ls="--", lw=1.3, label="理想校准")
    axes[1].plot(nominal, observed, marker="o", color=BLUE, lw=2.2, label="学校-年等权实现率")
    axes[1].fill_between(nominal, nominal, observed, color=BLUE, alpha=0.10)
    axes[1].set_xlim(0, 1)
    axes[1].set_ylim(0, 1)
    axes[1].xaxis.set_major_formatter(PercentFormatter(1.0))
    axes[1].yaxis.set_major_formatter(PercentFormatter(1.0))
    axes[1].set_xlabel("名义分位水平")
    axes[1].set_ylabel("实现覆盖率")
    axes[1].set_title("完整分布的可靠性曲线")
    axes[1].grid(color=GRID, lw=0.8)
    axes[1].legend(frameon=False, loc="upper left")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("原始样本带来新信息，但新组件必须通过预序护栏才能晋级", fontsize=14, weight="bold", y=0.985)
    fig.subplots_adjust(top=0.84, wspace=0.28)
    finish(fig, output, "23_prequential_validation_and_reliability")
    return {
        "years": years,
        "anchor_mae": anchor,
        "selected_mae": selected,
        "mean_absolute_calibration_error": float(metrics["mean_absolute_calibration_error"]),
    }


def plot_shape_heatmap(distributions: pd.DataFrame, output: Path) -> dict:
    latest = (
        distributions.sort_values(["school", "year"])
        .groupby("school", as_index=False)
        .tail(1)
        .copy()
    )
    quantile_columns = [f"score_q{int(p * 100):02d}" for p in PROBABILITIES]
    offsets = latest[quantile_columns].sub(latest["score_q10"], axis=0)
    latest["shape_span"] = offsets["score_q90"] - offsets["score_q10"]
    latest = latest.sort_values("shape_span")
    maximum = 36
    if len(latest) > maximum:
        indices = np.unique(np.round(np.linspace(0, len(latest) - 1, maximum)).astype(int))
        latest = latest.iloc[indices]
        offsets = latest[quantile_columns].sub(latest["score_q10"], axis=0)
    else:
        offsets = latest[quantile_columns].sub(latest["score_q10"], axis=0)
    labels = [f"{school} ({int(year)})" for school, year in zip(latest["school"], latest["year"])]
    cmap = LinearSegmentedColormap.from_list("paper", ["#edf5fb", "#8ec1d6", "#2f6f9f", "#183153"])
    fig, ax = plt.subplots(figsize=(9.5, max(6.8, 0.24 * len(latest) + 1.8)))
    image = ax.imshow(offsets.to_numpy(float), aspect="auto", cmap=cmap, interpolation="nearest")
    ax.set_yticks(np.arange(len(latest)), labels)
    ax.set_xticks(np.arange(len(PROBABILITIES)), [f"Q{int(p * 100):02d}" for p in PROBABILITIES])
    ax.set_title("校年分布形状不完全相同：各分位点相对 Q10 的偏移")
    colourbar = fig.colorbar(image, ax=ax, pad=0.02)
    colourbar.set_label("相对 Q10 的分数差")
    ax.tick_params(axis="y", labelsize=8)
    finish(fig, output, "24_school_shape_heatmap")
    return {"schools_displayed": int(len(latest))}


def main() -> None:
    args = parse_args()
    experiment = args.experiment_dir.resolve()
    selection_experiment = args.selection_experiment_dir.resolve()
    exact_experiment = args.exact_experiment_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    configure()
    distributions = pd.read_csv(experiment / "candidate_distribution_summary.csv", encoding="utf-8-sig")
    outer = pd.read_csv(experiment / "strict_outer_predictions.csv", encoding="utf-8-sig")
    summary = json.loads((experiment / "summary.json").read_text(encoding="utf-8"))
    decomposition = json.loads((experiment / "national_distribution_decomposition.json").read_text(encoding="utf-8"))
    all_candidate_rows = load_candidate_scores()
    candidates = exact_candidate_rows(all_candidate_rows)
    audited_pool = audited_candidate_pool(all_candidate_rows)
    retest_summary = json.loads(
        (selection_experiment / "summary.json").read_text(encoding="utf-8")
    )
    manifest = {
        "source_experiment": str(experiment.relative_to(ROOT)).replace("\\", "/"),
        "scope": summary.get("scope", {}),
        "figures": {
            "17_source_evidence_audit": plot_source_audit(output),
            "18_candidate_evidence_utilisation": plot_evidence_utilisation(
                all_candidate_rows, audited_pool, retest_summary, output
            ),
            "19_within_between_school_intervals": plot_nested_intervals(distributions, output),
            "20_national_mixture_estimands": plot_national_mixtures(
                candidates, audited_pool, output
            ),
            "21_three_level_variance_decomposition": plot_variance_decomposition(decomposition, output),
            "22_q10_sampling_uncertainty": plot_sampling_uncertainty(distributions, output),
            "23_prequential_validation_and_reliability": plot_validation(outer, summary, output),
            "24_school_shape_heatmap": plot_shape_heatmap(distributions, output),
            "25_retest_selection_gradient": plot_selection_gradient(
                selection_experiment, output
            ),
            "26_exact_label_proxy_and_backtest": plot_exact_label_upgrade(
                exact_experiment, output
            ),
        },
        "privacy": "Figures contain only aggregates or empirical distribution functions; no candidate identifiers are emitted.",
    }
    (output / "distribution_figure_metrics.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
