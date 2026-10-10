#!/usr/bin/env python3
"""Build reproducible analytical figures and tables for the V3 methods paper.

This program is deliberately part of the analysis pipeline rather than a
one-off drawing script.  It reads the same processed data and model artefacts
used by the public application, recomputes the paper's headline diagnostics,
and exports figures, a machine-readable summary, and the appendix forecast
table.  It can be rerun after any future data/model refresh.

Example
-------
python paper/scripts/build_paper_analysis.py \
  --repo-root . --output-dir paper/assets/v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch


INK = "#1f2933"
MUTED = "#66727f"
GRID = "#d8dee5"
BLUE = "#245a9b"
ORANGE = "#d97706"
GREEN = "#2f7d5b"
RED = "#b5473c"
PURPLE = "#7561a8"
LIGHT_BLUE = "#dbe8f6"
LIGHT_ORANGE = "#f6e7ce"
LIGHT_GREEN = "#dceee5"
LIGHT_RED = "#f3ddda"

FACTION_COLORS = {
    "纯贾": "#2f6f9f",
    "纯茆": "#d48134",
    "贾茆": "#4f8b62",
    "茆Pro": "#8a63a8",
    "贾茆Pro": "#b44d58",
    "待核实": "#7b8794",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root containing data/, app/, and paper/.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Figure/table directory (default: <repo>/paper/assets/v3).",
    )
    parser.add_argument(
        "--forecast-year",
        type=int,
        default=2027,
        help="Forecast year used in labels and output metadata.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def weighted_mean(values: Iterable[float], weights: Iterable[float]) -> float:
    v = np.asarray(list(values), dtype=float)
    w = np.asarray(list(weights), dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(v[mask], weights=w[mask]))


def weighted_quantile(
    values: Iterable[float], quantile: float, weights: Iterable[float] | None = None
) -> float:
    v = np.asarray(list(values), dtype=float)
    if weights is None:
        w = np.ones_like(v)
    else:
        w = np.asarray(list(weights), dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[mask], w[mask]
    if len(v) == 0:
        return float("nan")
    order = np.argsort(v)
    v, w = v[order], w[order]
    cdf = (np.cumsum(w) - 0.5 * w) / np.sum(w)
    return float(np.interp(quantile, cdf, v, left=v[0], right=v[-1]))


def configure_matplotlib() -> None:
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "Arial Unicode MS",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.color": INK,
            "ytick.color": INK,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "text.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.08,
            "svg.fonttype": "none",
            "svg.hashsalt": "applied-stat-risk-lab-v5",
            "pdf.fonttype": 42,
        }
    )


def finish(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(
        output_dir / f"{stem}.svg",
        format="svg",
        metadata={"Date": "2026-10-09"},
    )
    fig.savefig(output_dir / f"{stem}.png", format="png", dpi=220)
    plt.close(fig)


def figure_model_workflow(output_dir: Path) -> None:
    """Render the actual computation graph documented by the codebase."""

    fig, ax = plt.subplots(figsize=(12.4, 5.2))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 5.2)
    ax.axis("off")

    def box(x, y, w, h, title, lines, face, edge):
        patch = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.025,rounding_size=0.06",
            linewidth=1.1, edgecolor=edge, facecolor=face,
        )
        ax.add_patch(patch)
        ax.text(x + 0.12, y + h - 0.18, title, ha="left", va="top", fontsize=10.2, weight="bold")
        ax.text(x + 0.12, y + h - 0.55, "\n".join(lines), ha="left", va="top", fontsize=8.2, linespacing=1.45)
        return patch

    def arrow(x1, y1, x2, y2, label=None, rad=0.0):
        arr = FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=11,
            linewidth=1.0, color=MUTED,
            connectionstyle=f"arc3,rad={rad}",
        )
        ax.add_patch(arr)
        if label:
            ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.1, label, ha="center", va="bottom", fontsize=7.6, color=MUTED)

    box(0.1, 2.55, 2.15, 2.15, "① 报名前可见证据", [
        "招生简章与变更公告", "复试线与拟录取名单", "国家线与考试科目", "名额、学制及事件证据",
    ], "#eef3f8", BLUE)
    box(0.1, 0.35, 2.15, 1.55, "证据纪律", [
        "只使用报名截点前信息", "来源分级并保留原链接", "口径冲突进入人工复核",
    ], "#f7f8fa", MUTED)

    box(2.75, 2.55, 2.15, 2.15, "② 目标与权重", [
        "排除专项/非全/调剂", "构造录取初试分 Q10 代理", "证据权重 × 代理权重", "审计问题折减训练权重",
    ], "#eef7f2", GREEN)
    box(2.75, 0.35, 2.15, 1.55, "相对国家线建模", [
        "M = Q10 − 国家线", "减少公共政策波动", "保留学校间难度差异",
    ], "#f7faf8", GREEN)

    box(5.4, 2.55, 2.15, 2.15, "③ 中心候选与特征", [
        "严格滞后动态特征", "稳健边际/上一年锚点", "贝叶斯正则化分层近似", "梯度提升分位数回归",
    ], "#f4f0f8", PURPLE)
    box(5.4, 0.35, 2.15, 1.55, "逐年滚动选择", [
        "扩窗训练 → 下一年检验", "比较 MAE 与非对称损失", "复杂模型只在有增益时接管",
    ], "#faf8fc", PURPLE)

    box(8.05, 2.55, 2.15, 2.15, "④ 未来分布合成", [
        "中心 + 0.35×复杂形状", "国家线共同不确定性", "事件三情景或未知厚尾", "得到原始门槛样本分布",
    ], "#fbf3e8", ORANGE)
    box(8.05, 0.35, 2.15, 1.55, "跨年份稳健上界", [
        "每个预测年份单独算残差", "取最不利年份标准化分位", "学校特异误差尺度还原",
    ], "#fdf9f2", ORANGE)

    box(10.55, 2.55, 1.7, 2.15, "⑤ 决策输出", [
        "P50/P80/P90/P95", "个人估分覆盖概率", "冲/观察/稳/保标签", "分解、事件与证据说明",
    ], "#f8eeee", RED)
    box(10.55, 0.35, 1.7, 1.55, "边界", [
        "不是最终录取概率", "不含复试与单科线", "人工审核仍是必要环节",
    ], "#fcf7f6", RED)

    arrow(2.25, 3.63, 2.75, 3.63)
    arrow(4.9, 3.63, 5.4, 3.63)
    arrow(7.55, 3.63, 8.05, 3.63)
    arrow(10.2, 3.63, 10.55, 3.63)
    arrow(1.18, 2.55, 1.18, 1.9)
    arrow(3.83, 2.55, 3.83, 1.9)
    arrow(6.48, 2.55, 6.48, 1.9)
    arrow(9.13, 2.55, 9.13, 1.9)
    arrow(11.4, 2.55, 11.4, 1.9)
    arrow(2.25, 1.12, 2.75, 1.12, "限定口径")
    arrow(4.9, 1.12, 5.4, 1.12, "构造特征")
    arrow(7.55, 1.12, 8.05, 1.12, "选中心")
    arrow(10.2, 1.12, 10.55, 1.12, "原始分布 + 安全上界")

    ax.text(
        6.2, 5.05,
        "可复现计算图：每个箭头都对应代码中的数据变换或模型步骤",
        ha="center", va="top", fontsize=13,
    )
    fig.tight_layout(pad=0.4)
    finish(fig, output_dir, "00_model_workflow")


def annotate_bars(ax: plt.Axes, bars, fmt: str = "{:.0f}", pad: float = 2.0) -> None:
    for bar in bars:
        value = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + pad,
            fmt.format(value),
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=INK,
        )


def figure_data_audit(
    program: pd.DataFrame, output_dir: Path, exact_program_years: int = 0
) -> dict:
    counts = {
        "校年观测": int(len(program)),
        "有复试线": int(program["cutoff"].notna().sum()),
        "官方/官方二手复试线": int(
            program["cutoff_evidence_class"].isin(["official", "official_secondary"]).sum()
        ),
        "可构造Q10代理": int(program["q10_value"].notna().sum()),
        "逐名精确Q10": int(exact_program_years),
    }
    methods = (
        program["q10_method"]
        .fillna("missing")
        .value_counts()
        .reindex(
            ["order_stat_interpolation", "minimum_only", "small_n_minimum", "missing"],
            fill_value=0,
        )
    )
    issues = {
        "复试比不一致": int(program["issue_codes"].fillna("").str.contains("retest_ratio_mismatch").sum()),
        "录取最低分低于所选线": int(
            program["issue_codes"].fillna("").str.contains("admitted_min_below_selected_cutoff").sum()
        ),
        "专项计划排除不明确": int(
            program["issue_codes"].fillna("").str.contains("special_plan_exclusion_unclear").sum()
        ),
    }

    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.7), gridspec_kw={"width_ratios": [1.2, 1.05, 0.9]})

    ax = axes[0]
    labels = list(counts)
    values = list(counts.values())
    colors = [BLUE, BLUE, ORANGE, GREEN, RED]
    bars = ax.bar(np.arange(len(labels)), values, color=colors, width=0.66)
    ax.set_title("数据可用性漏斗")
    ax.set_ylabel("学校-年份记录数")
    ax.set_xticks(np.arange(len(labels)), ["校年\n观测", "有复\n试线", "官方\n复试线", "Q10\n代理", "精确\nQ10"])
    ax.set_ylim(0, max(values) * 1.18)
    annotate_bars(ax, bars, pad=7)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    ax = axes[1]
    method_labels = ["顺序统计插值", "仅最低分", "小样本最低分", "缺失"]
    method_values = methods.to_numpy(dtype=float)
    bars = ax.bar(np.arange(4), method_values, color=[BLUE, ORANGE, PURPLE, "#a4adb7"], width=0.66)
    ax.set_title("Q10代理的构造方式")
    ax.set_ylabel("记录数")
    ax.set_xticks(np.arange(4), ["插值", "最低分", "小样本", "缺失"])
    ax.set_ylim(0, max(method_values) * 1.25)
    annotate_bars(ax, bars, pad=3)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    ax = axes[2]
    issue_labels = list(issues)
    issue_values = list(issues.values())
    bars = ax.barh(np.arange(len(issue_labels)), issue_values, color=[ORANGE, RED, PURPLE], height=0.58)
    ax.set_title("进入人工复核队列的问题")
    ax.set_xlabel("记录数")
    ax.set_yticks(np.arange(len(issue_labels)), ["复试比\n不一致", "最低分\n低于所选线", "专项计划\n排除不明"])
    ax.invert_yaxis()
    ax.set_xlim(0, max(issue_values) * 1.35)
    for bar in bars:
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2, f"{bar.get_width():.0f}", va="center", fontsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    fig.suptitle("从原始证据到可训练目标：缺失与审计问题必须显式暴露", fontsize=13, y=1.03)
    fig.tight_layout()
    finish(fig, output_dir, "01_data_audit")
    return {"counts": counts, "q10_methods": dict(zip(method_labels, method_values.astype(int))), "issues": issues}


def figure_provenance_audit(
    provenance: dict,
    url_audit: dict,
    supplemental: dict,
    roster_index_audit: dict,
    roster_audit: dict,
    output_dir: Path,
) -> dict:
    """Visualize the evidence chain, not merely the volume of collected data."""
    program = provenance.get("program_year", {})
    field_total = int(program.get("field_value_count", 0))
    field_linked = int(program.get("field_values_with_public_url", 0))
    url_reachable = int(url_audit.get("reachable", 0))
    url_failed = int(url_audit.get("failed_or_blocked", 0))
    dead_years = int(supplemental.get("dead_third_party_school_years", 0))
    supplemented_years = int(
        supplemental.get("dead_third_party_school_years_with_live_reconciled_supplement", 0)
    )
    roster_values = [
        int(roster_index_audit.get("successful_api_targets", 0)),
        int(roster_audit.get("images", 0)),
        int(roster_audit.get("images_parsed", 0)),
        int(roster_audit.get("validated_exact_programs", 0)),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.7), gridspec_kw={"width_ratios": [1.05, 1.0, 1.25]})

    ax = axes[0]
    linked_pct = 100 * field_linked / field_total if field_total else 0.0
    ax.barh([0], [100], color="#e3e8ed", height=0.42)
    ax.barh([0], [linked_pct], color=GREEN, height=0.42)
    ax.text(linked_pct / 2, 0, f"{field_linked:,} / {field_total:,}\n{linked_pct:.2f}%", ha="center", va="center", color="white", fontsize=11, fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.set_xlabel("非空核心字段值中附有公开 URL 的比例（%）")
    ax.set_title("字段级可追溯性")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    ax = axes[1]
    bars = ax.bar(
        [0, 1],
        [url_reachable, url_failed],
        color=[GREEN, ORANGE],
        width=0.62,
    )
    ax.set_xticks([0, 1], ["本次可访问", "失效/受阻"])
    ax.set_ylabel("唯一 URL 数")
    ax.set_title("来源链接现时可访问性")
    ax.set_ylim(0, max(url_reachable, url_failed, 1) * 1.2)
    annotate_bars(ax, bars, pad=max(url_reachable, url_failed, 1) * 0.025)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.text(0.5, -0.24, "链接失效不等于历史证据无效；状态被保留并补充独立证据", transform=ax.transAxes, ha="center", fontsize=8.2, color=MUTED)

    ax = axes[2]
    labels = ["详情接口", "名单图片", "表格可解析", "四项核对通过"]
    ypos = np.arange(len(labels))
    bars = ax.barh(ypos, roster_values, color=[BLUE, BLUE, ORANGE, GREEN], height=0.56)
    ax.set_yticks(ypos, labels)
    ax.invert_yaxis()
    ax.set_xlabel("证据单元数")
    ax.set_title("逐名标签的质量闸门")
    ax.set_xlim(0, max(roster_values + [1]) * 1.22)
    for bar in bars:
        ax.text(bar.get_width() + max(roster_values + [1]) * 0.02, bar.get_y() + bar.get_height() / 2, f"{bar.get_width():.0f}", va="center", fontsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    fig.suptitle("证据链审计：有来源、能访问、可解析、可核对是四个不同层次", fontsize=13, y=1.03)
    fig.tight_layout()
    finish(fig, output_dir, "01b_provenance_audit")
    return {
        "field_values": field_total,
        "field_values_with_public_url": field_linked,
        "url_reachable": url_reachable,
        "url_failed_or_blocked": url_failed,
        "dead_source_school_years": dead_years,
        "dead_source_school_years_supplemented": supplemented_years,
        "roster_funnel": dict(zip(labels, roster_values)),
    }


def figure_exact_label_upgrade(
    proxy_pairs: pd.DataFrame,
    paired_backtest: pd.DataFrame,
    exact_summary: dict,
    output_dir: Path,
) -> dict:
    """Show what exact labels teach us about proxies, models and Q10 noise."""
    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.75), gridspec_kw={"width_ratios": [1.0, 1.08, 1.0]})

    ax = axes[0]
    year_colors = {2024: BLUE, 2025: ORANGE, 2026: GREEN}
    for year, group in proxy_pairs.groupby("year"):
        ax.scatter(
            group["q10_value"],
            group["q10_exact"],
            s=28,
            alpha=0.78,
            color=year_colors.get(int(year), MUTED),
            label=str(int(year)),
            edgecolor="white",
            linewidth=0.35,
        )
    limits = [
        float(min(proxy_pairs["q10_value"].min(), proxy_pairs["q10_exact"].min()) - 4),
        float(max(proxy_pairs["q10_value"].max(), proxy_pairs["q10_exact"].max()) + 4),
    ]
    ax.plot(limits, limits, linestyle="--", color=MUTED, linewidth=1.0, label="完全一致")
    ax.set_xlim(limits)
    ax.set_ylim(limits)
    ax.set_xlabel("原 Q10 代理（分）")
    ax.set_ylabel("逐名精确 Q10（分）")
    ax.set_title("代理是否系统偏离真实标签")
    ax.legend(frameon=False, fontsize=7.8, ncol=2)
    ax.grid(color=GRID, linewidth=0.6)
    bias = float(proxy_pairs["exact_minus_proxy"].mean())
    proxy_mae = float(proxy_pairs["exact_minus_proxy"].abs().mean())
    ax.text(0.04, 0.96, f"平均偏差 +{bias:.2f} 分\n代理 MAE {proxy_mae:.2f} 分", transform=ax.transAxes, va="top", fontsize=8.6, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": GRID})

    ax = axes[1]
    rows = []
    for year, group in paired_backtest.groupby("year"):
        rows.append(
            (
                int(year),
                float((group["q10_exact"] - group["baseline_q50"]).abs().mean()),
                float((group["q10_exact"] - group["enhanced_q50"]).abs().mean()),
            )
        )
    positions = np.arange(len(rows))
    width = 0.34
    baseline_bars = ax.bar(positions - width / 2, [row[1] for row in rows], width, color="#a4adb7", label="冻结代理模型")
    enhanced_bars = ax.bar(positions + width / 2, [row[2] for row in rows], width, color=GREEN, label="精确标签增强")
    ax.set_xticks(positions, [str(row[0]) for row in rows])
    ax.set_ylabel("精确 Q10 上的 MAE（分）")
    ax.set_title("同一真实标签上的逐年比较")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for bars in (baseline_bars, enhanced_bars):
        annotate_bars(ax, bars, fmt="{:.1f}", pad=0.35)

    ax = axes[2]
    ax.scatter(
        proxy_pairs["candidate_n"],
        proxy_pairs["q10_bootstrap_sd"],
        c=[year_colors.get(int(year), MUTED) for year in proxy_pairs["year"]],
        s=28,
        alpha=0.78,
        edgecolor="white",
        linewidth=0.35,
    )
    ax.set_xscale("log")
    ax.set_xlabel("拟录取人数（对数刻度）")
    ax.set_ylabel("Q10 bootstrap 标准差（分）")
    ax.set_title("小样本 Q10 的抽样不确定性")
    ax.grid(color=GRID, linewidth=0.6)
    sampling_median = float(proxy_pairs["q10_bootstrap_sd"].median())
    ax.text(0.96, 0.95, f"中位数 {sampling_median:.2f} 分", transform=ax.transAxes, ha="right", va="top", fontsize=8.6, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": GRID})

    fig.suptitle("逐名标签带来的三项可检验证据：代理偏差、模型增益与分位数抽样误差", fontsize=13, y=1.03)
    fig.tight_layout()
    finish(fig, output_dir, "01c_exact_label_upgrade")
    return {
        "exact_program_years": int(exact_summary.get("exact_program_years_total", len(proxy_pairs))),
        "exact_candidate_rows": int(exact_summary.get("exact_candidate_rows", proxy_pairs["candidate_n"].sum())),
        "proxy_mean_bias": bias,
        "proxy_mae": proxy_mae,
        "baseline_exact_mae": exact_summary.get("frozen_baseline_on_exact_labels", {}).get("mae"),
        "enhanced_exact_mae": exact_summary.get("enhanced_model_on_exact_labels", {}).get("mae"),
        "year_block_mae_difference": exact_summary.get("paired_year_block_mae_difference", {}),
        "bootstrap_sd_median": sampling_median,
    }


def figure_national_line(
    national: dict, app_forecast: dict, output_dir: Path, forecast_year: int
) -> dict:
    if isinstance(national, dict) and "values" in national:
        records = [
            {"year": int(year), "line_a": values["A"], "line_b": values["B"]}
            for year, values in national["values"].items()
        ]
    else:
        records = national.get("history", national if isinstance(national, list) else [])
    if isinstance(records, dict):
        records = records.get("records", [])
    history = pd.DataFrame(records)
    if history.empty:
        history = pd.DataFrame(app_forecast.get("nationalLineHistory", []))
    # tolerate alternate field names
    rename = {"A": "line_a", "B": "line_b", "zoneA": "line_a", "zoneB": "line_b"}
    history = history.rename(columns=rename)
    if "year" not in history.columns:
        raise ValueError("national line history must contain a year column")
    line_a = next(c for c in ["line_a", "a", "A_line", "zone_a"] if c in history.columns)
    line_b = next(c for c in ["line_b", "b", "B_line", "zone_b"] if c in history.columns)
    history = history.sort_values("year")

    fc = app_forecast["meta"]["nationalLineForecast"]
    fig, ax = plt.subplots(figsize=(8.6, 4.3))
    ax.plot(history["year"], history[line_a], marker="o", color=BLUE, linewidth=2, label="A区国家线")
    ax.plot(history["year"], history[line_b], marker="s", color=ORANGE, linewidth=2, label="B区国家线")
    for zone, color, marker in [("A", BLUE, "o"), ("B", ORANGE, "s")]:
        f = fc[zone]
        x0 = float(history["year"].max())
        y0 = float(history[line_a if zone == "A" else line_b].iloc[-1])
        ax.plot([x0, forecast_year], [y0, f["q50"]], color=color, linestyle="--", linewidth=1.4)
        ax.errorbar(
            [forecast_year],
            [f["q50"]],
            yerr=[[f["q50"] - (2 * f["q50"] - f["q90"])], [f["q90"] - f["q50"]]],
            fmt=marker,
            capsize=4,
            color=color,
            markersize=6,
        )
        ax.text(forecast_year + 0.08, f["q50"], f"{zone}区 {f['q50']:.1f}", va="center", fontsize=9, color=color)
    ax.axvline(forecast_year - 0.5, color=MUTED, linewidth=1, linestyle=":")
    ax.text(
        forecast_year - 0.42,
        0.97,
        "报名时点后的预测区",
        transform=ax.get_xaxis_transform(),
        va="top",
        fontsize=8.5,
        color=MUTED,
    )
    ax.set_title(f"国家线历史与 {forecast_year} 年报名时点预测")
    ax.set_xlabel("招生年份")
    ax.set_ylabel("总分")
    ax.set_xticks(list(history["year"].astype(int)) + [forecast_year])
    ax.set_xlim(float(history["year"].min()) - 0.25, forecast_year + 0.72)
    ax.grid(color=GRID, linewidth=0.7)
    ax.legend(frameon=False, ncol=2, loc="lower left")
    fig.tight_layout()
    finish(fig, output_dir, "02_national_line")
    return {"forecast": fc, "history_rows": int(len(history))}


def figure_rolling_origin(backtest: pd.DataFrame, output_dir: Path) -> None:
    years = sorted(int(v) for v in backtest["year"].unique())
    min_history = min(years) - 2
    cells = []
    for y in years:
        cells.append((y, list(range(min_history, y)), y))
    fig, ax = plt.subplots(figsize=(9.2, 2.8))
    for row, (test_year, train_years, _) in enumerate(cells):
        for yr in train_years:
            ax.barh(row, 0.82, left=yr - 0.41, height=0.48, color=LIGHT_BLUE, edgecolor=BLUE, linewidth=0.7)
        ax.barh(row, 0.82, left=test_year - 0.41, height=0.48, color=ORANGE, edgecolor=ORANGE, linewidth=0.7)
        ax.text(test_year, row, f"检验 {test_year}", ha="center", va="center", fontsize=8, color="white")
    ax.set_yticks(range(len(cells)), [f"第 {i + 1} 折" for i in range(len(cells))])
    ax.set_xticks(range(min_history, max(years) + 1))
    ax.set_xlabel("年份：蓝色只用于训练，橙色作为下一年时间外检验")
    ax.set_title("逐年扩窗滚动回测：报名后信息不得进入当年预测")
    ax.set_ylim(-0.65, len(cells) - 0.35)
    ax.invert_yaxis()
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    finish(fig, output_dir, "03_rolling_origin")


def compute_backtest_metrics(backtest: pd.DataFrame) -> dict:
    bt = backtest.copy()
    bt["abs_error"] = (bt["actual"] - bt["pred_q50"]).abs()
    bt["complex_abs_error"] = (bt["actual"] - bt["complex_q50"]).abs()
    bt["baseline_abs_error"] = (bt["actual"] - bt["baseline"]).abs()
    bt["robust_abs_error"] = (bt["actual"] - bt["robust_baseline"]).abs()
    bt["asym_loss"] = np.where(
        bt["actual"] > bt["pred_q50"],
        3 * (bt["actual"] - bt["pred_q50"]),
        bt["pred_q50"] - bt["actual"],
    )
    overall = {
        "rows": int(len(bt)),
        "weighted_mae": weighted_mean(bt["abs_error"], bt["weight"]),
        "median_absolute_error": float(bt["abs_error"].median()),
        "asymmetric_loss_3x": weighted_mean(bt["asym_loss"], bt["weight"]),
        "underprediction_rate": weighted_mean((bt["actual"] > bt["pred_q50"]).astype(float), bt["weight"]),
        "complex_candidate_mae": weighted_mean(bt["complex_abs_error"], bt["weight"]),
        "last_year_baseline_mae": weighted_mean(bt["baseline_abs_error"], bt["weight"]),
        "robust_anchor_mae": weighted_mean(bt["robust_abs_error"], bt["weight"]),
        "q80_coverage": weighted_mean((bt["actual"] <= bt["pred_q80"]).astype(float), bt["weight"]),
        "q90_coverage": weighted_mean((bt["actual"] <= bt["pred_q90"]).astype(float), bt["weight"]),
        "q95_coverage": weighted_mean((bt["actual"] <= bt["pred_q95"]).astype(float), bt["weight"]),
    }
    yearly = []
    for year, g in bt.groupby("year"):
        yearly.append(
            {
                "year": int(year),
                "n": int(len(g)),
                "weighted_mae": weighted_mean(g["abs_error"], g["weight"]),
                "median_absolute_error": float(g["abs_error"].median()),
                "underprediction_rate": weighted_mean((g["actual"] > g["pred_q50"]).astype(float), g["weight"]),
                "q80_coverage": weighted_mean((g["actual"] <= g["pred_q80"]).astype(float), g["weight"]),
                "q90_coverage": weighted_mean((g["actual"] <= g["pred_q90"]).astype(float), g["weight"]),
                "q95_coverage": weighted_mean((g["actual"] <= g["pred_q95"]).astype(float), g["weight"]),
            }
        )
    by_model = []
    for model, g in bt.groupby("selected_model"):
        by_model.append(
            {
                "model": str(model),
                "n": int(len(g)),
                "weighted_mae": weighted_mean(g["abs_error"], g["weight"]),
                "q90_coverage": weighted_mean((g["actual"] <= g["pred_q90"]).astype(float), g["weight"]),
            }
        )
    return {"overall": overall, "yearly": yearly, "by_model": by_model}


def figure_model_comparison(backtest: pd.DataFrame, metrics: dict, output_dir: Path) -> None:
    values = [
        metrics["overall"]["robust_anchor_mae"],
        metrics["overall"]["last_year_baseline_mae"],
        metrics["overall"]["complex_candidate_mae"],
    ]
    labels = ["稳健边际锚点", "上一年锚点", "复杂候选模型"]
    colors = [GREEN, BLUE, PURPLE]
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    bars = ax.barh(np.arange(3), values, color=colors, height=0.58)
    ax.set_yticks(np.arange(3), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.25)
    ax.set_xlabel("时间外加权 MAE（分，越低越好）")
    ax.set_title("候选中心预测比较：复杂度没有自动换来更低误差")
    for bar, value in zip(bars, values):
        ax.text(value + 0.25, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center", fontsize=9.5)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "04_model_comparison")


def figure_yearly_backtest(metrics: dict, output_dir: Path) -> None:
    yearly = pd.DataFrame(metrics["yearly"])
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
    ax = axes[0]
    bars = ax.bar(yearly["year"].astype(str), yearly["weighted_mae"], color=[BLUE, ORANGE, GREEN], width=0.62)
    annotate_bars(ax, bars, fmt="{:.2f}", pad=0.45)
    ax.set_ylabel("加权 MAE（分）")
    ax.set_title("点预测误差")
    ax.set_ylim(0, yearly["weighted_mae"].max() * 1.22)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    ax = axes[1]
    for col, label, color, marker in [
        ("q80_coverage", "P80 实际覆盖", BLUE, "o"),
        ("q90_coverage", "P90 实际覆盖", ORANGE, "s"),
        ("q95_coverage", "P95 实际覆盖", GREEN, "^")
    ]:
        ax.plot(yearly["year"], yearly[col], marker=marker, color=color, linewidth=2, label=label)
    for level, color in [(0.8, BLUE), (0.9, ORANGE), (0.95, GREEN)]:
        ax.axhline(level, color=color, linestyle=":", linewidth=0.9, alpha=0.7)
    ax.set_ylim(0.3, 1.02)
    ax.set_xticks(yearly["year"])
    ax.set_ylabel("覆盖率")
    ax.set_title("原始上界覆盖率：2026 年发生明显漂移")
    ax.grid(color=GRID, linewidth=0.7)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.suptitle("逐年滚动回测结果", fontsize=13, y=1.02)
    fig.tight_layout()
    finish(fig, output_dir, "05_yearly_backtest")


def figure_calibration_drift(backtest: pd.DataFrame, output_dir: Path) -> dict:
    bt = backtest.copy()
    bt["residual"] = bt["actual"] - bt["pred_q50"]
    windows = [
        ("2024", bt["year"] == 2024),
        ("2024-2025", bt["year"].isin([2024, 2025])),
        ("2024-2026", bt["year"].isin([2024, 2025, 2026])),
        ("仅 2026", bt["year"] == 2026),
    ]
    vals = []
    for name, mask in windows:
        g = bt.loc[mask]
        vals.append((name, weighted_quantile(g["residual"], 0.9, g["weight"])))
    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    labels = [v[0] for v in vals]
    numbers = [v[1] for v in vals]
    bars = ax.bar(np.arange(len(vals)), numbers, color=[BLUE, LIGHT_BLUE, ORANGE, RED], edgecolor=[BLUE, BLUE, ORANGE, RED], width=0.62)
    annotate_bars(ax, bars, fmt="{:.2f}", pad=0.7)
    ax.set_xticks(np.arange(len(vals)), labels)
    ax.set_ylabel("中位数残差的加权 P90（分）")
    ax.set_title("校准窗口敏感性：固定历史窗口无法消除年度漂移")
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(numbers) * 1.23)
    fig.tight_layout()
    finish(fig, output_dir, "06_calibration_drift")
    return {label: value for label, value in vals}


def figure_event_scenarios(events: pd.DataFrame, output_dir: Path) -> list[dict]:
    events = events.copy()
    events["expected_adjustment"] = (
        events["withdrawal_adjustment"] * events["withdrawal_weight"]
        + events["neutral_adjustment"] * events["neutral_weight"]
        + events["crowd_adjustment"] * events["crowd_weight"]
    )
    events = events.sort_values("expected_adjustment")
    fig, ax = plt.subplots(figsize=(9.2, 4.4))
    y = np.arange(len(events))
    for i, row in enumerate(events.itertuples(index=False)):
        values = [row.withdrawal_adjustment, row.neutral_adjustment, row.crowd_adjustment]
        ax.plot([min(values), max(values)], [i, i], color=GRID, linewidth=5, solid_capstyle="round", zorder=1)
        ax.scatter(values, [i] * 3, s=[55, 55, 55], c=[BLUE, MUTED, ORANGE], marker="o", zorder=3)
        ax.scatter([row.expected_adjustment], [i], s=85, c=RED, marker="D", zorder=4)
        ax.text(row.expected_adjustment + 0.5, i - 0.20, f"期望 {row.expected_adjustment:+.2f}", fontsize=8.5, color=RED)
    ax.axvline(0, color=INK, linewidth=0.9)
    ax.set_yticks(y, events["school"])
    ax.set_xlabel("事件对所需分数的情景调整（分）")
    ax.set_title("已知事件的退潮-中性-涌入三情景（结构化专家先验）")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(
        handles=[
            Line2D([0], [0], marker="o", color="none", markerfacecolor=BLUE, markeredgecolor=BLUE, label="退潮"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor=MUTED, markeredgecolor=MUTED, label="中性"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor=ORANGE, markeredgecolor=ORANGE, label="涌入"),
            Line2D([0], [0], marker="D", color="none", markerfacecolor=RED, markeredgecolor=RED, label="加权期望"),
        ],
        frameon=False,
        ncol=4,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.30),
    )
    fig.tight_layout()
    finish(fig, output_dir, "07_event_scenarios")
    cols = [
        "school", "event_name", "withdrawal_adjustment", "neutral_adjustment", "crowd_adjustment",
        "withdrawal_weight", "neutral_weight", "crowd_weight", "expected_adjustment", "source_url",
    ]
    return events[cols].round(4).to_dict(orient="records")


def figure_forecast_spectrum(forecast: pd.DataFrame, output_dir: Path) -> dict:
    forecast = forecast.copy().sort_values("q90")
    selected = pd.concat([forecast.head(8), forecast.tail(8)]).drop_duplicates("school")
    selected = selected.sort_values("q90")
    fig, ax = plt.subplots(figsize=(8.8, 7.2))
    y = np.arange(len(selected))
    for i, row in enumerate(selected.itertuples(index=False)):
        color = FACTION_COLORS.get(row.faction, MUTED)
        ax.plot([row.q50, row.q90], [i, i], color=color, linewidth=3, solid_capstyle="round")
        ax.scatter([row.q50], [i], color="white", edgecolor=color, s=45, zorder=3, linewidth=1.4)
        ax.scatter([row.q90], [i], color=color, edgecolor=color, s=45, zorder=3)
        ax.text(row.q90 + 1.4, i, f"{row.q90:.1f}", va="center", fontsize=8.3)
    ax.set_yticks(y, selected["school"])
    ax.set_xlabel("预测所需分数：空心点 P50，实心点为稳健 P90* 安全上界")
    ax.set_title("2027 年风险带光谱：仅展示两端各 8 所，不作精细名次解释")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    present = [f for f in FACTION_COLORS if f in selected["faction"].unique()]
    ax.legend(
        handles=[Patch(facecolor=FACTION_COLORS[f], label=f) for f in present],
        frameon=False,
        ncol=min(3, len(present)),
        loc="lower center",
        bbox_to_anchor=(0.5, -0.17),
    )
    fig.tight_layout()
    finish(fig, output_dir, "08_forecast_spectrum")
    return {
        "q50_mean": float(forecast["q50"].mean()),
        "q50_sd": float(forecast["q50"].std(ddof=1)),
        "q50_min": float(forecast["q50"].min()),
        "q50_median": float(forecast["q50"].median()),
        "q50_max": float(forecast["q50"].max()),
        "q90_mean": float(forecast["q90"].mean()),
        "q90_sd": float(forecast["q90"].std(ddof=1)),
        "q90_min": float(forecast["q90"].min()),
        "q90_median": float(forecast["q90"].median()),
        "q90_max": float(forecast["q90"].max()),
        "confidence_counts": forecast["confidence"].value_counts().to_dict(),
        "faction_counts": forecast["faction"].value_counts().to_dict(),
    }


def interpolated_cdf(score: np.ndarray, anchors_x: Sequence[float], anchors_p: Sequence[float]) -> np.ndarray:
    x = np.asarray(anchors_x, dtype=float)
    p = np.asarray(anchors_p, dtype=float)
    out = np.interp(score, x, p)
    out[score < x[0]] = p[0]
    out[score > x[-1]] = p[-1]
    return np.clip(out, p[0], p[-1])


def figure_ecnu_cdf(forecast: pd.DataFrame, output_dir: Path) -> dict:
    row = forecast.loc[forecast["school"] == "华东师范大学"].iloc[0]
    probs = np.array([0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95])
    anchors = np.array([row.q05, row.q10, row.q20, row.q50, row.q80, row.q90, row.q95], dtype=float)
    scores = np.linspace(anchors[0] - 10, anchors[-1] + 10, 240)
    cdf = interpolated_cdf(scores, anchors, probs)
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.plot(scores, cdf, color=BLUE, linewidth=2.4)
    ax.scatter(anchors, probs, color=BLUE, edgecolor="white", linewidth=0.8, s=45, zorder=3)
    for threshold, label, color in [(0.60, "观察/冲分界", PURPLE), (0.90, "稳", ORANGE), (0.95, "保", GREEN)]:
        ax.axhline(threshold, color=color, linestyle="--", linewidth=1)
        ax.text(scores[0] + 1, threshold + 0.018, f"{label} {threshold:.0%}", fontsize=8.5, color=color)
    ax.axvline(row.q90, color=ORANGE, linestyle=":", linewidth=1)
    ax.text(row.q90 + 0.8, 0.20, f"P90 上界 {row.q90:.1f} 分", rotation=90, va="bottom", fontsize=8.5, color=ORANGE)
    ax.set_ylim(0, 1.0)
    ax.set_xlim(scores.min(), scores.max())
    ax.set_xlabel("考生报名时估分（分）")
    ax.set_ylabel("估分覆盖预测门槛的概率")
    ax.set_title("华东师范大学示例：由七个预测分位点得到覆盖概率")
    ax.grid(color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "09_ecnu_cdf")
    query_scores = np.array([375.0, 380.0, 385.0, 390.0, float(row.q90), 395.0, 400.0, 405.0])
    query_probs = interpolated_cdf(query_scores, anchors, probs)
    return {
        "anchors": {f"q{int(p * 100):02d}": float(v) for p, v in zip(probs, anchors)},
        "score_probabilities": {f"{s:g}": float(p) for s, p in zip(query_scores, query_probs)},
    }


def figure_feature_effects(app_forecast: dict, output_dir: Path) -> list[dict]:
    effects = app_forecast.get("featureEffects", [])
    if isinstance(effects, dict):
        effects = [{"feature": k, **(v if isinstance(v, dict) else {"effect": v})} for k, v in effects.items()]
    frame = pd.DataFrame(effects)
    if frame.empty:
        raise ValueError("featureEffects is empty")
    feature_col = next(c for c in ["feature", "name", "label"] if c in frame.columns)
    effect_col = next(
        c for c in ["effect", "mean", "value", "standardizedEffect", "posterior_mean"]
        if c in frame.columns
    )
    sd_col = next(
        (c for c in ["sd", "std", "standardDeviation", "posterior_sd"] if c in frame.columns),
        None,
    )
    translation = {
        "year_index": "年份趋势",
        "is985": "985身份",
        "is_985": "985身份",
        "trailing_margin_median": "历史边际中位数",
        "national_zone_A": "A区",
        "national_zone_B": "B区",
        "national_zone=A": "A区",
        "national_zone=B": "B区",
        "lag1_margin_q10": "上一年Q10边际",
        "log1p_lag1_admitted_count": "上一年录取数（对数）",
        "log_lag1_admitted_count": "上一年录取数（对数）",
        "peer_lag1_surprise_mean": "竞校上一年异常",
        "lag1_cutoff_change": "上一年复试线变化",
        "lag1_surprise_z": "上一年冷热异常",
    }
    frame["label_cn"] = frame[feature_col].map(translation).fillna(frame[feature_col])
    frame["effect_value"] = pd.to_numeric(frame[effect_col], errors="coerce")
    if sd_col:
        frame["sd_value"] = pd.to_numeric(frame[sd_col], errors="coerce").fillna(0)
    else:
        frame["sd_value"] = 0.0
    preferred = [
        "year_index",
        "is_985",
        "trailing_margin_median",
        "national_zone=A",
        "national_zone=B",
        "lag1_margin_q10",
        "log_lag1_admitted_count",
        "peer_lag1_surprise_mean",
        "lag1_cutoff_change",
        "lag1_surprise_z",
    ]
    frame = frame.loc[frame[feature_col].isin(preferred)].dropna(subset=["effect_value"])
    frame = frame.sort_values("effect_value")
    fig, ax = plt.subplots(figsize=(8.3, 5.2))
    y = np.arange(len(frame))
    colors = np.where(frame["effect_value"] >= 0, BLUE, ORANGE)
    ax.errorbar(
        frame["effect_value"], y, xerr=frame["sd_value"], fmt="none", ecolor=GRID,
        elinewidth=4, capsize=0, zorder=1,
    )
    ax.scatter(frame["effect_value"], y, c=colors, s=55, zorder=3)
    ax.axvline(0, color=INK, linewidth=0.9)
    ax.set_yticks(y, frame["label_cn"])
    ax.set_xlabel("标准化特征变化对应的复杂候选模型预测关联（分）")
    ax.set_title("复杂候选模型中的预测关联：不作因果解释")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "10_feature_effects")
    return frame[[feature_col, "label_cn", "effect_value", "sd_value"]].round(4).to_dict(orient="records")


def figure_loss_quantile(output_dir: Path) -> dict:
    ratios = np.array([1, 2, 3, 4, 5, 9], dtype=float)
    quantiles = ratios / (1 + ratios)
    fig, ax = plt.subplots(figsize=(7.8, 3.9))
    ax.plot(ratios, quantiles, color=BLUE, linewidth=2.2, marker="o")
    ax.scatter([3], [0.75], color=ORANGE, s=90, zorder=4)
    ax.annotate(
        "当前 λ=3 → 决策最优点为 P75\n“稳”仍额外采用 P90 风险约束",
        xy=(3, 0.75), xytext=(4.2, 0.66),
        arrowprops={"arrowstyle": "->", "color": ORANGE, "lw": 1.2},
        fontsize=9, color=INK,
    )
    ax.axhline(0.90, color=GREEN, linestyle="--", linewidth=1)
    ax.text(8.8, 0.905, "P90", ha="right", va="bottom", fontsize=8.5, color=GREEN)
    ax.set_xticks(ratios.astype(int))
    ax.set_ylim(0.45, 0.95)
    ax.set_xlabel("低估 1 分相对高估 1 分的损失倍数 λ")
    ax.set_ylabel("非对称绝对损失的最优分位点 λ/(1+λ)")
    ax.set_title("损失偏好与风险约束是两个不同层级")
    ax.grid(color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "11_loss_quantile")
    return {str(int(r)): float(q) for r, q in zip(ratios, quantiles)}


def figure_reliability_curve(nested: pd.DataFrame, output_dir: Path) -> dict:
    """Reliability curve on origins with an earlier OOS calibration set."""
    strict = nested[nested["robust_calibration_prior_rows"] > 0].copy()
    quantiles = np.array([0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95])
    weights = strict["weight"].to_numpy(float)
    actual = strict["actual"].to_numpy(float)
    raw_observed = []
    robust_observed = []
    for quantile in quantiles:
        q = int(quantile * 100)
        raw_observed.append(
            weighted_mean(actual <= strict[f"pred_q{q:02d}"], weights)
        )
        robust_column = f"robust_q{q:02d}"
        robust_observed.append(
            weighted_mean(actual <= strict[robust_column], weights)
        )
    fig, ax = plt.subplots(figsize=(6.8, 5.4))
    ax.plot([0, 1], [0, 1], color=MUTED, linestyle="--", linewidth=1.1, label="理想校准")
    ax.plot(quantiles, raw_observed, color=ORANGE, marker="o", linewidth=2, label="原始分布")
    ax.plot(quantiles, robust_observed, color=GREEN, marker="s", linewidth=2, label="稳健安全上界")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("名义分位")
    ax.set_ylabel("加权实际覆盖率")
    ax.set_title("严格嵌套年份的可靠性曲线（2025-2026）")
    ax.grid(color=GRID, linewidth=0.7)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    finish(fig, output_dir, "12_reliability_curve")
    return {
        "rows": int(len(strict)),
        "quantiles": quantiles.tolist(),
        "raw_observed": raw_observed,
        "robust_observed": robust_observed,
    }


def figure_calibration_tradeoff(summary: dict, output_dir: Path) -> dict:
    strict = summary["overall_strict_nested"]
    raw = strict["raw_distribution"]
    robust = strict["robust_origin_safety_bound"]
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.6))
    comparisons = [
        ("WIS\n越低越好", raw["wis"], robust["wis"], None),
        ("P90覆盖率\n目标90%", raw["q90_coverage"] * 100, robust["q90_coverage"] * 100, 90),
        ("P90-P50宽度\n分", raw["upper_width_90"], robust["upper_width_90"], None),
    ]
    for ax, (title, raw_value, robust_value, reference) in zip(axes, comparisons):
        bars = ax.bar(["原始", "稳健"], [raw_value, robust_value], color=[ORANGE, GREEN], width=0.62)
        for bar, value in zip(bars, [raw_value, robust_value]):
            label = f"{value:.1f}" if max(raw_value, robust_value) >= 20 else f"{value:.2f}"
            ax.text(bar.get_x() + bar.get_width() / 2, value + max(raw_value, robust_value) * 0.035, label, ha="center", fontsize=9)
        if reference is not None:
            ax.axhline(reference, color=MUTED, linestyle="--", linewidth=1)
        ax.set_title(title, fontsize=10.5)
        ax.grid(axis="y", color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(raw_value, robust_value, reference or 0) * 1.18)
    fig.suptitle("校准不是只追覆盖率：同时比较锐度和 proper score", fontsize=12.5, y=1.02)
    fig.tight_layout()
    finish(fig, output_dir, "13_calibration_tradeoff")
    return {"raw": raw, "robust": robust}


def figure_calibration_frontier(candidates: pd.DataFrame, output_dir: Path) -> list[dict]:
    """Show why the promoted calibration must balance score and both upper tails."""
    labels = {
        "raw": "原始分布",
        "pooled_floor": "全局地板",
        "recent_floor": "近期地板",
        "worst_origin_floor": "最不利年份地板",
        "pooled_tail": "全局上尾",
        "recent_tail": "近期上尾",
        "worst_origin_tail": "最不利年份上尾",
        "scaled_pooled_floor": "分层尺度全局地板",
        "scaled_worst_origin_floor": "选定：分层尺度最不利地板",
    }
    selected_key = "scaled_worst_origin_floor"
    frame = candidates.copy()
    frame["label"] = frame["strategy"].map(labels).fillna(frame["strategy"])

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.35))
    for _, row in frame.iterrows():
        key = row["strategy"]
        if key == selected_key:
            color, marker, size, zorder = GREEN, "*", 170, 5
        elif key == "raw":
            color, marker, size, zorder = ORANGE, "o", 68, 4
        elif bool(row["promotion_eligible"]):
            color, marker, size, zorder = BLUE, "s", 58, 3
        else:
            color, marker, size, zorder = MUTED, "o", 42, 2
        axes[0].scatter(
            row["upper_width_90"], row["wis"], color=color, marker=marker,
            s=size, alpha=0.92, zorder=zorder,
        )
        axes[1].scatter(
            row["q90_coverage"] * 100, row["q95_coverage"] * 100,
            color=color, marker=marker, s=size, alpha=0.92, zorder=zorder,
        )

    key_offsets = {
        "raw": (4, 6),
        "worst_origin_floor": (-82, 10),
        "worst_origin_tail": (5, -15),
        selected_key: (-120, 8),
    }
    for _, row in frame[frame["strategy"].isin(key_offsets)].iterrows():
        offset = key_offsets[row["strategy"]]
        label = row["label"]
        axes[0].annotate(
            label,
            (row["upper_width_90"], row["wis"]),
            xytext=offset,
            textcoords="offset points",
            fontsize=8.1,
            color=INK,
            arrowprops={"arrowstyle": "-", "color": GRID, "lw": 0.8},
        )

    axes[0].set_xlabel("P90-P50 上界宽度（分，越窄越好）")
    axes[0].set_ylabel("加权区间分数 WIS（越低越好）")
    axes[0].set_title("锐度与整体概率质量")
    axes[0].grid(color=GRID, linewidth=0.7)
    axes[0].set_axisbelow(True)

    axes[1].axvline(90, color=MUTED, linestyle="--", linewidth=1)
    axes[1].axhline(95, color=MUTED, linestyle="--", linewidth=1)
    axes[1].fill_betweenx([95, 101], 90, 101, color=LIGHT_GREEN, alpha=0.65, zorder=0)
    axes[1].text(100.3, 100.1, "同时达到 P90/P95 目标", ha="right", va="top", fontsize=8.2, color=GREEN)
    for key in ["raw", "worst_origin_floor", "worst_origin_tail", selected_key]:
        row = frame.loc[frame["strategy"] == key].iloc[0]
        offset = {
            "raw": (5, -14),
            "worst_origin_floor": (-84, -16),
            "worst_origin_tail": (6, 8),
            selected_key: (5, 7),
        }[key]
        axes[1].annotate(
            row["label"],
            (row["q90_coverage"] * 100, row["q95_coverage"] * 100),
            xytext=offset,
            textcoords="offset points",
            fontsize=8.1,
            color=INK,
            arrowprops={"arrowstyle": "-", "color": GRID, "lw": 0.8},
        )
    axes[1].set_xlim(78, 100.8)
    axes[1].set_ylim(84, 100.8)
    axes[1].set_xlabel("P90 加权覆盖率（%）")
    axes[1].set_ylabel("P95 加权覆盖率（%）")
    axes[1].set_title("两个上尾目标不能只顾其一")
    axes[1].grid(color=GRID, linewidth=0.7)
    axes[1].set_axisbelow(True)

    fig.suptitle("九种校准候选的覆盖—锐度—评分权衡", fontsize=12.5, y=1.01)
    fig.tight_layout()
    finish(fig, output_dir, "17_calibration_frontier")
    return frame.drop(columns="label").round(6).to_dict(orient="records")


def figure_conditional_coverage(nested: pd.DataFrame, output_dir: Path) -> list[dict]:
    """Diagnose strict nested P90 coverage without pretending small groups are precise."""
    strict = nested[nested["robust_calibration_prior_rows"] > 0].copy()
    groups: list[tuple[str, pd.Series]] = [
        ("非985", ~strict["is_985"].astype(bool)),
        ("985", strict["is_985"].astype(bool)),
        ("A区", strict["national_zone"].eq("A")),
        ("B区", strict["national_zone"].eq("B")),
        ("证据较低", strict["confidence_band"].eq("较低")),
        ("证据中等", strict["confidence_band"].eq("中等")),
        ("证据较高", strict["confidence_band"].eq("较高")),
    ]
    rows = []
    for label, mask in groups:
        subset = strict.loc[mask]
        weights = subset["weight"].to_numpy(float)
        covered = subset["actual"].to_numpy(float) <= subset["robust_q90"].to_numpy(float)
        rows.append(
            {
                "group": label,
                "rows": int(len(subset)),
                "effective_rows": float(weights.sum()),
                "q90_coverage": weighted_mean(covered, weights),
            }
        )
    frame = pd.DataFrame(rows)
    y = np.arange(len(frame))
    colors = [
        MUTED if row.rows < 10 else (GREEN if row.q90_coverage >= 0.90 else RED)
        for row in frame.itertuples()
    ]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.axvspan(88, 92, color=LIGHT_BLUE, alpha=0.42, zorder=0)
    ax.axvline(90, color=BLUE, linestyle="--", linewidth=1.1, label="名义目标 90%")
    for idx, row in frame.iterrows():
        value = row["q90_coverage"] * 100
        ax.hlines(idx, 75, value, color=GRID, linewidth=2.2, zorder=1)
        marker = "x" if row["rows"] < 10 else "o"
        ax.scatter(value, idx, color=colors[idx], marker=marker, s=68, zorder=3)
        if value >= 98.5:
            text_x, align = value - 0.7, "right"
        else:
            text_x, align = value + 0.7, "left"
        ax.text(text_x, idx, f"{value:.1f}% · n={row['rows']}", va="center", ha=align, fontsize=8.7)
    ax.set_yticks(y, frame["group"])
    ax.invert_yaxis()
    ax.set_xlim(75, 102.5)
    ax.set_xlabel("严格嵌套 P90* 加权覆盖率（%）")
    ax.set_title("总体覆盖不等于条件覆盖：低样本组只作诊断")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "18_conditional_coverage")
    return frame.round(6).to_dict(orient="records")


def figure_missingness(missingness: dict, output_dir: Path) -> dict:
    frame = pd.DataFrame(missingness["by_year"])
    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    bars = ax.bar(frame["year"].astype(str), frame["mean"] * 100, color=[RED, ORANGE, BLUE, GREEN, GREEN], width=0.62)
    annotate_bars(ax, bars, fmt="{:.1f}", pad=1.5)
    ax.set_ylabel("Q10代理缺失率（%）")
    ax.set_xlabel("招生年份")
    ax.set_title("标签缺失并非同质：主要集中在历史补录年份")
    ax.set_ylim(0, 105)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "14_missingness")
    return missingness


def figure_anchor_ablation(anchor: pd.DataFrame, output_dir: Path) -> list[dict]:
    frame = anchor.sort_values("weighted_mae", ascending=True).copy()
    labels = {
        "relative_last2_median": "近两年相对边际中位数",
        "relative_mean": "全部相对边际均值",
        "relative_recency_mean": "时间衰减相对边际均值",
        "relative_all_median": "全部相对边际中位数（正式中心）",
        "raw_all_median": "绝对分历史中位数",
        "relative_last": "上一年相对边际",
        "raw_last": "上一年绝对分",
    }
    frame["label"] = frame["model"].map(labels).fillna(frame["model"])
    colors = [GREEN if value == "relative_all_median" else BLUE for value in frame["model"]]
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    y = np.arange(len(frame))
    bars = ax.barh(y, frame["weighted_mae"], color=colors, height=0.58)
    ax.set_yticks(y, frame["label"])
    ax.invert_yaxis()
    ax.set_xlabel("2024-2026 时间外加权 MAE（分）")
    ax.set_title("简单中心消融：聚合冠军不能直接替代嵌套选择")
    ax.set_xlim(0, frame["weighted_mae"].max() * 1.25)
    for bar, value in zip(bars, frame["weighted_mae"]):
        ax.text(value + 0.18, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center", fontsize=8.8)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    finish(fig, output_dir, "15_anchor_ablation")
    return frame.drop(columns="label").to_dict(orient="records")


def figure_forecast_widths(forecast: pd.DataFrame, output_dir: Path) -> dict:
    raw_width = forecast["rawQ90"] - forecast["rawQ50"]
    robust_width = forecast["q90"] - forecast["q50"]
    q1, q3 = np.quantile(robust_width, [0.25, 0.75])
    threshold = float(q3 + 1.5 * (q3 - q1))
    flagged = forecast.loc[robust_width > threshold].copy()
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.45))

    parts = axes[0].violinplot(
        [raw_width.to_numpy(float), robust_width.to_numpy(float)],
        positions=[1, 2], widths=0.72, showmeans=False, showmedians=False, showextrema=False,
    )
    for body, color in zip(parts["bodies"], [ORANGE, GREEN]):
        body.set_facecolor(color)
        body.set_edgecolor(color)
        body.set_alpha(0.30)
    boxes = axes[0].boxplot(
        [raw_width.to_numpy(float), robust_width.to_numpy(float)],
        positions=[1, 2], widths=0.22, patch_artist=True, showfliers=False,
        medianprops={"color": INK, "linewidth": 1.4},
        boxprops={"facecolor": "white", "edgecolor": INK, "linewidth": 0.9},
        whiskerprops={"color": INK, "linewidth": 0.9},
        capprops={"color": INK, "linewidth": 0.9},
    )
    del boxes
    rng = np.random.default_rng(20261008)
    axes[0].scatter(1 + rng.normal(0, 0.045, len(raw_width)), raw_width, color=ORANGE, s=11, alpha=0.42)
    axes[0].scatter(2 + rng.normal(0, 0.045, len(robust_width)), robust_width, color=GREEN, s=11, alpha=0.42)
    axes[0].hlines(threshold, 1.62, 2.38, color=RED, linestyle="--", linewidth=1.2)
    axes[0].text(2.38, threshold + 0.8, f"Tukey上围栏 {threshold:.1f}", ha="right", va="bottom", fontsize=8.4, color=RED)
    for _, row in flagged.iterrows():
        width = float(row["q90"] - row["q50"])
        axes[0].annotate(
            f"{row['school']} {width:.1f}", xy=(2, width), xytext=(1.18, width - 1.2),
            fontsize=8.5, color=RED,
            arrowprops={"arrowstyle": "->", "color": RED, "lw": 0.9},
        )
    axes[0].set_xticks([1, 2], ["原始分布", "稳健安全上界"])
    axes[0].set_ylabel("P90-P50 上界宽度（分）")
    axes[0].set_title("宽度分布与信息不足离群点")
    axes[0].grid(axis="y", color=GRID, linewidth=0.7)

    confidence_colors = {"较高": GREEN, "中等": BLUE, "较低": ORANGE}
    for confidence, group in forecast.groupby("confidence"):
        axes[1].scatter(
            group["rawQ90"] - group["rawQ50"],
            group["q90"] - group["q50"],
            color=confidence_colors.get(confidence, MUTED),
            marker={"较高": "s", "中等": "o", "较低": "^"}.get(confidence, "o"),
            alpha=0.78, s=37, label=f"证据{confidence}",
        )
    maximum = max(float(raw_width.max()), float(robust_width.max())) + 3
    axes[1].plot([0, maximum], [0, maximum], color=MUTED, linestyle=":", linewidth=1, label="不额外扩宽")
    axes[1].axhline(threshold, color=RED, linestyle="--", linewidth=1)
    for _, row in flagged.iterrows():
        x_value = float(row["rawQ90"] - row["rawQ50"])
        y_value = float(row["q90"] - row["q50"])
        axes[1].annotate(
            row["school"], xy=(x_value, y_value), xytext=(x_value + 3.0, y_value - 1.5),
            fontsize=8.5, color=RED,
            arrowprops={"arrowstyle": "->", "color": RED, "lw": 0.9},
        )
    axes[1].set_xlim(13, max(23, float(raw_width.max()) + 5))
    axes[1].set_ylim(15, maximum)
    axes[1].set_xlabel("原始 P90-P50（分）")
    axes[1].set_ylabel("稳健 P90*-P50（分）")
    axes[1].set_title("原始尾部近同宽，异质性主要来自安全层")
    axes[1].grid(color=GRID, linewidth=0.7)
    axes[1].legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    finish(fig, output_dir, "16_forecast_widths")
    return {
        "raw_mean": float(raw_width.mean()),
        "raw_cv": float(raw_width.std(ddof=1) / raw_width.mean()),
        "robust_mean": float(robust_width.mean()),
        "robust_cv": float(robust_width.std(ddof=1) / robust_width.mean()),
        "robust_min": float(robust_width.min()),
        "robust_max": float(robust_width.max()),
        "tukey_q1": float(q1),
        "tukey_q3": float(q3),
        "tukey_upper_fence": threshold,
        "information_limited_schools": flagged["school"].tolist(),
    }


def _five_point_band(value: float) -> str:
    lower = int(math.floor(float(value) / 5.0) * 5)
    return f"{lower}-{lower + 5}"


def capture_git_state(root: Path) -> tuple[str, bool]:
    """Capture the source state before generated figures modify the tree."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable", True
    return commit, dirty


