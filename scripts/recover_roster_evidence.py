"""Recover existing roster assets using header-verified table geometry.

All individual rows and original images stay in data/private. This module
does not infer admission status from a score, rank, a summary count, or a
retest title. Existing explicit-legend and population gates still apply.
"""

from __future__ import annotations

import argparse
import json
import re
from multiprocessing import get_context
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

import extract_candidate_scores as legacy

ROOT = Path(__file__).resolve().parents[1]


def header_geometry(image: np.ndarray, score_column_index: int | None = None) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    dark = (gray < 145).astype(np.uint8)
    horizontal = legacy.grouped_centers(np.where(dark.sum(axis=1) > width * 0.55)[0])
    if len(horizontal) < 3:
        raise ValueError("No usable horizontal grid")
    row_height = float(np.median(np.diff(horizontal)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(row_height * 0.72))))
    vertical_mask = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
    # The first grid row with at least four columns is a column header;
    # titles and promotional strips are single merged cells. We do not OCR
    # subsequent name/candidate-number cells while locating the score column.
    for top, bottom in list(zip(horizontal, horizontal[1:]))[:5]:
        if bottom - top < 20:
            continue
        region = vertical_mask[top + 2 : bottom - 2]
        vertical = legacy.grouped_centers(
            np.where(region.sum(axis=0) >= max(5, (bottom - top - 4) * 0.65))[0]
        )
        if not 5 <= len(vertical) <= 16:
            continue
        crops = []
        for left, right in zip(vertical, vertical[1:]):
            inset = min(8, max(2, int((right - left) * 0.06)))
            crops.append(image[top + 3 : bottom - 3, left + inset : right - inset])
        headers = legacy.recognize_batch(crops)
        initial = [i for i, (text, _) in enumerate(headers) if "初试" in text]
        total = [i for i, (text, _) in enumerate(headers)
                 if "总分" in text and len(text) <= 8 and not re.search(r"复试|综合", text)]
        choices = initial or total
        if score_column_index is not None:
            if score_column_index not in choices:
                raise ValueError("Reviewed score column disagrees with visible header")
            choices = [score_column_index]
        if len(choices) != 1:
            raise ValueError(f"Ambiguous initial-score header: {[t for t, _ in headers]}")
        index = choices[0]
        subject_indices = [
            i for i, (text, _) in enumerate(headers)
            if re.search(r"政治|外语|英语|业务|数学|统计学", text)
            and not re.search(r"报考|专业名称|学院|初试|复试", text)
        ]
        return {
            "verified_score_bounds": [vertical[index], vertical[index + 1]],
            "verified_vertical_lines": vertical,
            "score_header": headers[index][0],
            "header_confidence": headers[index][1],
            "header_y": [top, bottom],
            "headers": [text for text, _ in headers],
            "subject_indices": subject_indices if len(subject_indices) == 4 else [],
        }
    raise ValueError("No header row with a verified initial-score column")


def prepare_metadata(row: dict, image: np.ndarray, geometry: dict) -> dict:
    # Read only merged footer bands, never full-width candidate rows.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    dark = (gray < 145).astype(np.uint8)
    horizontal = legacy.grouped_centers(np.where(dark.sum(axis=1) > width * 0.55)[0])
    if "verified_footer" not in row:
        row = {**row, "verified_footer": ""}
        footer_candidates = []
        for top, bottom in list(zip(horizontal, horizontal[1:]))[-3:]:
            if not 20 <= bottom - top <= 190:
                continue
            boundaries = legacy.grouped_centers(np.where(dark[top + 3 : bottom - 3].sum(axis=0) > (bottom - top - 6) * 0.75)[0])
            if len(boundaries) > 3:
                continue
            text, confidence = legacy.recognize_document(image[top + 4 : bottom - 4, 15 : width - 15])
            if re.search(r"绿色|蓝色", text) and re.search(r"录取", text) and confidence >= 0.80:
                footer_candidates.append((text, confidence))
        if footer_candidates:
            row = {**row, "verified_footer": max(footer_candidates, key=lambda item: item[1])[0]}
    return {**row, **geometry, "privacy_safe_recovery": True,
            "verified_header_y_top": geometry["header_y"][0]}


