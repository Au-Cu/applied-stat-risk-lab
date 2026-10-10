from __future__ import annotations

import json
from pathlib import Path

from candidate_score_layer import DEFAULT_PATH, exact_q10_by_program, load_candidate_scores, validate_candidate_scores


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit" / "candidate_score_quality.json"


def main() -> int:
    frame = load_candidate_scores(DEFAULT_PATH)
    report = validate_candidate_scores(frame)
    exact = exact_q10_by_program(frame)
    report["exact_program_labels"] = int(len(exact))
    report["policy"] = "exact labels are used only after normal-exam/full-time/special-plan exclusion and source review"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
