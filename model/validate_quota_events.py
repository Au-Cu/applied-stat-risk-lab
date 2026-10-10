"""Validate the public quota-event table and emit an auditable report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quota_features import DEFAULT_PATH, load_quota_events, quota_coverage, validate_quota_events


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "data" / "audit" / "quota_quality.json"


def main() -> int:
    raw = pd.read_csv(DEFAULT_PATH, encoding="utf-8")
    report = validate_quota_events(raw)
    strict = load_quota_events(strict=True)
    window = load_quota_events(strict=True, include_registration_window=True)
    report["strict_policy"] = quota_coverage(strict)
    report["registration_window_sensitivity"] = quota_coverage(window)
    report["policy_notes"] = [
        "严格模型只接受正式报名开始前发布且 model_eligible=true 的记录。",
        "registration_window 记录仅用于敏感性分析，不进入生产特征。",
        "published_regular_quota 优先；只有总计划与推免/专项扣除可核实时才推导统考名额。",
    ]
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
