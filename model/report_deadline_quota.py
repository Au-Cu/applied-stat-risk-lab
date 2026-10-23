"""Render the quota experiment's actual coverage and predictive-score results.

Consumes aggregate experiment outputs. Does not retrain, select or promote a
model, and does not touch a paper, production forecast or candidate roster.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiment_deadline_quota import DEFAULT_OUT


LABELS = {
    "baseline_v6": "V6 研究基线（不含名额）",
    "strict_ordinary__availability__sd10": "严格口径：仅可得性标记",
    "strict_ordinary__level__sd10": "严格口径：名额水平",
    "strict_ordinary__change__sd10": "严格口径：名额变化",
    "strict_ordinary__level_change__sd10": "严格口径：水平＋变化",
    "special_scope_sensitivity__availability__sd10": "专项待核：仅可得性标记",
    "special_scope_sensitivity__level__sd10": "专项待核：名额水平",
    "special_scope_sensitivity__change__sd10": "专项待核：名额变化",
    "special_scope_sensitivity__level_change__sd10": "专项待核：水平＋变化",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    validation = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
    if validation["status"] != "passed":
        raise SystemExit("Do not publish a report before experiment validation passes.")
    comparison = pd.read_csv(out / "comparison.csv")
    primary = comparison[comparison.view.eq("exact_paired")].set_index("kind")
    yearly = pd.read_csv(out / "yearly_metrics.csv")
    subgroups = json.loads((out / "subgroup_metrics.json").read_text(encoding="utf-8"))
    fits = json.loads((out / "origin_fits.json").read_text(encoding="utf-8"))
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False, "svg.fonttype": "path", "svg.hashsalt": "quota-20261024", "font.size": 10})
    kinds = ["baseline_v6", "strict_ordinary__level_change__sd10", "special_scope_sensitivity__level_change__sd10"]
    colors = ["#334155", "#0F766E", "#B45309"]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.7), gridspec_kw={"width_ratios": [1.25, 1]})
    for kind, color in zip(kinds, colors):
        values = yearly[yearly.view.eq("exact_paired") & yearly.kind.eq(kind)].sort_values("year")
        axes[0].plot(values.year, values.mae, marker="o", color=color, label=LABELS[kind],
            linewidth=1.8, linestyle="--" if kind.startswith("strict") else "-")
    axes[0].set_xticks([2024, 2025, 2026])
    axes[0].set_ylabel("P50 的 MAE（分，越低越好）")
    axes[0].set_xlabel("时间外预测年份（每年样本数 10 / 27 / 17）")
    axes[0].set_title("同一批经验 Q10：名额未带来稳定提升", pad=14)
    axes[0].legend(fontsize=8.5, loc="upper left")
    axes[0].set_ylim(9.8, 19.8)
    axes[0].grid(axis="y", alpha=.18)
    total = int(primary.loc["baseline_v6", "n"])
    amounts = [int(primary.loc[k, "quota_observed_rows"]) for k in kinds[1:]]
    missing = [total - v for v in amounts]
    ypos = np.arange(2)
    axes[1].barh(ypos, amounts, color=colors[1:], height=.46, label="名额与标签可连接")
    axes[1].barh(ypos, missing, left=amounts, color="#E2E8F0", height=.46, label="仍缺可用名额")
    for i, (kind, count) in enumerate(zip(kinds[1:], amounts)):
        school_count = int(primary.loc[kind, "quota_observed_schools"])
        axes[1].text(total / 2, i, f"{count} / {total} 校年，{school_count} 所学校", ha="center", va="center", color="#1E293B")
    axes[1].set_yticks(ypos, ["严格普通统考净额", "专项口径放宽（仅敏感性）"])
    axes[1].invert_yaxis()
    axes[1].set_xlim(0, total)
    axes[1].set_xticks([0, 10, 20, 30, 40, 54])
    axes[1].set_xlabel("同一组 54 个经验 Q10 时间外校年")
    axes[1].set_title("识别能力受资料覆盖约束", pad=14)
    axes[1].legend(fontsize=8.5, loc="upper center", bbox_to_anchor=(.5, -.17), ncol=2)
    for ax in axes:
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    fig.text(.5, .015, "严格名额与基线曲线基本重合；不能据此认定名额无效，也不能把专项待核数据当作普通净额。", ha="center", fontsize=9, color="#475569")
    fig.tight_layout(rect=(0, .07, 1, 1))
    svg_path = out / "quota_backtest_diagnostics.svg"
    fig.savefig(svg_path, bbox_inches="tight", metadata={"Date": None})
    # Matplotlib path serialization leaves trailing spaces; normalize generated
    # XML only, preserving whitespace separators inside multiline SVG paths.
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    fig.savefig(out / "quota_backtest_diagnostics.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    baseline = primary.loc["baseline_v6"]
    strict = primary.loc[kinds[1]]
    relaxed = primary.loc[kinds[2]]
    lines = [
        "# 报名截止前可见净名额的研究性回测", "",
        "结论：当年名额已作为研究变量接入，但当前资料未提供足以替换正式模型的预测增益。正式模型、2027 冻结预测、网页与论文数值不变。", "",
        "## 1. 数据接入结果", "",
        "使用已发布的 `data-quota-20261023-r2` 固定快照，对全部 436 条记录逐条作两套适用性判断，形成 872 行审计台账。", "",
        "- 严格普通净额：7 个校年满足来源/时点/普通专项口径，其中中央财经大学 2022—2027 的 6 个可连接现有院校标签；厦门大学 2027 的单学院名额不能强接到多学院学校标签。历史可连接值为 5 个校年。",
        "- 专项未清敏感性：27 条原文已核记录、24 个校年；显式单位连接后为 4 校 17 个校年，其中历史为 13 个。不能将这批值称为已核定普通统考净额。",
        "- 在 2024—2026 的 226 个可评价校年内，严格名额仅覆盖中央财经大学 3 条：其中 2024 是代理，2025/2026 是审计通过经验 Q10。因此主比较真正有严格名额的只有 2/54、1 所学校。敏感性主比较覆盖 6/54、3 所学校。",
        "- 其余已审计数据仍参与模型训练、代理误差估计或单独评分；349 条规则候选、未知发布日期、截止后修订附件和单位口径不明的记录保留排除理由，不因想扩大样本而补零或放行。", "",
        "培养单位连接采用显式同义映射；南京大学旧称数学系、新称数学学院，西南财经大学旧称统计学院、新称统计与数据科学学院。未核清学校级多学院标签前，不汇总不同学院名额。未取得当年网页存档的历史记录仍只是现存官方公告日期下的回溯重建，不是完整的历史资料版本。", "",
        "## 2. 实验方法", "",
        "以 V6 观测误差随机截距作为研究基线。每个原点仅使用此前标签，优先使用经验 Q10，同校年的代理不重复入模；观测误差参数、REML 方差、特征中心均在训练窗重估。当年特征仅依赖该年报名截止前可见的官方剩余净额或同范围总计划减实际接收推免，绝不采用最终录取人数、拟推免人数或上一年名额代替。", "",
        "名额以 log2 水平和相邻年 log2 比值进入正则化协变量；缺失值保持 NaN，设计矩阵零代表不添加数量调整，并另有可得性标记。零均值系数先验在 `X D Xᵀ` 中一次性积分，系数与截距不确定性进入预测，方差超参数仍为经验贝叶斯插件估计。数量系数标准差固定 10 分/翻倍，另作 5/20 敏感性；标记标准差固定 5 分，不根据本轮外层结果选模型或继续调参。", "",
        "两种资料口径分别比较仅可得性、仅水平、仅变化、水平加变化，加上两种先验敏感性，共 12 个候选；另有共同基线。3 个原点完成 36 次候选拟合。该设计是已知旧结果后的回溯比较，不称预注册或盲测。", "",
        "## 3. 同一组 54 个经验 Q10 校年的主结果", "",
        "| 模型 | MAE（分） | WIS ↓ | P90 覆盖 | 平均 P90−P50 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for kind, label in LABELS.items():
        row = primary.loc[kind]
        lines.append(f"| {label} | {row.mae:.3f} | {row.wis:.3f} | {row.q90_coverage:.1%} | {row.q90_minus_q50:.2f} |")
    lines.extend(["", "这里的基线是论文中的 V6 研究候选，不是网页当前冻结正式预测。冻结正式模型在同一 54 条上的 MAE=15.83、WIS=10.77；V5 增强为 14.90、10.81。不能把新名额候选与较弱旧模型比较后，把 V6 本身的改进全部记为名额贡献。", "",
        f"预设严格口径全特征相对基线的 MAE 差为 {strict.mae-baseline.mae:+.4f} 分，WIS 差为 {strict.wis-baseline.wis:+.4f}；实际可用性上基本没有变化。专项口径放宽后的全特征 MAE 恶化 {relaxed.mae-baseline.mae:.2f} 分，WIS 恶化 {relaxed.wis-baseline.wis:.2f}。", "",
        "所有候选的总体 P90 覆盖都为 50/54，2026 仍只有 14/17；区间没有变成更可靠的 90% 保证。覆盖率相同并不表示分布一样，应同时比较 WIS、pinball 和宽度。", "",
        "![名额回测的年度误差与资料覆盖](quota_backtest_diagnostics.svg)", "",
        "图读取本轮模型输出：左图显示三年误差及严格口径几乎重合的曲线，右图显示精确标签与净名额的真实交集。", "",
        "## 4. 有名额的子集与先验敏感性", "",
        "| 名额覆盖子集 | 校年/学校 | 基线 MAE | 加名额 MAE | 基线 WIS | 加名额 WIS |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for kind, label in ((kinds[1], "严格普通净额"), (kinds[2], "专项待核敏感性")):
        value = next(r for r in subgroups if r["kind"] == kind and r["view"] == "exact_paired" and r["subset"] == "quota_observed")
        a, b = value["candidate"], value["baseline"]
        lines.append(f"| {label} | {a['n']}/{a['schools']} | {b['mae']:.2f} | {a['mae']:.2f} | {b['wis']:.2f} | {a['wis']:.2f} |")
    lines.extend(["", "严格子集只有中财 2025/2026 两次，不能计算有全国泛化含义的学校簇置信区间。专项待核子集的学校簇与年份整块重抽结果保留在 `paired_uncertainty.json`，仅描述现有组合；只有三个日历年，不将 54 校年当作 54 次独立年份冲击。", "",
        "| 资料口径 | 系数先验标准差 | MAE | WIS |",
        "| --- | ---: | ---: | ---: |"])
    for policy, label in (("strict_ordinary", "严格普通净额"), ("special_scope_sensitivity", "专项待核")):
        for sd in (5, 10, 20):
            r = primary.loc[f"{policy}__level_change__sd{sd}"]
            lines.append(f"| {label} | {sd} | {r.mae:.4f} | {r.wis:.4f} |")
    lines.extend(["", "严格口径在放宽先验至 20 时有约 0.005 分的微小 MAE 下降，不作为有效改进、不据此改选 20。它小于可支持的实用差异，且仅一校可识别。专项待核口径随正则化减弱而变差，提示在当前小样本下放大数量系数会增加过拟合风险；这不是名额变量在更完整数据上无效的证据。", "",
        "## 5. 暂不晋级与后续补数顺序", "",
        "所有候选均未达到预设的至少 20 个名额覆盖精确时间外校年、5 校、2 年和 10% 覆盖的最低独立性护栏；默认全特征也未实现至少 2% 的 WIS 改善。结论是**当前证据不足、先保留研究模块**，而不是删除名额变量，也不是宣布名额无效。正式模型不替换，网页和毕业论文的正式数值不追认这些候选。", "",
        "下一步优先补能扩大独立识别的信息：", "",
        "1. 先补有逐人经验 Q10 的学校同年名额，尤其上海交大、南京大学的专项扣除明细；这比随机新增无法和标签连接的名额更有效。",
        "2. 对多学院学校恢复学院级名单标签，再连接各自计划、实际推免与专项，不强行求和投到学校最高门槛。",
        "3. 恢复较早年份的官方附件和版本日期，使同校名额变动有更多时间点，并保留计划到最终人数的历史修订作为另一变量。",
        "4. 数据覆盖足够后再评估同校内名额变化、学校间规模与事件交互；仅有单校时不估全国扩缩招弹性，不通过换复杂模型掩盖不可识别。", "",
        "## 6. 复现与核验", "",
        "全部数据为公开校年聚合，不读取逐人私有名单。回测保留全部 226 个可评价校年（54 个经验 Q10、172 个代理）的同一原点预测，每个模型单独评分；代理改善不冒充经验 Q10 改善。77 个已审计分布在各训练原点前按时间使用，不为了扩大测试量把训练年份算作测试。", "",
        "```powershell", "python -m pip install -r model/requirements-deadline-quota.txt",
        "python -m unittest discover -s model -v",
        "python model/experiment_deadline_quota.py",
        "python model/verify_deadline_quota_experiment.py",
        "python model/report_deadline_quota.py",
        "python model/verify_frozen_forecast_outputs.py", "```", "",
        f"本次实际环境：Python {summary['environment']['python']}，" + "，".join(f"{k} {v}" for k, v in summary['environment'].items() if k != "python") + "。统计主计算无随机抽样，整簇重抽种子为 20261024；依赖版本单独锁定，不改原生产依赖。", "",
        f"核验结果：{validation['checks']} 项结果/时点/哈希检查通过；36 个候选拟合全部收敛。独立沿用旧 V6 评分函数重算 MAE/WIS。既有 V6 三原点所有分位复现最大差小于 1e-4，实际最大约 5.7e-14。十个正式冻结数值文件哈希全部不变。模型目录 35 项测试通过，其中本轮新增 20 项，覆盖截止时钟、组件后修订、实际与拟推免区分、缺失保留、单位错配、未来隔离和基线等价。", "",
        "输入路径、SHA256、运行环境和基础提交见 `summary.json`；同时保存原字节和统一 LF 后的文本哈希，以识别 Git 在 Windows/Linux 检出时的纯换行差别，原始官方证据文件哈希不作该转换。每个原点的系数后验、方差和训练覆盖见 `origin_fits.json`。系数为正则化预测关联，不是因果效应。源证据 URL 和定位见 `record_eligibility.csv`；原记录的生产准入标记保持不变。", "",
        "完整方案见 [回测方案](../../../docs/deadline_quota_backtest_protocol_20261024.md)，基础资料口径见 [R2 数据审计](../../../docs/quota_deadline_collection_20261023_r2.md)。",
    ])
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out / "README.md"), "figure": str(out / "quota_backtest_diagnostics.svg"),
        "no_model_selected": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
