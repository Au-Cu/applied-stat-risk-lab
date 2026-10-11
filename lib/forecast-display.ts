/** Display policy only: the frozen forecast and interpolation are not refitted.
 * Upper anchors include safety adjustments, so this is a risk scale, not a
 * validated predictive CDF and never an individual's admission probability.
 */
export type RiskScaleItem = {
  q05: number;
  q95: number;
  upperWidthStatus: "information_limited" | "decision_informative";
};

export function riskScaleLabel(item: RiskScaleItem, score: number, scale: number) {
  if (item.upperWidthStatus === "information_limited") return "不宜精算";
  if (score <= item.q05) return "≤5%";
  if (score >= item.q95) return "≥95%";
  return `约${Math.round(scale * 100)}%`;
}

export function riskLabel(scale: number, informationLimited = false) {
  if (informationLimited) return { label: "需复核", tone: "watch" };
  if (scale >= 0.95) return { label: "保", tone: "safe" };
  if (scale >= 0.9) return { label: "稳", tone: "steady" };
  if (scale >= 0.6) return { label: "观察", tone: "watch" };
  return { label: "冲", tone: "reach" };
}
