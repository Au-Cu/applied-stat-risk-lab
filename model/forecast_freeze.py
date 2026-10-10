from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_MANIFEST = Path("data/audit/forecast_freeze_2027.json")
FROZEN_FILES = (
    "data/processed/program_year.csv",
    "data/processed/national_lines.json",
    "data/processed/events_2027.csv",
    "data/processed/quota_publication_events.csv",
    "data/processed/candidate_initial_scores.csv",
    "data/processed/rolling_backtest.csv",
    "data/processed/forecast_2027.csv",
    "data/processed/forecast_2027.json",
    "data/audit/model_run.json",
    "app/data/forecast.json",
    "model/train_model.py",
    "model/interval_calibration.py",
    "model/quota_features.py",
    "model/candidate_score_layer.py",
    "model/experiment_v3_validation.py",
    "output/experiments/v3_validation_20261007/summary.json",
    "model/forecast_freeze.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(root: Path) -> dict:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).splitlines()
        return {"commit": commit, "workingTreeDirty": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unavailable", "workingTreeDirty": True}


def build_manifest(root: Path) -> dict:
    forecast = json.loads(
        (root / "app/data/forecast.json").read_text(encoding="utf-8")
    )
    records = []
    for relative in FROZEN_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Frozen input is missing: {relative}")
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    meta = forecast["meta"]
    return {
        "schemaVersion": 1,
        "forecastYear": 2027,
        "informationCutoff": "2026-10-07 23:59 Asia/Hong_Kong",
        "frozenAt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(
            timespec="seconds"
        ),
        "status": "frozen_for_prospective_test",
        "git": git_state(root),
        "headlineMetricsAtFreeze": {
            "backtestRows": meta["backtest"]["rows"],
            "proxyQ10WeightedMae": meta["backtest"]["mae"],
            "strictNestedRows": meta["robustUpperBacktest"]["rows"],
            "rawP90Coverage": 0.797,
            "robustP90Coverage": meta["robustUpperBacktest"]["q90_coverage"],
            "robustWis": meta["robustUpperBacktest"]["wis"],
            "robustP90MinusP50": meta["robustUpperBacktest"]["q90_minus_q50"],
            "exactCandidateQ10Labels": meta["exactCandidateLabels"]["applied_rows"],
        },
        "evaluationProtocol": {
            "primaryRule": "Do not tune any model, calibration rule, width threshold, or event prior using 2027 outcomes.",
            "deviationRule": "Any change after outcome access must receive a new version and be scored separately from this frozen baseline.",
            "primaryMetrics": [
                "weighted_mae",
                "wis",
                "q90_coverage",
                "q95_coverage",
                "p90_minus_p50",
            ],
            "subgroupMetrics": ["is_985", "national_zone", "event_status"],
            "subgroupPolicy": "Diagnostic only until additional independent forecast origins are available; no subgroup retuning on the 2027 result.",
            "labelPolicy": "Score the proxy target for continuity and report any newly obtained exact normal-exam Q10 subset separately.",
            "candidateScoreUncertainty": "excluded_by_current_research_scope",
        },
        "files": records,
    }


def verify_manifest(root: Path, manifest_path: Path) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for record in manifest["files"]:
        path = root / record["path"]
        if not path.is_file():
            mismatches.append(f"missing: {record['path']}")
            continue
        actual = sha256_file(path)
        if actual != record["sha256"]:
            mismatches.append(f"changed: {record['path']}")
    return mismatches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or verify the frozen 2027 prospective forecast baseline."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.repo_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path

    if args.create:
        if manifest_path.exists():
            raise FileExistsError(
                f"Freeze manifest already exists: {manifest_path}. "
                "Delete it only when intentionally creating a new model version."
            )
        manifest = build_manifest(root)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"created {manifest_path}")
        return

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Freeze manifest not found: {manifest_path}")
    mismatches = verify_manifest(root, manifest_path)
    if mismatches:
        print("forecast freeze verification failed")
        for mismatch in mismatches:
            print(f"- {mismatch}")
        raise SystemExit(1)
    print("forecast freeze verification passed")


if __name__ == "__main__":
    main()
