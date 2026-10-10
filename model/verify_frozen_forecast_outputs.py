"""Verify immutable forecast artefacts while allowing later research code.

The original freeze manifest intentionally captured code and an empty public
candidate template.  Candidate rows were later moved to the private layer and
research code continued to evolve.  This verifier leaves the original manifest
untouched and checks only the files that constitute the frozen numerical 2027
forecast and its published backtest snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

from forecast_freeze import sha256_file


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "audit" / "forecast_freeze_2027.json"
FROZEN_OUTPUTS = {
    "data/processed/program_year.csv",
    "data/processed/national_lines.json",
    "data/processed/events_2027.csv",
    "data/processed/quota_publication_events.csv",
    "data/processed/rolling_backtest.csv",
    "data/processed/forecast_2027.csv",
    "data/processed/forecast_2027.json",
    "data/audit/model_run.json",
    "app/data/forecast.json",
    "output/experiments/v3_validation_20261007/summary.json",
}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    indexed = {record["path"]: record for record in manifest["files"]}
    missing_from_manifest = sorted(FROZEN_OUTPUTS - indexed.keys())
    mismatches = []
    for relative in sorted(FROZEN_OUTPUTS):
        record = indexed.get(relative)
        if record is None:
            continue
        path = ROOT / relative
        if not path.is_file():
            mismatches.append(f"missing: {relative}")
        elif sha256_file(path) != record["sha256"]:
            mismatches.append(f"changed: {relative}")
    payload = {
        "forecast_year": manifest["forecastYear"],
        "information_cutoff": manifest["informationCutoff"],
        "checked_outputs": len(FROZEN_OUTPUTS),
        "missing_from_manifest": missing_from_manifest,
        "mismatches": mismatches,
        "status": "passed" if not missing_from_manifest and not mismatches else "failed",
        "note": "Research code and private candidate files are versioned separately and are not treated as frozen numerical outputs.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
