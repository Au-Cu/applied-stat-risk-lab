"""Layered handling of de-identified candidate-level initial scores.

Rows enter the exact-label layer only after the roster-derived population
passes an approved reconciliation tier.  The preferred tier matches an
independently compiled count/minimum/median/maximum; legacy rosters may instead
pass count plus all available summaries together with explicit legend,
monotone-score, rank-coverage, and OCR-confidence checks.  The module also
reports non-parametric sampling uncertainty for the empirical P10; it never
treats a minimum score or an unreconciled roster as an exact label.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "private" / "candidate_initial_scores.csv"
DEFAULT_IMAGE_AUDIT = ROOT / "data" / "processed" / "roster_ocr_audit.csv"
DEFAULT_PROGRAM_AUDIT = ROOT / "data" / "processed" / "candidate_label_audit.csv"
TARGET_MAJOR = "025200"
ALLOWED_TYPES = {"normal_exam", "recommended", "special", "adjustment", "unknown"}
REQUIRED_COLUMNS = [
    "school",
    "year",
    "major_code",
    "study_mode",
    "candidate_type",
    "initial_score",
    "special_plan",
    "adjustment_status",
    "full_time",
    "label_available_date",
    "source_url",
    "model_eligible",
]


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "可用"}


def load_candidate_scores(path: Path | str = DEFAULT_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    frame = pd.read_csv(path, encoding="utf-8")
    for column in REQUIRED_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    frame["major_code"] = frame["major_code"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
    frame["initial_score"] = pd.to_numeric(frame["initial_score"], errors="coerce")
    frame["full_time"] = frame["full_time"].map(_bool)
    frame["model_eligible"] = frame["model_eligible"].map(_bool)
    return frame


def audited_candidate_pool(
    frame: pd.DataFrame | None = None,
    *,
    image_audit_path: Path | str = DEFAULT_IMAGE_AUDIT,
    program_audit_path: Path | str = DEFAULT_PROGRAM_AUDIT,
) -> pd.DataFrame:
    """Return exact rows plus lower-weight, internally coherent roster rows.

    A failed exact-label reconciliation does not imply that every readable
    score in the roster is useless.  This pool therefore preserves two roles:

    * ``exact`` rows come only from programme-years that passed the formal
      label gate and retain weight 1;
    * ``soft_roster`` rows come from parsed target-major/full-time rosters with
      an explicit admission legend, monotone score order, no asset-level
      special population, and adequate OCR confidence.  Their school-year
      weight is reduced by count and summary discrepancies.

    Soft rows may be used to estimate distributional shape or as noisy
    observations in separately validated experiments.  They must never be
    reported as exact Q10 labels.
    """

    if frame is None:
        frame = load_candidate_scores()
    if frame.empty:
        return pd.DataFrame()
    image_path = Path(image_audit_path)
    program_path = Path(program_audit_path)
    if not image_path.exists() or not program_path.exists():
        return pd.DataFrame()
    images = pd.read_csv(image_path, encoding="utf-8-sig")
    programs = pd.read_csv(program_path, encoding="utf-8-sig")
    for column in (
        "target_major_match",
        "special_population_flag",
        "score_order_monotone",
        "selected_for_exact_label",
    ):
        if column in images:
            images[column] = images[column].map(_bool)
    soft_image_ok = (
        images["layout_status"].eq("parsed")
        & images["target_major_match"]
        & ~images["special_population_flag"]
        & images["highlight_rule"].ne("unknown")
        & images["score_order_monotone"]
        & pd.to_numeric(images["score_ocr_confidence_median"], errors="coerce").ge(0.85)
    )
    # A programme-level exact reconciliation outranks any single image-level
    # heuristic.  Retain those selected assets even when, for example, the
    # median per-row OCR confidence is just below the auxiliary soft threshold.
    image_ok = images["selected_for_exact_label"] | soft_image_ok
    image_columns = [
        "school",
        "year",
        "source_url",
        "source_sha256",
        "selected_for_exact_label",
        "score_ocr_confidence_median",
    ]
    usable_images = images.loc[image_ok, image_columns].drop_duplicates(
        ["school", "year", "source_url", "source_sha256"]
    )
    pool = frame.copy()
    for column in ("full_time", "special_plan", "model_eligible"):
        pool[column] = pool[column].map(_bool)
    pool["initial_score"] = pd.to_numeric(pool["initial_score"], errors="coerce")
    pool = pool.merge(
        usable_images,
        on=["school", "year", "source_url", "source_sha256"],
        how="inner",
        suffixes=("", "_image"),
    )
    pool = pool[
        pool["major_code"].eq(TARGET_MAJOR)
        & pool["full_time"]
        & ~pool["special_plan"]
        & pool["initial_score"].notna()
    ].copy()
    if pool.empty:
        return pool
    pool = pool.drop_duplicates(["source_sha256", "row_index", "initial_score"])
    programme_columns = [
        "school",
        "year",
        "validation_pass",
        "validation_tier",
        "reference_n",
        "reference_min",
        "reference_median",
        "reference_max",
        "extracted_n",
        "extracted_min",
        "extracted_median",
        "extracted_max",
        "model_n",
    ]
    pool = pool.merge(programs[programme_columns], on=["school", "year"], how="left")
    pool["validation_pass"] = pool["validation_pass"].map(_bool)
    exact_keys = {
        (str(school), int(year))
        for school, year in zip(
            pool.loc[pool["model_eligible"], "school"],
            pool.loc[pool["model_eligible"], "year"],
        )
    }
    exact_group = pd.Series(
        [(str(school), int(year)) in exact_keys for school, year in zip(pool["school"], pool["year"])],
        index=pool.index,
    )
    # When a school-year has an exact population, keep only those selected
    # rows; otherwise non-selected parallel images could duplicate cohorts.
    pool = pool[~exact_group | pool["model_eligible"]].copy()
    exact_group = pool["model_eligible"]
    reference_n = pd.to_numeric(pool["reference_n"], errors="coerce")
    extracted_n = pd.to_numeric(pool["extracted_n"], errors="coerce")
    count_discrepancy = ((extracted_n - reference_n).abs() / reference_n.clip(lower=1)).fillna(0.25)
    differences = []
    for name in ("min", "median", "max"):
        reference = pd.to_numeric(pool[f"reference_{name}"], errors="coerce")
        extracted = pd.to_numeric(pool[f"extracted_{name}"], errors="coerce")
        differences.append((extracted - reference).abs())
    summary_difference = pd.concat(differences, axis=1).mean(axis=1, skipna=True).fillna(5.0)
    confidence = pd.to_numeric(pool["score_ocr_confidence_median"], errors="coerce").fillna(0.85)
    soft_weight = (
        0.55
        * np.exp(-4.0 * count_discrepancy.to_numpy(float))
        * np.exp(-summary_difference.to_numpy(float) / 12.0)
        * np.clip((confidence.to_numpy(float) - 0.75) / 0.20, 0.25, 1.0)
    )
    pool["programme_evidence_weight"] = np.where(
        exact_group,
        1.0,
        np.clip(soft_weight, 0.10, 0.55),
    )
    pool["candidate_evidence_tier"] = np.where(exact_group, "exact", "soft_roster")
    pool["candidate_population_role"] = np.where(
        exact_group,
        "exact_q10_and_distribution",
        "distribution_shape_or_noisy_label_only",
    )
    return pool.reset_index(drop=True)


def validate_candidate_scores(frame: pd.DataFrame) -> dict:
    errors: list[dict] = []
    warning_rows: dict[str, list[int]] = defaultdict(list)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        errors.append({"type": "missing_columns", "columns": missing})
        return {"rows": len(frame), "errors": errors, "warnings": [], "status": "error"}
    for index, row in frame.iterrows():
        if str(row.get("major_code", "")) != TARGET_MAJOR:
            warning_rows["out_of_scope_major"].append(int(index))
        if row.get("candidate_type") not in ALLOWED_TYPES:
            errors.append({"type": "invalid_candidate_type", "row": int(index)})
        score = row.get("initial_score")
        if pd.notna(score) and not (0 <= float(score) <= 500):
            errors.append({"type": "score_out_of_range", "row": int(index), "value": float(score)})
        eligible = _bool(row.get("model_eligible"))
        normal = row.get("candidate_type") == "normal_exam"
        if eligible and (not normal or not _bool(row.get("full_time")) or _bool(row.get("special_plan"))):
            errors.append({"type": "eligible_population_mismatch", "row": int(index)})
        if eligible and not str(row.get("source_url", "")).startswith(("http://", "https://")):
            errors.append({"type": "eligible_without_source", "row": int(index)})
        if not eligible:
            warning_rows["not_used_for_exact_label"].append(int(index))
    warnings = [
        {
            "type": warning_type,
            "count": len(rows),
            "example_rows": rows[:20],
        }
        for warning_type, rows in sorted(warning_rows.items())
    ]
    return {
        "rows": int(len(frame)),
        "eligible_rows": int(sum(_bool(value) for value in frame["model_eligible"])),
        "exact_candidate_rows": int(sum(_bool(value) and typ == "normal_exam" for value, typ in zip(frame["model_eligible"], frame["candidate_type"]))),
        "errors": errors,
        "warnings": warnings,
        "status": "error" if errors else ("warning" if warnings else "ok"),
    }


def exact_q10_by_program(
    frame: pd.DataFrame | None = None,
    *,
    minimum_n: int = 10,
    bootstrap_draws: int = 2000,
) -> pd.DataFrame:
    """Return empirical P10 and bootstrap sampling uncertainty.

    Bootstrap seeds are deterministic by school and year, so the uncertainty
    summary is reproducible while remaining independent across program-years.
    """

    if frame is None:
        frame = load_candidate_scores()
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "school",
                "year",
                "q10_exact",
                "candidate_n",
                "q10_bootstrap_sd",
                "q10_bootstrap_p05",
                "q10_bootstrap_p95",
                "label_tier",
            ]
        )
    frame = frame.copy()
    for column in ("model_eligible", "full_time", "special_plan"):
        if column in frame:
            frame[column] = frame[column].map(_bool)
    if "initial_score" in frame:
        frame["initial_score"] = pd.to_numeric(frame["initial_score"], errors="coerce")
    clean = frame[
        frame["model_eligible"]
        & frame["candidate_type"].eq("normal_exam")
        & frame["full_time"]
        & ~frame["special_plan"].map(_bool)
        & frame["initial_score"].notna()
        & frame["school"].notna()
    ].copy()
    rows = []
    for (school, year), group in clean.groupby(["school", "year"], dropna=False):
        scores = group["initial_score"].astype(float).to_numpy()
        if len(scores) < minimum_n:
            continue
        seed_bytes = hashlib.sha256(f"{school}|{int(year)}".encode("utf-8")).digest()[:8]
        rng = np.random.default_rng(int.from_bytes(seed_bytes, "big", signed=False))
        if bootstrap_draws > 0:
            resampled = scores[rng.integers(0, len(scores), size=(bootstrap_draws, len(scores)))]
            bootstrap_q10 = np.quantile(resampled, 0.10, axis=1, method="linear")
            bootstrap_sd = float(np.std(bootstrap_q10, ddof=1))
            bootstrap_p05, bootstrap_p95 = np.quantile(bootstrap_q10, [0.05, 0.95])
        else:
            bootstrap_sd = np.nan
            bootstrap_p05 = np.nan
            bootstrap_p95 = np.nan
        rows.append({
            "school": school,
            "year": int(year),
            "q10_exact": float(np.quantile(scores, 0.10, method="linear")),
            "candidate_n": int(len(scores)),
            "q10_bootstrap_sd": bootstrap_sd,
            "q10_bootstrap_p05": float(bootstrap_p05),
            "q10_bootstrap_p95": float(bootstrap_p95),
            "label_tier": "exact_candidate_scores",
        })
    return pd.DataFrame(rows)


def candidate_distribution_by_program(
    frame: pd.DataFrame | None = None,
    *,
    minimum_n: int = 10,
    bootstrap_draws: int = 2000,
) -> pd.DataFrame:
    """Summarise the full admitted-score distribution for audited program-years.

    This is deliberately richer than an exact P10 table.  The output contains
    only school-year aggregates, so it can be used in public diagnostics while
    the de-identified candidate rows remain in ``data/private``.  A row is
    included only when the same population gate used by ``exact_q10_by_program``
    is satisfied.  Finite-sample uncertainty for P10 is carried forward from a
    deterministic non-parametric bootstrap.
    """

    if frame is None:
        frame = load_candidate_scores()
    if frame.empty:
        return pd.DataFrame()
    clean = frame.copy()
    for column in ("model_eligible", "full_time", "special_plan"):
        if column in clean:
            clean[column] = clean[column].map(_bool)
    clean["initial_score"] = pd.to_numeric(clean["initial_score"], errors="coerce")
    clean = clean[
        clean["model_eligible"]
        & clean["candidate_type"].eq("normal_exam")
        & clean["full_time"]
        & ~clean["special_plan"]
        & clean["initial_score"].notna()
        & clean["school"].notna()
    ].copy()

    q10_uncertainty = exact_q10_by_program(
        clean,
        minimum_n=minimum_n,
        bootstrap_draws=bootstrap_draws,
    ).set_index(["school", "year"])
    probabilities = (0.05, 0.10, 0.20, 0.25, 0.50, 0.75, 0.80, 0.90, 0.95)
    rows: list[dict] = []
    for (school, year), group in clean.groupby(["school", "year"], dropna=False):
        scores = group["initial_score"].astype(float).to_numpy()
        if len(scores) < minimum_n:
            continue
        quantiles = np.quantile(scores, probabilities, method="linear")
        q = {f"score_q{int(probability * 100):02d}": float(value) for probability, value in zip(probabilities, quantiles)}
        iqr = q["score_q75"] - q["score_q25"]
        centered = scores - float(np.mean(scores))
        sample_sd = float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0
        sample_skewness = (
            float(np.mean(centered**3) / (np.mean(centered**2) ** 1.5))
            if len(scores) > 2 and np.mean(centered**2) > 0
            else 0.0
        )
        key = (school, int(year))
        uncertainty = q10_uncertainty.loc[key]
        rows.append(
            {
                "school": school,
                "year": int(year),
                "candidate_n": int(len(scores)),
                "score_min": float(np.min(scores)),
                "score_max": float(np.max(scores)),
                "score_mean": float(np.mean(scores)),
                "score_sd": sample_sd,
                **q,
                "score_iqr": float(iqr),
                "lower_tail_span_q50_q10": float(q["score_q50"] - q["score_q10"]),
                "upper_tail_span_q90_q50": float(q["score_q90"] - q["score_q50"]),
                "bowley_skewness": float(
                    (q["score_q75"] + q["score_q25"] - 2.0 * q["score_q50"]) / iqr
                )
                if iqr > 0
                else 0.0,
                "sample_skewness": sample_skewness,
                "q10_bootstrap_sd": float(uncertainty["q10_bootstrap_sd"]),
                "q10_bootstrap_p05": float(uncertainty["q10_bootstrap_p05"]),
                "q10_bootstrap_p95": float(uncertainty["q10_bootstrap_p95"]),
                "label_tier": "exact_candidate_distribution",
            }
        )
    return pd.DataFrame(rows).sort_values(["year", "school"]).reset_index(drop=True)


def audited_distribution_by_program(
    pool: pd.DataFrame | None = None,
    *,
    minimum_n: int = 5,
    bootstrap_draws: int = 1000,
) -> pd.DataFrame:
    """Summarise exact and soft-roster programme-year distributions.

    The returned ``programme_evidence_weight`` is an observation-quality
    weight, not a claim that a soft roster is exact.  It allows experiments to
    use readable but unreconciled samples without silently upgrading them.
    """

    if pool is None:
        pool = audited_candidate_pool()
    if pool.empty:
        return pd.DataFrame()
    probabilities = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
    rows: list[dict] = []
    for (school, year), group in pool.groupby(["school", "year"], dropna=False):
        scores = pd.to_numeric(group["initial_score"], errors="coerce").dropna().to_numpy(float)
        if len(scores) < minimum_n:
            continue
        quantiles = np.quantile(scores, probabilities, method="linear")
        seed_bytes = hashlib.sha256(f"soft|{school}|{int(year)}".encode("utf-8")).digest()[:8]
        rng = np.random.default_rng(int.from_bytes(seed_bytes, "big", signed=False))
        if bootstrap_draws:
            resampled = scores[rng.integers(0, len(scores), size=(bootstrap_draws, len(scores)))]
            bootstrap_q10 = np.quantile(resampled, 0.10, axis=1, method="linear")
            bootstrap_sd = float(np.std(bootstrap_q10, ddof=1))
        else:
            bootstrap_sd = np.nan
        exact = bool(group["candidate_evidence_tier"].eq("exact").all())
        record = {
            "school": school,
            "year": int(year),
            "candidate_n": int(len(scores)),
            "candidate_evidence_tier": "exact" if exact else "soft_roster",
            "programme_evidence_weight": 1.0
            if exact
            else float(group["programme_evidence_weight"].median()),
            "q10_bootstrap_sd": bootstrap_sd,
            "score_mean": float(np.mean(scores)),
            "score_sd": float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0,
            "score_min": float(np.min(scores)),
            "score_max": float(np.max(scores)),
        }
        record.update(
            {
                f"score_q{int(probability * 100):02d}": float(value)
                for probability, value in zip(probabilities, quantiles)
            }
        )
        rows.append(record)
    return pd.DataFrame(rows).sort_values(["year", "school"]).reset_index(drop=True)


def apply_exact_candidate_labels(program_frame: pd.DataFrame, candidate_frame: pd.DataFrame | None = None):
    """Override proxy targets only where a clean exact candidate P10 exists.

    The empty current template is a no-op.  Keeping this hook in the normal
    preparation path means future official lists can improve labels without
    changing feature construction or silently mixing populations.
    """

    result = program_frame.copy()
    exact = exact_q10_by_program(candidate_frame)
    if exact.empty:
        return result, {"candidate_programs": 0, "applied_programs": 0, "applied_rows": 0}
    applied = 0
    for _, label in exact.iterrows():
        mask = result["school"].eq(label["school"]) & result["year"].eq(int(label["year"]))
        if "study_mode" in result:
            mask &= result["study_mode"].fillna("").str.contains("全日制")
        if not mask.any():
            continue
        value = float(label["q10_exact"])
        result.loc[mask, "q10_value"] = value
        result.loc[mask, "q10_method"] = "exact_candidate_scores"
        result.loc[mask, "q10_weight"] = 1.0
        result.loc[mask, "target_value"] = value
        result.loc[mask, "target_kind"] = "q10_exact"
        result.loc[mask, "target_weight"] = 1.0
        result.loc[mask, "q10_sampling_sd"] = float(label["q10_bootstrap_sd"])
        result.loc[mask, "q10_sampling_p05"] = float(label["q10_bootstrap_p05"])
        result.loc[mask, "q10_sampling_p95"] = float(label["q10_bootstrap_p95"])
        if "national_line" in result:
            result.loc[mask, "margin_q10"] = value - pd.to_numeric(result.loc[mask, "national_line"], errors="coerce")
        applied += 1
    return result, {
        "candidate_programs": int(len(exact)),
        "applied_programs": int(applied),
        "applied_rows": int(sum(result["q10_method"].eq("exact_candidate_scores"))),
    }


def recompute_exact_aware_features(program_frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute every lagged target feature after exact-label replacement.

    ``program_year.csv`` contains lags derived from the original proxy labels.
    Leaving those columns untouched would make an exact label affect the target
    but not the following year's features.  This function mirrors the temporal
    construction in ``prepare_data.py`` and must run before any backtest split.
    """

    result = program_frame.copy()
    by_school: dict[str, list[int]] = defaultdict(list)
    for index, row in result.iterrows():
        by_school[str(row["school"])].append(index)

    for indices in by_school.values():
        indices.sort(key=lambda index: int(result.at[index, "year"]))
        prior_margins: list[float] = []
        previous = None
        previous_previous = None
        for index in indices:
            row = result.loc[index]
            result.at[index, "lag1_cutoff"] = previous.get("cutoff") if previous is not None else np.nan
            result.at[index, "lag1_q10"] = previous.get("q10_value") if previous is not None else np.nan
            result.at[index, "lag1_margin_q10"] = previous.get("margin_q10") if previous is not None else np.nan
            result.at[index, "lag1_admitted_count"] = previous.get("admitted_count") if previous is not None else np.nan
            if (
                previous is not None
                and previous_previous is not None
                and pd.notna(previous.get("cutoff"))
                and pd.notna(previous_previous.get("cutoff"))
            ):
                result.at[index, "lag1_cutoff_change"] = float(previous["cutoff"] - previous_previous["cutoff"])
            else:
                result.at[index, "lag1_cutoff_change"] = np.nan
            if (
                previous is not None
                and previous_previous is not None
                and pd.notna(previous.get("margin_q10"))
                and pd.notna(previous_previous.get("margin_q10"))
            ):
                result.at[index, "lag1_margin_change"] = float(
                    previous["margin_q10"] - previous_previous["margin_q10"]
                )
            else:
                result.at[index, "lag1_margin_change"] = np.nan
            result.at[index, "trailing_margin_median"] = (
                float(np.median(prior_margins)) if prior_margins else np.nan
            )
            history_before_previous = prior_margins[:-1]
            if (
                previous is not None
                and pd.notna(previous.get("margin_q10"))
                and history_before_previous
            ):
                center = float(np.median(history_before_previous))
                deviations = np.abs(np.asarray(history_before_previous, dtype=float) - center)
                scale = float(np.median(deviations) * 1.4826) if len(deviations) >= 2 else 12.0
                scale = max(scale, 4.0)
                result.at[index, "lag1_surprise_z"] = (float(previous["margin_q10"]) - center) / scale
            else:
                result.at[index, "lag1_surprise_z"] = np.nan
            margin = row.get("margin_q10")
            if pd.notna(margin):
                prior_margins.append(float(margin))
            previous_previous = previous
            previous = row.to_dict()

    peer_groups: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
    broad_groups: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
    for _, row in result.iterrows():
        surprise = row.get("lag1_surprise_z")
        if pd.isna(surprise):
            continue
        trailing = row.get("trailing_margin_median")
        band = None if pd.isna(trailing) else int(round(float(trailing) / 20.0))
        # ``bool("False")`` is truthy in Python.  Use the same explicit
        # coercion as the candidate flags so CSV string values cannot move a
        # school into the wrong peer group.
        is_985 = int(_bool(row.get("is_985", 0)))
        peer_groups[(int(row["year"]), is_985, row.get("national_zone"), band)].append(
            (row["school"], float(surprise))
        )
        broad_groups[(int(row["year"]), is_985)].append((row["school"], float(surprise)))

    for index, row in result.iterrows():
        trailing = row.get("trailing_margin_median")
        band = None if pd.isna(trailing) else int(round(float(trailing) / 20.0))
        is_985 = int(_bool(row.get("is_985", 0)))
        candidates = [
            value
            for school, value in peer_groups.get(
                (int(row["year"]), is_985, row.get("national_zone"), band), []
            )
            if school != row["school"]
        ]
        if len(candidates) < 2:
            candidates = [
                value
                for school, value in broad_groups.get((int(row["year"]), is_985), [])
                if school != row["school"]
            ]
        result.at[index, "peer_lag1_surprise_mean"] = (
            float(np.mean(candidates)) if candidates else np.nan
        )
    return result


__all__ = [
    "DEFAULT_PATH",
    "apply_exact_candidate_labels",
    "audited_candidate_pool",
    "audited_distribution_by_program",
    "candidate_distribution_by_program",
    "exact_q10_by_program",
    "load_candidate_scores",
    "recompute_exact_aware_features",
    "validate_candidate_scores",
]
