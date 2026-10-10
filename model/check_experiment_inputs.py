from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def main():
    program = pd.read_csv(ROOT / "data" / "processed" / "program_year.csv")
    schools = pd.read_csv(ROOT / "data" / "processed" / "schools.csv")
    merged = program.merge(schools, on="school", how="left", suffixes=("", "_school"))
    trainable = merged[
        merged["margin_q10"].notna()
        & merged["study_mode"].fillna("").str.contains("全日制")
        & (merged["target_weight"] >= 0.12)
    ].copy()
    oos_path = ROOT / "output" / "experiments" / "precision_upgrade_20261007" / "oos_predictions.json"
    oos = json.loads(oos_path.read_text(encoding="utf-8"))
    history_mismatches = []
    for row in oos:
        expected = int(
            trainable[
                (trainable["school"] == row["school"])
                & (trainable["year"] < int(row["year"]))
            ].shape[0]
        )
        if int(row["history_n"]) != expected:
            history_mismatches.append(
                {"school": row["school"], "year": row["year"], "expected": expected, "observed": row["history_n"]}
            )
    report = {
        "program_rows": int(len(program)),
        "program_columns": int(program.shape[1]),
        "duplicate_school_year": int(program.duplicated(["school", "year"]).sum()),
        "school_duplicate_keys": int(schools.duplicated(["school"]).sum()),
        "orphan_school_rows": int((~program["school"].isin(schools["school"])).sum()),
        "years": {str(int(k)): int(v) for k, v in program["year"].value_counts().sort_index().items()},
        "trainable_rows": int(len(trainable)),
        "trainable_by_year": {
            str(int(k)): int(v) for k, v in trainable["year"].value_counts().sort_index().items()
        },
        "q10_method": {
            str(k): int(v) for k, v in trainable["q10_method"].fillna("missing").value_counts().items()
        },
        "target_weight_missing": int(trainable["target_weight"].isna().sum()),
        "target_weight_below_floor": int((trainable["target_weight"] < 0.12).sum()),
        "required_feature_missing": {
            column: int(trainable[column].isna().sum())
            for column in [
                "margin_q10",
                "national_zone",
                "is_985",
                "lag1_q10",
                "trailing_margin_median",
            ]
        },
        "experiment_oos_rows": int(len(oos)),
        "history_feature_mismatches": history_mismatches,
    }
    out = ROOT / "output" / "experiments" / "precision_upgrade_20261007" / "data_quality_checks.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