def build_manifest(
    root: Path, paths: list[Path], source_git_state: tuple[str, bool]
) -> dict:
    files = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    commit, dirty = source_git_state
    return {
        "data_vintage": "2026-10-07 23:59 Asia/Hong_Kong",
        "retrospective_audit_as_of": "2026-10-09",
        "python_seed": 20261007,
        "git_commit": commit,
        "working_tree_dirty": dirty,
        "files": files,
    }


def export_appendix_table(forecast: pd.DataFrame, output_dir: Path) -> None:
    cols = ["school", "is985", "zone", "faction", "q50", "rawQ90", "q90", "confidence", "upperWidthStatus"]
    table = forecast[cols].sort_values(["q90", "school"]).copy()
    table["q50"] = table["q50"].map(_five_point_band)
    table["rawQ90"] = table["rawQ90"].map(_five_point_band)
    table["q90"] = table["q90"].map(_five_point_band)
    table = table.rename(
        columns={
            "school": "院校",
            "is985": "是否985",
            "zone": "分区",
            "faction": "派系",
            "q50": "中心区间",
            "rawQ90": "原始P90区间",
            "q90": "稳健上界区间",
            "confidence": "证据完备度",
            "upperWidthStatus": "上界可比性",
        }
    )
    table["上界可比性"] = table["上界可比性"].map(
        {
            "information_limited": "证据不足：不宜精算",
            "decision_informative": "可作风险带比较",
        }
    ).fillna("待核实")
    table.to_csv(output_dir / "forecast_appendix.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    root = args.repo_root.resolve()
    source_git_state = capture_git_state(root)
    output_dir = (args.output_dir or root / "paper" / "assets" / "v3").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_matplotlib()

    processed = root / "data" / "processed"
    program = read_csv(processed / "program_year.csv")
    backtest = read_csv(processed / "rolling_backtest.csv")
    events = read_csv(processed / "events_2027.csv")
    forecast = read_csv(processed / "forecast_2027.csv")
    national = json.loads((processed / "national_lines.json").read_text(encoding="utf-8-sig"))
    app_forecast = json.loads((root / "app" / "data" / "forecast.json").read_text(encoding="utf-8-sig"))
    v3_dir = root / "output" / "experiments" / "v3_validation_20261007"
    v3_summary = json.loads((v3_dir / "summary.json").read_text(encoding="utf-8"))
    nested = read_csv(v3_dir / "nested_calibration_rows.csv")
    missingness = json.loads((v3_dir / "missingness.json").read_text(encoding="utf-8"))
    anchor_ablation = read_csv(v3_dir / "anchor_ablation.csv")
    calibration_dir = root / "output" / "experiments" / "calibration_candidates_20261008"
    calibration_candidates = read_csv(calibration_dir / "metrics.csv")
    audit_dir = root / "data" / "audit"

    def read_optional_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    provenance = read_optional_json(audit_dir / "provenance_coverage.json")
    url_audit = read_optional_json(audit_dir / "source_url_audit.json")
    supplemental = read_optional_json(audit_dir / "supplemental_provenance.json")
    roster_index_audit = read_optional_json(audit_dir / "mini_program_roster_index.json")
    roster_audit = read_optional_json(audit_dir / "candidate_score_extraction.json")
    exact_eval_dir = root / "output" / "experiments" / "v5_exact_labels_20261009" / "exact_evaluation"
    exact_summary = read_optional_json(exact_eval_dir / "summary.json")

    metrics = compute_backtest_metrics(backtest)
    figure_model_workflow(output_dir)
    summary = {
        "generated_from": {
            "program_year": str((processed / "program_year.csv").relative_to(root)),
            "rolling_backtest": str((processed / "rolling_backtest.csv").relative_to(root)),
            "events": str((processed / "events_2027.csv").relative_to(root)),
            "forecast": str((processed / "forecast_2027.csv").relative_to(root)),
            "national_lines": str((processed / "national_lines.json").relative_to(root)),
            "app_forecast": str((root / "app" / "data" / "forecast.json").relative_to(root)),
        },
        "forecast_year": args.forecast_year,
        "data_audit": figure_data_audit(
            program,
            output_dir,
            int(roster_audit.get("model_eligible_exact_programs", 0)),
        ),
        "national_line": figure_national_line(national, app_forecast, output_dir, args.forecast_year),
        "backtest": metrics,
        "v3_validation": v3_summary,
    }
    summary["provenance_audit"] = figure_provenance_audit(
        provenance, url_audit, supplemental, roster_index_audit, roster_audit, output_dir
    )
    if (exact_eval_dir / "exact_proxy_pairs.csv").exists() and (
        exact_eval_dir / "paired_exact_backtest.csv"
    ).exists():
        summary["exact_label_upgrade"] = figure_exact_label_upgrade(
            read_csv(exact_eval_dir / "exact_proxy_pairs.csv"),
            read_csv(exact_eval_dir / "paired_exact_backtest.csv"),
            exact_summary,
            output_dir,
        )
    figure_rolling_origin(backtest, output_dir)
    figure_model_comparison(backtest, metrics, output_dir)
    figure_yearly_backtest(metrics, output_dir)
    summary["calibration_window_q90"] = figure_calibration_drift(backtest, output_dir)
    summary["events"] = figure_event_scenarios(events, output_dir)
    summary["forecast_distribution"] = figure_forecast_spectrum(forecast, output_dir)
    summary["ecnu_example"] = figure_ecnu_cdf(forecast, output_dir)
    summary["complex_feature_effects"] = figure_feature_effects(app_forecast, output_dir)
    summary["loss_ratio_to_quantile"] = figure_loss_quantile(output_dir)
    summary["reliability"] = figure_reliability_curve(nested, output_dir)
    summary["calibration_tradeoff"] = figure_calibration_tradeoff(v3_summary, output_dir)
    summary["missingness"] = figure_missingness(missingness, output_dir)
    summary["anchor_ablation"] = figure_anchor_ablation(anchor_ablation, output_dir)
    summary["forecast_widths"] = figure_forecast_widths(forecast, output_dir)
    summary["calibration_candidates"] = figure_calibration_frontier(calibration_candidates, output_dir)
    summary["conditional_coverage"] = figure_conditional_coverage(nested, output_dir)
    export_appendix_table(forecast, output_dir)

    manifest_paths = [
        processed / "program_year.csv",
        processed / "rolling_backtest.csv",
        processed / "events_2027.csv",
        processed / "forecast_2027.csv",
        processed / "national_lines.json",
        root / "app" / "data" / "forecast.json",
        v3_dir / "summary.json",
        v3_dir / "nested_calibration_rows.csv",
        v3_dir / "missingness.json",
        v3_dir / "anchor_ablation.csv",
        calibration_dir / "metrics.csv",
        audit_dir / "provenance_coverage.json",
        audit_dir / "source_url_audit.json",
        audit_dir / "supplemental_provenance.json",
        audit_dir / "candidate_score_quality.json",
        audit_dir / "score_row_utilisation.json",
        processed / "program_year_provenance.csv",
        processed / "program_year_supplemental_provenance.csv",
        processed / "school_master_supplemental_provenance.csv",
        processed / "candidate_label_audit.csv",
        exact_eval_dir / "summary.json",
        exact_eval_dir / "exact_proxy_pairs.csv",
        exact_eval_dir / "paired_exact_backtest.csv",
        root / "output" / "experiments" / "v5_hierarchical_distribution_20261009" / "summary.json",
        root / "output" / "experiments" / "v5_retest_selection_20261009" / "summary.json",
        root / "app" / "data" / "model-v5-audit.json",
    ]
    manifest_paths = [path for path in manifest_paths if path.exists()]
    manifest = build_manifest(root, manifest_paths, source_git_state)
    summary["reproducibility_manifest"] = manifest
    (output_dir / "data_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (output_dir / "paper_metrics.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.item() if isinstance(value, np.generic) else str(value),
        ),
        encoding="utf-8",
    )
    print(f"Generated {len(list(output_dir.glob('*.svg')))} SVG figures in {output_dir}")
    print(f"Summary: {output_dir / 'paper_metrics.json'}")


if __name__ == "__main__":
    main()
