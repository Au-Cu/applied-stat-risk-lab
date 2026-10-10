"""报名时点可见名额的审计、时间截断和特征构造。

这个模块只接受已经落入本地 CSV 的证据，不负责联网抓取。核心原则是：

* 默认只使用正式报名开始前已经发布、并且人工标记为可用的记录；
* 统考、推免和专项计划分别保留，不能用最终录取人数冒充报名时名额；
* 没有当年名额时可以回退到最近的历史公告，但必须显式记录年龄和缺失标记；
* 任何无法证明时间顺序的记录只进入审计报告，不进入严格模型。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "quota_publication_events.csv"
TARGET_MAJOR = "025200"
QUALITY_SCORE = {"A": 1.00, "B": 0.85, "C": 0.65, "D": 0.45, "": 0.35}

NUMERIC_COLUMNS = [
    "published_total_quota",
    "published_regular_quota",
    "published_recommended_quota",
    "published_special_quota",
    "quota_lower",
    "quota_upper",
]

KEY_COLUMNS = [
    "school",
    "year",
    "major_code",
    "study_mode",
    "unit_id",
    "direction_scope",
]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "可用"}


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return np.nan
    return value if math.isfinite(value) else np.nan


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ("school", "major_code", "study_mode", "unit_id", "direction_scope", "source_type", "evidence_grade", "availability_stage", "review_status", "source_url"):
        if column in frame:
            frame[column] = frame[column].fillna("").astype(str).str.strip()
    if "major_code" in frame:
        frame["major_code"] = frame["major_code"].str.replace(r"\.0$", "", regex=True).str.zfill(6)
    if "year" in frame:
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
    for column in NUMERIC_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("publish_date", "registration_start_date"):
        if column not in frame:
            frame[column] = pd.NaT
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in ("as_of_cutoff", "model_eligible"):
        if column not in frame:
            frame[column] = False
        frame[column] = frame[column].map(_as_bool)
    return frame


def validate_quota_events(frame: pd.DataFrame) -> dict:
    """Return an auditable quality report without mutating the source frame."""

    frame = _normalise(frame)
    errors: list[dict] = []
    warnings: list[dict] = []

    missing_columns = [column for column in KEY_COLUMNS + ["source_url", "publish_date", "registration_start_date"] if column not in frame.columns]
    if missing_columns:
        errors.append({"type": "missing_columns", "columns": missing_columns})

    if not frame.empty:
        duplicate_mask = frame.duplicated(KEY_COLUMNS, keep=False)
        for _, row in frame[duplicate_mask].iterrows():
            errors.append({"type": "duplicate_key", "key": {column: row.get(column) for column in KEY_COLUMNS}})

        for index, row in frame.iterrows():
            for column in NUMERIC_COLUMNS:
                value = row.get(column)
                if pd.notna(value) and float(value) < 0:
                    errors.append({"type": "negative_quota", "row": int(index), "column": column, "value": float(value)})
            total = row.get("published_total_quota")
            regular = row.get("published_regular_quota")
            recommended = row.get("published_recommended_quota")
            special = row.get("published_special_quota")
            if pd.notna(total) and pd.notna(regular) and regular > total:
                errors.append({"type": "regular_exceeds_total", "row": int(index)})
            known_parts = [value for value in (regular, recommended, special) if pd.notna(value)]
            if pd.notna(total) and known_parts and sum(known_parts) > total + 1e-9:
                errors.append({"type": "parts_exceed_total", "row": int(index), "parts_sum": float(sum(known_parts)), "total": float(total)})
            if row.get("model_eligible", False):
                publish_date = row.get("publish_date")
                registration_start = row.get("registration_start_date")
                if not row.get("as_of_cutoff", False):
                    errors.append({"type": "eligible_without_cutoff_flag", "row": int(index)})
                if str(row.get("availability_stage", "")) != "pre_registration":
                    errors.append({"type": "eligible_not_pre_registration", "row": int(index), "stage": row.get("availability_stage")})
                if pd.isna(publish_date) or pd.isna(registration_start) or publish_date >= registration_start:
                    errors.append({"type": "date_leakage_or_missing_date", "row": int(index), "publish_date": str(publish_date), "registration_start_date": str(registration_start)})
            elif str(row.get("availability_stage", "")) == "registration_window":
                publish_date = row.get("publish_date")
                registration_start = row.get("registration_start_date")
                if pd.isna(publish_date) or pd.isna(registration_start) or publish_date != registration_start:
                    warnings.append({"type": "registration_window_date_not_same_day", "row": int(index), "publish_date": str(publish_date), "registration_start_date": str(registration_start)})
            if not str(row.get("source_url", "")).startswith(("http://", "https://")):
                warnings.append({"type": "missing_source_url", "row": int(index)})
            if pd.isna(row.get("published_regular_quota")) and pd.isna(row.get("quota_lower")):
                warnings.append({"type": "no_regular_quota_or_bound", "row": int(index)})

    eligible = frame[frame.get("model_eligible", False)] if not frame.empty else frame
    return {
        "rows": int(len(frame)),
        "eligible_rows": int(len(eligible)),
        "schools": sorted(frame["school"].dropna().unique().tolist()) if "school" in frame else [],
        "years": sorted(int(value) for value in frame["year"].dropna().unique()) if "year" in frame else [],
        "duplicate_key_count": int(frame.duplicated(KEY_COLUMNS).sum()) if all(column in frame for column in KEY_COLUMNS) else None,
        "errors": errors,
        "warnings": warnings,
        "status": "error" if errors else ("warning" if warnings else "ok"),
    }


def load_quota_events(path: Path | str = DEFAULT_PATH, *, strict: bool = True, include_registration_window: bool = False) -> pd.DataFrame:
    """Load quota events and apply the chosen information-set policy.

    ``strict=True`` is the production policy. ``include_registration_window`` is
    intentionally opt-in and is used only for a sensitivity experiment.
    """

    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=KEY_COLUMNS + NUMERIC_COLUMNS)
    frame = _normalise(pd.read_csv(path, encoding="utf-8"))
    frame = frame[frame["major_code"].eq(TARGET_MAJOR)].copy()
    frame = frame[frame["study_mode"].str.contains("全日制", na=False)].copy()
    if strict:
        if include_registration_window:
            # 敏感性分析明确允许“与正式报名首日同日发布”的记录，
            # 即便它们在生产表中被标记为 model_eligible=false。
            frame = frame[frame["availability_stage"].isin(["pre_registration", "registration_window"])].copy()
        else:
            frame = frame[frame["model_eligible"] & frame["as_of_cutoff"] & frame["availability_stage"].eq("pre_registration")].copy()
    frame["_regular_value"] = frame.apply(_regular_value, axis=1)
    frame["_quality_score"] = frame["evidence_grade"].map(QUALITY_SCORE).fillna(0.35)
    return frame.sort_values(["school", "year", "publish_date"], na_position="first").reset_index(drop=True)


def _regular_value(row: pd.Series) -> float:
    direct = row.get("published_regular_quota")
    if pd.notna(direct):
        return float(direct)
    total = row.get("published_total_quota")
    if pd.isna(total):
        return np.nan
    deductions = sum(float(value) for value in (row.get("published_recommended_quota"), row.get("published_special_quota")) if pd.notna(value))
    derived = float(total) - deductions
    return derived if derived >= 0 else np.nan


def _latest_for_target(events: pd.DataFrame, school: str, target_year: int):
    candidates = events[(events["school"] == school) & (events["year"].notna()) & (events["year"].astype(int) <= int(target_year))].copy()
    if candidates.empty:
        return None, None
    candidates = candidates.sort_values(["year", "publish_date"], na_position="first")
    selected = candidates.iloc[-1]
    previous = candidates[candidates["year"].astype(int) < int(selected["year"])]
    prior = previous.iloc[-1] if not previous.empty else None
    return selected, prior


def attach_quota_features(frame: pd.DataFrame, events: pd.DataFrame | None = None, *, year_column: str = "year") -> pd.DataFrame:
    """Attach leakage-safe quota features to a school-year frame."""

    result = frame.copy()
    if events is None:
        events = load_quota_events()
    events = _normalise(events) if not events.empty else events.copy()
    if not events.empty and "_regular_value" not in events:
        events["_regular_value"] = events.apply(_regular_value, axis=1)
    output_columns = {
        "quota_regular_value": np.nan,
        "log_regular_quota": np.nan,
        "quota_shock_log": np.nan,
        "quota_age": np.nan,
        "quota_missing": 1.0,
        "quota_direct": 0.0,
        "quota_is_current": 0.0,
        "quota_quality": np.nan,
        "quota_lower": np.nan,
        "quota_upper": np.nan,
        "quota_source_year": np.nan,
        "quota_source_url": "",
        "quota_source_title": "",
        "quota_status": "未找到严格报名时点名额",
    }
    for column, default in output_columns.items():
        result[column] = default

    if events.empty or result.empty:
        return result

    for index, row in result.iterrows():
        school = str(row.get("school", ""))
        target_year = _finite(row.get(year_column))
        if not school or not np.isfinite(target_year):
            continue
        selected, prior = _latest_for_target(events, school, int(target_year))
        if selected is None:
            continue
        value = _finite(selected.get("_regular_value"))
        if not np.isfinite(value):
            continue
        prior_value = _finite(prior.get("_regular_value")) if prior is not None else np.nan
        lower = _finite(selected.get("quota_lower"))
        upper = _finite(selected.get("quota_upper"))
        if not np.isfinite(lower):
            lower = value
        if not np.isfinite(upper):
            upper = value
        result.at[index, "log_regular_quota"] = math.log1p(max(value, 0.0))
        result.at[index, "quota_regular_value"] = value
        result.at[index, "quota_shock_log"] = math.log((value + 1.0) / (prior_value + 1.0)) if np.isfinite(prior_value) else np.nan
        result.at[index, "quota_age"] = max(int(target_year) - int(selected["year"]), 0)
        result.at[index, "quota_missing"] = 0.0
        result.at[index, "quota_direct"] = 1.0 if pd.notna(selected.get("published_regular_quota")) else 0.0
        result.at[index, "quota_is_current"] = 1.0 if int(target_year) == int(selected["year"]) else 0.0
        result.at[index, "quota_quality"] = _finite(selected.get("_quality_score"))
        result.at[index, "quota_lower"] = lower
        result.at[index, "quota_upper"] = upper
        result.at[index, "quota_source_year"] = int(selected["year"])
        result.at[index, "quota_source_url"] = str(selected.get("source_url", ""))
        result.at[index, "quota_source_title"] = str(selected.get("source_title", ""))
        result.at[index, "quota_status"] = "当年严格报名前公告" if int(target_year) == int(selected["year"]) else f"沿用{int(selected['year'])}年公告（滞后{int(target_year) - int(selected['year'])}年）"
    return result


def quota_coverage(events: pd.DataFrame, frame: pd.DataFrame | None = None) -> dict:
    report = {
        "event_rows": int(len(events)),
        "eligible_event_rows": int(events["model_eligible"].sum()) if "model_eligible" in events else int(len(events)),
        "schools": int(events["school"].nunique()) if not events.empty else 0,
        "years": sorted(int(value) for value in events["year"].dropna().unique()) if not events.empty else [],
    }
    if frame is not None and not frame.empty:
        attached = attach_quota_features(frame, events)
        report["frame_rows"] = int(len(frame))
        report["frame_rows_with_quota"] = int((attached["quota_missing"] == 0).sum())
        report["frame_coverage"] = round(float((attached["quota_missing"] == 0).mean()), 4)
    return report


__all__ = [
    "DEFAULT_PATH",
    "TARGET_MAJOR",
    "attach_quota_features",
    "load_quota_events",
    "quota_coverage",
    "validate_quota_events",
]