def recover_asset(row: dict) -> dict:
    image = cv2.imdecode(np.fromfile(ROOT / row["local_private_path"], dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Cannot decode image")
    geometry = row.get("header_geometry") or header_geometry(image, row.get("verified_score_header_index"))
    extracted = legacy.extract_image(prepare_metadata(row, image, geometry))
    extracted["recovery_geometry"] = geometry
    if extracted["layout_status"] != "parsed":
        return extracted
    # Recognise omitted score cells independently at several scales. Require
    # agreement from two crops AND an explicit integer row number. An optional
    # four-subject checksum provides a separate numerical check. No reference
    # Q10/minimum is used to manufacture a missing observation.
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    horizontal = legacy.grouped_centers(np.where((gray < 145).sum(axis=1) > width * 0.55)[0])
    present = {int(item["band_index"]) for item in extracted["score_rows"]}
    left, right = geometry["verified_score_bounds"]
    vertical = geometry["verified_vertical_lines"]
    added = []
    for band, (top, bottom) in enumerate(zip(horizontal, horizontal[1:])):
        if band in present or top <= geometry["header_y"][0] or not 20 <= bottom - top <= 190:
            continue
        rank_variants = [image[top + 12 : bottom - 12,
                               vertical[0] + int((vertical[1]-vertical[0])*fraction) :
                               vertical[1] - int((vertical[1]-vertical[0])*fraction)] for fraction in (0.125, 0.25)]
        rank_text, rank_confidence = max(legacy.recognize_batch(rank_variants), key=lambda item: item[1])
        if not re.fullmatch(r"\d{1,3}", rank_text) or float(rank_confidence) < 0.80:
            continue
        variants = [image[top + 12 : bottom - 12, left + int((right-left)*fraction) : right - int((right-left)*fraction)] for fraction in (0.20, 0.25)]
        variants += [cv2.resize(crop, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC) for crop in variants.copy()]
        readings = legacy.recognize_batch(variants)
        numeric = [int(text) for text, confidence in readings if re.fullmatch(r"[2-4]\d{2}", text) and confidence >= 0.80]
        consensus = sorted({score for score in numeric if numeric.count(score) >= 2})
        if len(consensus) != 1:
            continue
        score = consensus[0]
        checksum = None
        if geometry["subject_indices"]:
            subject_crops = [image[top + 7 : bottom - 7, vertical[i] + 8 : vertical[i + 1] - 8] for i in geometry["subject_indices"]]
            subjects = legacy.recognize_batch(subject_crops)
            if all(re.fullmatch(r"\d{1,3}", text) and confidence >= 0.80 for text, confidence in subjects):
                checksum = sum(int(text) for text, _ in subjects)
                if checksum != score:
                    continue
        r, g, b, highlight = legacy.dominant_background(image[top + 4 : bottom - 4, left + 4 : right - 4])
        rule = extracted["highlight_rule"]
        if rule == "all_rows_admitted":
            status = "admitted"
        elif rule in {"green_excluded", "blue_excluded"}:
            status = "not_admitted" if highlight == rule.split("_")[0] else "admitted"
        elif rule in {"green_admitted", "blue_admitted"}:
            status = "admitted" if highlight == rule.split("_")[0] else "not_admitted"
        else:
            status = "unknown"
        display_rank = int(rank_text)
        special_indices = {int(m.group(1)) for m in legacy.SPECIAL_ROW_PATTERN.finditer(extracted["footer"])}
        added.append({"band_index": band, "y_top": top, "y_bottom": bottom,
                      "initial_score": score, "ocr_confidence": max(confidence for _, confidence in readings),
                      "ocr_text": str(score), "display_rank": display_rank, "rank_was_ocr": True,
                      "rank_ocr_confidence": rank_confidence, "special_row": display_rank in special_indices,
                      "background_rgb": f"{r},{g},{b}", "highlight": highlight, "admission_status": status,
                      "checksum_total": checksum, "recovery_rule": "multiscale_consensus_with_rank"})
    extracted["score_rows"] = sorted(extracted["score_rows"] + added, key=lambda item: item["band_index"])
    # A crop without border strokes also corrects mistaken row serials. Row
    # serials are used solely to exclude explicitly identified special plans.
    rank_crops = []
    for item in extracted["score_rows"]:
        top, bottom = item["y_top"], item["y_bottom"]
        for fraction in (0.125, 0.25):
            inset = int((vertical[1] - vertical[0]) * fraction)
            rank_crops.append(image[top + 12 : bottom - 12, vertical[0] + inset : vertical[1] - inset])
    rank_readings = legacy.recognize_batch(rank_crops)
    special_indices = {int(m.group(1)) for m in legacy.SPECIAL_ROW_PATTERN.finditer(extracted["footer"])}
    for index, item in enumerate(extracted["score_rows"]):
        text, confidence = max(rank_readings[index*2:index*2+2], key=lambda reading: reading[1])
        match = re.fullmatch(r"(\d{1,3})(?:\*|号|號)?", text)
        if match and confidence >= 0.80:
            item.update(display_rank=int(match.group(1)), rank_was_ocr=True, rank_ocr_confidence=confidence)
        item["special_row"] = item["display_rank"] in special_indices
    values = [item["initial_score"] for item in extracted["score_rows"]]
    extracted["score_order_monotone"] = bool(values and (all(a >= b for a, b in zip(values, values[1:])) or all(a <= b for a, b in zip(values, values[1:]))))
    extracted["rank_coverage"] = float(np.mean([item["rank_was_ocr"] for item in extracted["score_rows"]])) if values else 0.0
    extracted["score_ocr_confidence_median"] = float(np.median([item["ocr_confidence"] for item in extracted["score_rows"]])) if values else 0.0
    extracted["recovered_omitted_rows"] = len(added)
    ranks = [item["display_rank"] for item in extracted["score_rows"]]
    extracted["rank_sequence_verified"] = bool(ranks and len(set(ranks)) == len(ranks) and all(a < b for a, b in zip(ranks, ranks[1:])))
    return extracted


def refresh_metadata(path: Path) -> None:
    """Reuse verified score cells while restricting metadata OCR to safe bands."""
    assets = json.loads(path.read_text(encoding="utf-8"))
    for n, asset in enumerate(assets, 1):
        if asset.get("layout_status") != "parsed":
            continue
        image = cv2.imdecode(np.fromfile(ROOT / asset["local_private_path"], dtype=np.uint8), 1)
        geometry = asset.get("recovery_geometry") or header_geometry(image, asset.get("verified_score_header_index"))
        source = {**asset}
        source.pop("verified_footer", None)
        if asset.get("verified_footer") and asset.get("school") == "同济大学" and int(asset["year"]) == 2025:
            source["verified_footer"] = "注：绿色标记为未被拟录取考生。"
        metadata = legacy.extract_image({**prepare_metadata(source, image, geometry), "metadata_only": True})
        for key in ("title", "title_confidence", "footer", "footer_confidence", "roster_stage", "highlight_rule", "target_major_match", "special_population_flag"):
            asset[key] = metadata[key]
        special_indices = {int(match.group(1)) for match in legacy.SPECIAL_ROW_PATTERN.finditer(asset["footer"])}
        for item in asset["score_rows"]:
            rule, color = asset["highlight_rule"], item["highlight"]
            if rule == "all_rows_admitted":
                status = "admitted"
            elif rule in {"green_excluded", "blue_excluded"}:
                status = "not_admitted" if color == rule.split("_")[0] else "admitted"
            elif rule in {"green_admitted", "blue_admitted"}:
                status = "admitted" if color == rule.split("_")[0] else "not_admitted"
            else:
                status = "unknown"
            item["admission_status"] = status
            item["special_row"] = item["display_rank"] in special_indices
        asset["metadata_recovery_revision"] = 3
        if n % 20 == 0:
            print(f"metadata refresh {n}/{len(assets)}", flush=True)
    path.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")


def recover_worker(row: dict) -> dict:
    try:
        return recover_asset(row)
    except Exception as exc:
        return {**row, "layout_status": "unrecognized", "score_rows": [], "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/private/evidence_refresh_20261024/recovered_assets.json")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--school")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--scan-headers", action="store_true", help="Inspect score-column identity across every source without re-OCRing all score cells")
    args = parser.parse_args()
    manifest = pd.read_csv(ROOT / "data/processed/roster_asset_manifest.csv").fillna("")
    audit = pd.read_csv(ROOT / "data/processed/roster_ocr_audit.csv").fillna("")
    index = pd.read_csv(ROOT / "data/private/evidence_refresh_20261024/mini_program_roster_index.csv").fillna("")
    header_path = ROOT / "data/private/evidence_refresh_20261024/header_audit.json"
    header_records = json.loads(header_path.read_text(encoding="utf-8")) if header_path.exists() else []
    adjudications = json.loads((ROOT / "data/curated/evidence_adjudications_20261024.json").read_text(encoding="utf-8"))
    reviewed = {row["source_sha256"]: row for row in adjudications["records"]}
    wrong_columns = {r["source_sha256"] for r in header_records if r.get("score_column_disagrees")}
    needs = set(audit.loc[audit.layout_status.ne("parsed") | audit.school.eq("同济大学"), "source_sha256"]) | wrong_columns
    if args.scan_headers:
        needs = set(manifest.sha256)
    manifest = manifest[manifest.sha256.isin(needs)].copy()
    if args.school:
        manifest = manifest[manifest.school.eq(args.school)]
    index = index.drop_duplicates("repeat_url").rename(columns={"repeat_url": "source_url", "repeat_title": "expected_title", "major_name": "expected_major_name", "college": "expected_college"})
    manifest = manifest.merge(index[["source_url", "expected_title", "expected_major_name", "expected_college"]], on="source_url", how="left")
    legacy.init_worker()
    if args.refresh_metadata:
        refresh_metadata(args.output)
        return
    if args.scan_headers:
        checked = []
        cached_headers = {r["source_sha256"]: r for r in header_records if not r.get("error")}
        for n, row in enumerate(manifest.to_dict("records"), 1):
            if row["sha256"] in cached_headers:
                checked.append(cached_headers[row["sha256"]])
                continue
            record = {"school": row["school"], "year": int(row["year"]), "source_sha256": row["sha256"]}
            try:
                im = cv2.imdecode(np.fromfile(ROOT / row["local_private_path"], dtype=np.uint8), 1)
                geom = header_geometry(im, reviewed.get(row["sha256"], {}).get("verified_score_header_index"))
                height, width = im.shape[:2]
                dark = (cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) < 145).astype(np.uint8)
                for threshold in (0.70, 0.38, 0.24):
                    vertical = legacy.grouped_centers(np.where(dark.sum(axis=0) > height * threshold)[0])
                    if len(vertical) >= 2:
                        break
                right = [v for v in vertical if v > width * 0.60]
                old_bounds = right[-2:] if len(right) >= 2 else []
                difference = not old_bounds or max(abs(a-b) for a,b in zip(old_bounds, geom["verified_score_bounds"])) > 8
                record.update(**geom, legacy_score_bounds=old_bounds, score_column_disagrees=difference, error="")
            except Exception as exc:
                record.update(error=f"{type(exc).__name__}: {exc}", score_column_disagrees=False)
            checked.append(record)
            header_path.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
            if n % 25 == 0:
                print(f"header audit {n}/{len(manifest)}", flush=True)
        header_path.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"header audit complete: {len(checked)}, disagreements {sum(r.get('score_column_disagrees',False) for r in checked)}", flush=True)
        return
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.retry_failed and args.output.exists() else []
    verified_headers = {row["source_sha256"]: row for row in header_records if not row.get("error")}
    cached = {row["sha256"]: row for row in previous
              if row.get("layout_status") == "parsed" and row["sha256"] not in reviewed}
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = []
    for row in manifest.to_dict("records"):
        if row["sha256"] in verified_headers:
            row["header_geometry"] = verified_headers[row["sha256"]]
        if row["sha256"] in reviewed:
            reviewed_row = reviewed[row["sha256"]]
            if row["school"] != reviewed_row["school"] or int(row["year"]) != reviewed_row["year"]:
                raise ValueError("Reviewed source identity mismatch")
            for key in ("verified_footer", "verified_score_header_index"):
                if key in reviewed_row:
                    row[key] = reviewed_row[key]
        if row["sha256"] in cached:
            results.append(cached[row["sha256"]])
            continue
        pending.append(row)
    def retain(result):
        results.append(result)
        results.sort(key=lambda item: (item["school"], int(item["year"]), item["source_url"]))
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"recovered {len(results)}/{len(manifest)} {result['school']} {result['year']}: {result['layout_status']}, {len(result['score_rows'])} score rows", flush=True)
    if args.workers > 1:
        with get_context("spawn").Pool(args.workers, initializer=legacy.init_worker) as pool:
            for result in pool.imap_unordered(recover_worker, pending):
                retain(result)
    else:
        for row in pending:
            retain(recover_worker(row))
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
