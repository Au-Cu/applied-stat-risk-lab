"""Extract de-identified initial scores from indexed roster images.

The source images use a regular table layout.  OCR is applied only to the
title, footer, and total-score column; names and candidate numbers are neither
read nor retained.  An admitted-score set is promoted to an exact model label
only when (a) the image itself supplies an explicit admission rule and (b) the
derived count/minimum/median/maximum reconcile with the independently compiled
school-year summary.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import get_context
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "processed" / "roster_asset_manifest.csv"
DEFAULT_INDEX = ROOT / "data" / "processed" / "mini_program_roster_index.csv"
DEFAULT_PERIODS = ROOT / "data" / "processed" / "program_year.csv"
DEFAULT_SCHOOLS = ROOT / "data" / "processed" / "schools.csv"
DEFAULT_IMAGE_AUDIT = ROOT / "data" / "processed" / "roster_ocr_audit.csv"
DEFAULT_PROGRAM_AUDIT = ROOT / "data" / "processed" / "candidate_label_audit.csv"
# Candidate-level rows remain local because a score plus school/year and public
# row order can still be linkable even after names are removed.  Only the
# aggregate program audit is suitable for the public processed-data layer.
DEFAULT_RETEST = ROOT / "data" / "private" / "retest_initial_scores.csv"
DEFAULT_CANDIDATES = ROOT / "data" / "private" / "candidate_initial_scores.csv"
DEFAULT_AUDIT = ROOT / "data" / "audit" / "candidate_score_extraction.json"

SCORE_PATTERN = re.compile(r"(?<!\d)([2-4]\d{2})(?:\.0+)?(?!\d)")
TARGET_PATTERN = re.compile(r"应用统计|应统|025200")
SPECIAL_PATTERN = re.compile(r"专项|士兵|少数民族|骨干|单独考试|推免|推荐免试|调剂")
SPECIAL_ROW_PATTERN = re.compile(r"(?:序号)?(\d{1,3})(?:号)?考生.{0,12}(?:少干|士兵|专项)")
GREEN_EXCLUDED_PATTERN = re.compile(r"绿色.{0,8}(?:未被拟录取|未拟录取|未被录取|未录取)")
GREEN_ADMITTED_PATTERN = re.compile(r"绿色.{0,8}(?:为|是)?(?:本校)?拟录取")
BLUE_EXCLUDED_PATTERN = re.compile(r"蓝色.{0,12}(?:未被拟录取|未拟录取|未被录取|未录取)")
BLUE_ADMITTED_PATTERN = re.compile(r"蓝色.{0,12}(?:为|是)?(?:本校)?拟录取")

_OCR: RapidOCR | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract privacy-preserving score rows from roster images.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--periods", type=Path, default=DEFAULT_PERIODS)
    parser.add_argument("--schools", type=Path, default=DEFAULT_SCHOOLS)
    parser.add_argument("--image-audit", type=Path, default=DEFAULT_IMAGE_AUDIT)
    parser.add_argument("--program-audit", type=Path, default=DEFAULT_PROGRAM_AUDIT)
    parser.add_argument("--retest-output", type=Path, default=DEFAULT_RETEST)
    parser.add_argument("--candidate-output", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--school")
    parser.add_argument("--year", type=int)
    return parser.parse_args()


def init_worker() -> None:
    global _OCR
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    # Four workers × two intra-op threads matches the 8 logical cores of the
    # reference machine and avoids ONNX Runtime oversubscription.
    _OCR = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def grouped_centers(indices: np.ndarray) -> list[int]:
    groups: list[list[int]] = []
    for raw in indices:
        value = int(raw)
        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [int(round(sum(group) / len(group))) for group in groups]


def normalize_ocr(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).replace("廣", "").strip()


def recognize_batch(crops: list[np.ndarray]) -> list[tuple[str, float]]:
    if not crops:
        return []
    assert _OCR is not None
    result, _ = _OCR.text_rec(crops)
    return [(normalize_ocr(item[0]), float(item[1])) for item in result]


def recognize_document(crop: np.ndarray) -> tuple[str, float]:
    """Detect and recognise multiple text boxes in a loose footer crop."""

    assert _OCR is not None
    result, _ = _OCR(crop)
    if not result:
        return "", 0.0
    texts = [normalize_ocr(item[1]) for item in result if len(item) >= 3]
    confidences = [float(item[2]) for item in result if len(item) >= 3]
    return "".join(texts), float(np.mean(confidences)) if confidences else 0.0


def title_score(value: str, school: str, year: str) -> tuple[int, int]:
    score = 0
    score += 20 if school and school.replace("大学", "") in value else 0
    score += 10 if year and year in value else 0
    score += 20 if re.search(r"复试|拟录取|录取名单", value) else 0
    score += 10 if TARGET_PATTERN.search(value) else 0
    score -= 20 if re.search(r"公众号|小程序|更多.*信息", value) else 0
    return score, len(value)


def dominant_background(image: np.ndarray) -> tuple[int, int, int, str]:
    pixels = image.reshape(-1, 3)
    bright = pixels[np.min(pixels, axis=1) > 150]
    if len(bright) < 10:
        bright = pixels
    b, g, r = np.median(bright, axis=0).astype(int).tolist()
    if g > r + 6 and g > b + 3 and max(b, g, r) - min(b, g, r) > 10:
        label = "green"
    elif b > r + 8 and b >= g - 5 and max(b, g, r) - min(b, g, r) > 10:
        label = "blue"
    elif max(b, g, r) - min(b, g, r) <= 8 and min(b, g, r) >= 235:
        label = "white"
    else:
        label = "colored"
    return r, g, b, label


def extract_image(row: dict) -> dict:
    path = ROOT / row["local_private_path"]
    output = {
        **row,
        "layout_status": "unrecognized",
        "title": "",
        "title_confidence": 0.0,
        "footer": "",
        "footer_confidence": 0.0,
        "roster_stage": "unknown",
        "highlight_rule": "unknown",
        "target_major_match": False,
        "special_population_flag": False,
        "horizontal_lines": 0,
        "vertical_lines": 0,
        "score_rows": [],
        "score_order_monotone": False,
        "rank_coverage": 0.0,
        "score_ocr_confidence_median": 0.0,
        "error": "",
    }
    try:
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("OpenCV could not decode image")
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        dark = (gray < 145).astype(np.uint8)
        horizontal = grouped_centers(np.where(dark.sum(axis=1) > width * 0.55)[0])
        # Older long screenshots align three-digit subject scores so tightly
        # that text strokes can exceed the old 24% projection threshold and be
        # mistaken for table borders.  Prefer columns spanning at least 38% of
        # the image, with the legacy threshold only as a fallback for short or
        # fragmented tables.
        vertical = grouped_centers(np.where(dark.sum(axis=0) > height * 0.70)[0])
        if len(vertical) < 2:
            vertical = grouped_centers(np.where(dark.sum(axis=0) > height * 0.38)[0])
        if len(vertical) < 2:
            vertical = grouped_centers(np.where(dark.sum(axis=0) > height * 0.24)[0])
        output["horizontal_lines"] = len(horizontal)
        output["vertical_lines"] = len(vertical)
        if len(horizontal) < 4:
            raise ValueError("fewer than four horizontal table lines")
        right_lines = [value for value in vertical if value > width * 0.60]
        if len(right_lines) < 2:
            raise ValueError("score column boundaries not found")
        x_left, x_right = right_lines[-2], right_lines[-1]
        if x_right - x_left < 35:
            raise ValueError("score column is implausibly narrow")

        title_crops = []
        for y_top, y_bottom in list(zip(horizontal, horizontal[1:]))[:5]:
            if 22 <= y_bottom - y_top <= 180:
                title_crops.append(image[y_top + 5 : y_bottom - 5, 25 : width - 25])
        title_results = recognize_batch(title_crops)
        if title_results:
            title, title_confidence = max(
                title_results,
                key=lambda item: (title_score(item[0], row["school"], str(row["year"])), item[1]),
            )
            output["title"] = title
            output["title_confidence"] = title_confidence

        footer_crops = []
        for pixels in (80, 120, 200, 280):
            crop = image[max(0, height - pixels) : height, 15 : width - 15]
            footer_crops.append(cv2.resize(crop, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC))
        footer_results = recognize_batch(footer_crops)
        if footer_results:
            footer, footer_confidence = max(
                footer_results,
                key=lambda item: (
                    (("绿色" in item[0]) or ("蓝色" in item[0])) * 10
                    + (("拟录取" in item[0]) or ("未录取" in item[0])) * 5,
                    item[1],
                ),
            )
            output["footer"] = footer
            output["footer_confidence"] = footer_confidence
        if (
            int(row.get("year") or 0) <= 2023
            and not re.search(r"绿色|蓝色|拟录取|未录取", output["footer"])
        ):
            detected_footer, detected_confidence = recognize_document(
                image[max(0, height - 220) : height, :]
            )
            if detected_footer:
                output["footer"] = detected_footer
                output["footer_confidence"] = detected_confidence

        title = output["title"]
        footer = output["footer"]
        expected_title = str(row.get("expected_title") or "")
        expected_major = str(row.get("expected_major_name") or "")
        stage_text = title if re.search(r"复试|拟录取|录取名单", title) else expected_title
        if "复试" in stage_text:
            output["roster_stage"] = "retest_roster"
        elif re.search(r"拟录取|录取名单|录取结果", stage_text):
            output["roster_stage"] = "admitted_roster"
        if GREEN_EXCLUDED_PATTERN.search(footer):
            output["highlight_rule"] = "green_excluded"
        elif GREEN_ADMITTED_PATTERN.search(footer):
            output["highlight_rule"] = "green_admitted"
        elif BLUE_EXCLUDED_PATTERN.search(footer):
            output["highlight_rule"] = "blue_excluded"
        elif BLUE_ADMITTED_PATTERN.search(footer):
            output["highlight_rule"] = "blue_admitted"
        elif output["roster_stage"] == "admitted_roster":
            output["highlight_rule"] = "all_rows_admitted"

        scope_text = title + expected_title + expected_major
        output["target_major_match"] = bool(TARGET_PATTERN.search(scope_text))
        # A footer may identify one special-plan candidate by row number.  It
        # must not disqualify the entire ordinary-exam roster.
        output["special_population_flag"] = bool(SPECIAL_PATTERN.search(scope_text))
        special_row_indices = {
            int(match.group(1)) for match in SPECIAL_ROW_PATTERN.finditer(footer)
        }

        band_meta = []
        score_crops = []
        rank_crops = []
        read_rank_column = int(row.get("year") or 0) <= 2023 or bool(special_row_indices)
        for band_index, (y_top, y_bottom) in enumerate(zip(horizontal, horizontal[1:])):
            if not 20 <= y_bottom - y_top <= 190:
                continue
            column_width = x_right - x_left
            inset = max(4, min(18, int(column_width * 0.12)))
            crop = image[y_top + 5 : y_bottom - 5, x_left + inset : x_right - inset]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            if read_rank_column:
                rank_left, rank_right = vertical[0], vertical[1]
                rank_width = rank_right - rank_left
                rank_inset = max(3, min(12, int(rank_width * 0.10)))
                rank_crop = image[
                    y_top + 4 : y_bottom - 4,
                    rank_left + rank_inset : rank_right - rank_inset,
                ]
                rank_crop = cv2.resize(rank_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            background = dominant_background(image[y_top + 4 : y_bottom - 4, x_left + 4 : x_right - 4])
            score_crops.append(crop)
            if read_rank_column:
                rank_crops.append(rank_crop)
            band_meta.append((band_index, y_top, y_bottom, background))

        if read_rank_column:
            combined_results = recognize_batch(score_crops + rank_crops)
            score_results = combined_results[: len(score_crops)]
            rank_results = combined_results[len(score_crops) :]
        else:
            score_results = recognize_batch(score_crops)
            rank_results = [("", 0.0)] * len(score_results)
        extracted = []
        for meta, (ocr_text, confidence), (rank_text, rank_confidence) in zip(
            band_meta, score_results, rank_results
        ):
            match = SCORE_PATTERN.search(ocr_text)
            if not match:
                continue
            score = int(match.group(1))
            if not 180 <= score <= 500:
                continue
            rank_match = re.search(r"(?<!\d)(\d{1,3})(?:\*)?(?!\d)", rank_text)
            display_rank = int(rank_match.group(1)) if rank_match else None
            band_index, y_top, y_bottom, background = meta
            r, g, b, highlight = background
            # An explicit colour legend is stronger than a generic title such
            # as "录取结果名单".  Several 2022-2023 tables list all candidates
            # and mark the non-admitted rows inside an otherwise admitted-stage
            # image.
            if output["highlight_rule"] == "green_excluded":
                admission_status = "not_admitted" if highlight == "green" else "admitted"
            elif output["highlight_rule"] == "green_admitted":
                admission_status = "admitted" if highlight == "green" else "not_admitted"
            elif output["highlight_rule"] == "blue_excluded":
                admission_status = "not_admitted" if highlight == "blue" else "admitted"
            elif output["highlight_rule"] == "blue_admitted":
                admission_status = "admitted" if highlight == "blue" else "not_admitted"
            elif output["roster_stage"] == "admitted_roster":
                admission_status = "admitted"
            else:
                admission_status = "unknown"
            extracted.append(
                {
                    "band_index": band_index,
                    "y_top": y_top,
                    "y_bottom": y_bottom,
                    "initial_score": score,
                    "ocr_confidence": confidence,
                    "ocr_text": ocr_text,
                    "display_rank": display_rank,
                    "rank_was_ocr": display_rank is not None,
                    "rank_ocr_confidence": rank_confidence,
                    "special_row": display_rank in special_row_indices,
                    "background_rgb": f"{r},{g},{b}",
                    "highlight": highlight,
                    "admission_status": admission_status,
                }
            )
        for ordinal, score_row in enumerate(extracted, start=1):
            if score_row["display_rank"] is None:
                score_row["display_rank"] = ordinal
            if score_row["display_rank"] in special_row_indices:
                score_row["special_row"] = True
        score_values = [row["initial_score"] for row in extracted]
        nonincreasing = all(left >= right for left, right in zip(score_values, score_values[1:]))
        nondecreasing = all(left <= right for left, right in zip(score_values, score_values[1:]))
        output["score_order_monotone"] = bool(score_values and (nonincreasing or nondecreasing))
        output["rank_coverage"] = (
            float(np.mean([row["rank_was_ocr"] for row in extracted]))
            if extracted
            else 0.0
        )
        output["score_ocr_confidence_median"] = (
            float(np.median([row["ocr_confidence"] for row in extracted]))
            if extracted
            else 0.0
        )
        output["score_rows"] = extracted
        output["layout_status"] = "parsed"
    except Exception as exc:
        output["error"] = f"{type(exc).__name__}: {exc}"
    return output


def numeric(value):
    value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(value) else float(value)


def subset_metrics(rows: list[dict]) -> dict:
    values = np.array([float(row["initial_score"]) for row in rows], dtype=float)
    if not len(values):
        return {"n": 0, "min": None, "median": None, "max": None, "q10": None}
    return {
        "n": int(len(values)),
        "min": float(np.min(values)),
        "median": float(np.median(values)),
        "max": float(np.max(values)),
        "q10": float(np.quantile(values, 0.10, method="linear")),
    }


def match_penalty(metrics: dict, reference: dict) -> float:
    penalty = 0.0
    if reference["n"] is not None:
        penalty += abs(metrics["n"] - reference["n"]) * 20.0
    for key in ("min", "median", "max"):
        if reference[key] is not None and metrics[key] is not None:
            penalty += abs(metrics[key] - reference[key])
    return float(penalty)


def exact_match(metrics: dict, reference: dict) -> bool:
    # Preferred promotion path: all four independently compiled summaries
    # exist and agree.  Legacy rosters with incomplete summaries are handled
    # separately by ``structural_exact_match`` and must satisfy additional
    # layout, rank, monotonicity, legend, and OCR-confidence checks.
    if any(reference[key] is None for key in ("n", "min", "median", "max")):
        return False
    if metrics["n"] != int(reference["n"]):
        return False
    tolerances = {"min": 0.51, "median": 0.76, "max": 0.51}
    comparisons = []
    for key, tolerance in tolerances.items():
        comparisons.append(metrics[key] is not None and abs(metrics[key] - reference[key]) <= tolerance)
    return all(comparisons)


def available_summary_match(metrics: dict, reference: dict) -> bool:
    if reference["n"] is None or metrics["n"] != int(reference["n"]):
        return False
    tolerances = {"min": 0.51, "median": 0.76, "max": 0.51}
    available = [key for key in tolerances if reference[key] is not None]
    if not available:
        return False
    return all(
        metrics[key] is not None and abs(metrics[key] - reference[key]) <= tolerances[key]
        for key in available
    )


def structural_exact_match(
    metrics: dict,
    model_metrics: dict,
    reference: dict,
    assets: list[dict],
) -> bool:
    """Fallback gate for legacy rosters with incomplete independent summaries."""

    count_matches = reference["n"] is not None and int(reference["n"]) in {
        int(metrics["n"]),
        int(model_metrics["n"]),
    }
    tolerances = {"min": 0.51, "median": 0.76, "max": 0.51}
    available = [key for key in tolerances if reference[key] is not None]
    source_summaries_match = all(
        metrics[key] is not None and abs(metrics[key] - reference[key]) <= tolerances[key]
        for key in available
    )
    ordinary_summaries_match = all(
        model_metrics[key] is not None
        and abs(model_metrics[key] - reference[key]) <= tolerances[key]
        for key in available
    )
    if not count_matches or not available or not (
        source_summaries_match or ordinary_summaries_match
    ):
        return False
    if not assets:
        return False
    for asset in assets:
        if asset["highlight_rule"] == "unknown":
            return False
        if not asset["score_order_monotone"]:
            return False
        if float(asset["rank_coverage"]) < 0.90:
            return False
        if float(asset["score_ocr_confidence_median"]) < 0.85:
            return False
    return True


def candidate_combinations(assets: list[dict]) -> list[tuple[tuple[int, ...], list[dict]]]:
    usable = []
    for index, asset in enumerate(assets):
        if not asset["target_major_match"] or asset["special_population_flag"]:
            continue
        admitted = [row for row in asset["score_rows"] if row["admission_status"] == "admitted"]
        if admitted and asset["highlight_rule"] != "unknown":
            usable.append((index, admitted))
    combinations = []
    for size in range(1, min(len(usable), 8) + 1):
        for subset in itertools.combinations(usable, size):
            indices = tuple(item[0] for item in subset)
            rows = [row for item in subset for row in item[1]]
            combinations.append((indices, rows))
    return combinations


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "是", "全日制"}


def write_frame(path: Path, frame: pd.DataFrame, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        frame = pd.DataFrame(columns=columns)
    else:
        for column in columns:
            if column not in frame:
                frame[column] = ""
        frame = frame[columns]
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    manifest = pd.read_csv(args.manifest, encoding="utf-8-sig")
    manifest = manifest[manifest["retrieval_status"].eq("downloaded")].copy()
    if args.index.exists():
        index = pd.read_csv(args.index, encoding="utf-8-sig")
        index = index.drop_duplicates("repeat_url")[["repeat_url", "repeat_title", "major_name", "college", "detail_id"]]
        index = index.rename(
            columns={
                "repeat_url": "source_url",
                "repeat_title": "expected_title",
                "major_name": "expected_major_name",
                "college": "expected_college",
                "detail_id": "detail_id",
            }
        )
        manifest = manifest.merge(index, on="source_url", how="left")
    if args.school:
        manifest = manifest[manifest["school"].eq(args.school)]
    if args.year:
        manifest = manifest[pd.to_numeric(manifest["year"], errors="coerce").eq(args.year)]
    if args.limit:
        manifest = manifest.head(args.limit)
    records = manifest.to_dict("records")

    if args.workers <= 1:
        init_worker()
        extracted = []
        for index, row in enumerate(records, start=1):
            extracted.append(extract_image(row))
            print(f"OCR {index}/{len(records)} {row['school']} {row['year']}", flush=True)
    else:
        context = get_context("spawn")
        with context.Pool(processes=args.workers, initializer=init_worker) as pool:
            extracted = []
            for index, result in enumerate(pool.imap_unordered(extract_image, records), start=1):
                extracted.append(result)
                print(f"OCR {index}/{len(records)} {result['school']} {result['year']}", flush=True)
    extracted.sort(key=lambda row: (row["school"], int(row["year"]), row["source_url"]))

    periods = pd.read_csv(args.periods, encoding="utf-8-sig")
    schools = pd.read_csv(args.schools, encoding="utf-8-sig")
    full_time_map = {
        row["school"]: "全日制" in str(row.get("study_mode", ""))
        for row in schools.to_dict("records")
    }
    references = {}
    for row in periods.to_dict("records"):
        references[(row["school"], int(row["year"]))] = {
            "n": numeric(row.get("admitted_count")),
            "min": numeric(row.get("admitted_min")),
            "median": numeric(row.get("admitted_median")),
            "max": numeric(row.get("admitted_max")),
        }

    by_program = defaultdict(list)
    for asset in extracted:
        by_program[(asset["school"], int(asset["year"]))].append(asset)

    selected = set()
    program_audit = []
    for key, assets in sorted(by_program.items()):
        reference = references.get(key, {"n": None, "min": None, "median": None, "max": None})
        choices = candidate_combinations(assets)
        ranked = []
        for indices, rows in choices:
            metrics = subset_metrics(rows)
            chosen_assets = [assets[index] for index in indices]
            model_rows = [row for row in rows if not row.get("special_row")]
            model_metrics = subset_metrics(model_rows)
            if exact_match(metrics, reference):
                tier_rank = 0
                validation_tier = "four_summary_reconciled"
            elif structural_exact_match(
                metrics, model_metrics, reference, chosen_assets
            ):
                tier_rank = 1
                validation_tier = "count_available_summary_and_structure_reconciled"
            else:
                tier_rank = 2
                validation_tier = "not_reconciled"
            ranked.append(
                (
                    tier_rank,
                    match_penalty(metrics, reference),
                    len(indices),
                    indices,
                    rows,
                    metrics,
                    validation_tier,
                )
            )
        ranked.sort(key=lambda item: item[:3])
        best = ranked[0] if ranked else None
        validation_pass = bool(best and best[0] < 2)
        if validation_pass:
            for index in best[3]:
                selected.add((key[0], key[1], assets[index]["source_url"]))
        metrics = best[5] if best else {"n": 0, "min": None, "median": None, "max": None, "q10": None}
        model_rows = [row for row in best[4] if not row.get("special_row")] if best else []
        model_metrics = subset_metrics(model_rows)
        reference_complete = all(
            reference[field] is not None for field in ("n", "min", "median", "max")
        )
        if validation_pass:
            validation_status = best[6]
        elif not reference_complete:
            validation_status = "independent_summary_incomplete"
        elif not choices:
            validation_status = "no_explicit_admitted_rows"
        else:
            validation_status = "summary_mismatch"
        program_audit.append(
            {
                "school": key[0],
                "year": key[1],
                "asset_count": len(assets),
                "parsed_asset_count": sum(asset["layout_status"] == "parsed" for asset in assets),
                "target_asset_count": sum(asset["target_major_match"] for asset in assets),
                "explicit_admission_asset_count": sum(asset["highlight_rule"] != "unknown" for asset in assets),
                "reference_n": reference["n"],
                "reference_min": reference["min"],
                "reference_median": reference["median"],
                "reference_max": reference["max"],
                "extracted_n": metrics["n"],
                "extracted_min": metrics["min"],
                "extracted_median": metrics["median"],
                "extracted_max": metrics["max"],
                "model_n": model_metrics["n"],
                "model_min": model_metrics["min"],
                "model_median": model_metrics["median"],
                "model_max": model_metrics["max"],
                "q10_exact": model_metrics["q10"] if validation_pass else None,
                "validation_pass": validation_pass,
                "validation_status": validation_status,
                "validation_tier": best[6] if validation_pass else "not_reconciled",
                "selected_asset_count": len(best[3]) if validation_pass else 0,
                "match_penalty": best[1] if best else None,
            }
        )

    retest_rows = []
    admitted_rows = []
    model_program_keys = {
        (str(row["school"]), int(row["year"]))
        for row in program_audit
        if row["validation_pass"] and int(row["model_n"] or 0) >= 10
    }
    for asset in extracted:
        asset_selected = (asset["school"], int(asset["year"]), asset["source_url"]) in selected
        label_date_match = re.search(r"/kaoyan/(\d{4})/(\d{2})/(\d{2})/", asset["source_url"])
        label_date = "-".join(label_date_match.groups()) if label_date_match else ""
        full_time = bool(full_time_map.get(asset["school"], False))
        for score_row in asset["score_rows"]:
            candidate_hash = hashlib.sha256(
                f"{asset['sha256']}|{score_row['band_index']}".encode("utf-8")
            ).hexdigest()[:24]
            common = {
                "school": asset["school"],
                "year": int(asset["year"]),
                "major_code": "025200" if asset["target_major_match"] else "",
                "study_mode": "全日制" if full_time else "待核实",
                "candidate_id_hash": candidate_hash,
                "initial_score": score_row["initial_score"],
                "admission_status": score_row["admission_status"],
                "roster_stage": asset["roster_stage"],
                "highlight": score_row["highlight"],
                "highlight_rule": asset["highlight_rule"],
                "ocr_confidence": round(score_row["ocr_confidence"], 6),
                "row_index": score_row["band_index"],
                "label_available_date": label_date,
                "source_type": "mini_program_public_snapshot",
                "evidence_grade": asset["authority_grade"],
                "source_url": asset["source_url"],
                "source_title": asset["title"],
                "source_sha256": asset["sha256"],
                "source_cell": asset["source_cell"],
                "extraction_method": "grid_segmented_total_score_ocr",
                "review_status": "machine_summary_reconciled" if asset_selected else "machine_extracted_not_label_validated",
                "source_note": "Names and candidate numbers were not extracted or retained.",
                "special_row": bool(score_row.get("special_row")),
            }
            retest_rows.append(common)
            if score_row["admission_status"] == "admitted":
                eligible = bool(
                    asset_selected
                    and (str(asset["school"]), int(asset["year"])) in model_program_keys
                    and full_time
                    and asset["target_major_match"]
                    and not asset["special_population_flag"]
                    and not score_row.get("special_row")
                )
                admitted_rows.append(
                    {
                        **common,
                        "candidate_type": (
                            "special"
                            if score_row.get("special_row")
                            else ("normal_exam" if eligible else "unknown")
                        ),
                        "special_plan": bool(score_row.get("special_row")),
                        "adjustment_status": "no_adjustment" if eligible else "unknown",
                        "full_time": full_time,
                        "as_of_cutoff": False,
                        "model_eligible": eligible,
                    }
                )

    image_audit_rows = []
    for asset in extracted:
        scores = [row["initial_score"] for row in asset["score_rows"]]
        admitted = [row["initial_score"] for row in asset["score_rows"] if row["admission_status"] == "admitted"]
        image_audit_rows.append(
            {
                "school": asset["school"],
                "year": asset["year"],
                "source_url": asset["source_url"],
                "source_sha256": asset["sha256"],
                "title": asset["title"],
                "title_confidence": asset["title_confidence"],
                "footer": asset["footer"],
                "footer_confidence": asset["footer_confidence"],
                "layout_status": asset["layout_status"],
                "roster_stage": asset["roster_stage"],
                "highlight_rule": asset["highlight_rule"],
                "target_major_match": asset["target_major_match"],
                "special_population_flag": asset["special_population_flag"],
                "score_row_count": len(scores),
                "score_min": min(scores) if scores else None,
                "score_median": float(np.median(scores)) if scores else None,
                "score_max": max(scores) if scores else None,
                "admitted_row_count": len(admitted),
                "admitted_min": min(admitted) if admitted else None,
                "admitted_median": float(np.median(admitted)) if admitted else None,
                "admitted_max": max(admitted) if admitted else None,
                "selected_for_exact_label": (asset["school"], int(asset["year"]), asset["source_url"]) in selected,
                "score_order_monotone": asset["score_order_monotone"],
                "rank_coverage": asset["rank_coverage"],
                "score_ocr_confidence_median": asset["score_ocr_confidence_median"],
                "horizontal_lines": asset["horizontal_lines"],
                "vertical_lines": asset["vertical_lines"],
                "error": asset["error"],
            }
        )

    image_columns = list(image_audit_rows[0].keys()) if image_audit_rows else []
    write_frame(args.image_audit, pd.DataFrame(image_audit_rows), image_columns)
    program_columns = list(program_audit[0].keys()) if program_audit else []
    write_frame(args.program_audit, pd.DataFrame(program_audit), program_columns)
    retest_columns = list(retest_rows[0].keys()) if retest_rows else []
    write_frame(args.retest_output, pd.DataFrame(retest_rows), retest_columns)
    candidate_columns = [
        "school",
        "year",
        "major_code",
        "study_mode",
        "candidate_id_hash",
        "candidate_type",
        "initial_score",
        "special_plan",
        "adjustment_status",
        "full_time",
        "label_available_date",
        "source_type",
        "evidence_grade",
        "source_url",
        "source_title",
        "as_of_cutoff",
        "model_eligible",
        "review_status",
        "source_note",
        "admission_status",
        "roster_stage",
        "highlight",
        "highlight_rule",
        "ocr_confidence",
        "row_index",
        "source_sha256",
        "source_cell",
        "extraction_method",
    ]
    write_frame(args.candidate_output, pd.DataFrame(admitted_rows), candidate_columns)

    validated = [row for row in program_audit if row["validation_pass"]]
    model_validated = [row for row in validated if int(row["model_n"] or 0) >= 10]
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy_policy": "No names or candidate numbers were OCRed into output tables.",
        "images": len(extracted),
        "images_parsed": sum(row["layout_status"] == "parsed" for row in extracted),
        "image_stage_counts": dict(Counter(row["roster_stage"] for row in extracted)),
        "highlight_rule_counts": dict(Counter(row["highlight_rule"] for row in extracted)),
        "deidentified_score_rows": len(retest_rows),
        "admitted_score_rows": len(admitted_rows),
        "model_eligible_rows": sum(bool(row["model_eligible"]) for row in admitted_rows),
        "validated_exact_programs": len(validated),
        "model_eligible_exact_programs": len(model_validated),
        "validated_by_year": dict(Counter(str(row["year"]) for row in validated)),
        "validated_programs": [
            {
                "school": row["school"],
                "year": row["year"],
                "n": row["model_n"],
                "source_population_n": row["extracted_n"],
                "q10_exact": row["q10_exact"],
                "min": row["model_min"],
                "median": row["model_median"],
                "max": row["model_max"],
            }
            for row in validated
        ],
        "interpretation": (
            "Exact labels require an explicit admission marking in the image plus exact reconciliation "
            "of count and reported distribution summaries. Retest-only rows remain non-label data."
        ),
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
