"""Integration checks for the public evidence revision and its time boundary."""
from __future__ import annotations

import hashlib
import json
import sys
import importlib.metadata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/evidence_refresh_20261024"
EXP = ROOT / "output/experiments/evidence_refresh_20261024"


def main():
    checks = []
    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    coverage = pd.read_csv(DATA / "coverage_by_school_year.csv")
    exact = pd.read_csv(DATA / "exact_distribution_summary.csv")
    labels = pd.read_csv(DATA / "candidate_label_audit.csv")
    panel=pd.read_csv(DATA/"program_year.csv")
    sources = pd.read_csv(DATA / "official_source_registry.csv").fillna("")
    headers = pd.read_csv(DATA / "score_column_audit.csv").fillna("")
    experiment = json.loads((EXP / "summary.json").read_text(encoding="utf-8"))
    payload = json.loads((ROOT / "app/data/evidence-refresh.json").read_text(encoding="utf-8"))
    check(len(coverage)==405 and coverage.school.nunique()==81 and not coverage.duplicated(["school","year"]).any(), "All 81 x 5 school-years retained exactly once")
    check(set(coverage.year)==set(range(2022,2027)), "No missing panel year")
    check(len(headers)==452 and headers.source_sha256.nunique()==summary["unique_source_payloads"], "All 452 source references inspected; duplicate payloads identified")
    check(len(exact)==summary["exact_school_years_after"] and int(exact.candidate_n.sum())==summary["exact_candidate_rows_after"], "Aggregate sample counts reconcile")
    check(exact.candidate_n.ge(10).all(), "Small cohorts do not silently bypass exact-label n>=10 gate")
    effective_labels=panel[panel.q10_method.eq("exact_candidate_scores")].merge(exact,on=["school","year"])
    check(len(effective_labels)==len(exact) and np.allclose(effective_labels.q10_value,effective_labels.score_q10), "Audited raw-score labels replace every available proxy in the effective panel")
    tg=panel[panel.school.eq("同济大学")].set_index("year")
    check(tg.loc[2025,"cutoff"]==385 and tg.loc[2026,"cutoff"]==396 and tg.loc[2026,"lag1_q10"]==388, "Official cutoff corrections and exact-aware lagged labels are propagated")
    exact_gate = labels[labels.model_label_eligible.astype(str).str.lower().eq("true")]
    check(set(zip(exact.school,exact.year))==set(zip(exact_gate.school,exact_gate.year)), "Every exact distribution passes the label gate")
    old = pd.read_csv(ROOT / "output/experiments/v5_hierarchical_distribution_20261009/candidate_distribution_summary.csv")
    common = old.merge(exact,on=["school","year"],suffixes=("_old","_new"))
    check(len(common)==len(old), "No previously accepted school-year silently dropped")
    check(np.allclose(common.score_q10_old,common.score_q10_new,atol=1e-10), "Previous audited empirical Q10 labels retained")
    check(sources.source_id.is_unique and sources.source_sha256.str.fullmatch(r"[a-f0-9]{64}").all(), "Official sources have unique IDs and content hashes")
    check(all(sources.capture_time.str.len()>0), "Capture dates retained separately from publication dates")
    check(sources.loc[sources.source_role.eq("unavailable_roster"),"publish_date"].eq("").all(), "Unknown source publication date not invented")
    official_dir=ROOT/"data/private/evidence_refresh_20261024/official"
    if official_dir.exists():
        hashes={hashlib.sha256(path.read_bytes()).hexdigest() for path in official_dir.iterdir() if path.is_file()}
        check(set(sources.source_sha256).issubset(hashes), "Official source hashes match local original captures")
    for filename in ["previous_evidence_common_predictions.csv", "refreshed_evidence_common_predictions.csv", "refreshed_evidence_expanded_predictions.csv"]:
        frame=pd.read_csv(EXP/filename)
        check(frame.latest_training_year.lt(frame.year).all(), f"Strictly past outcomes in {filename}")
        quantiles=frame[[f"pred_q{q:02d}" for q in (5,10,20,50,80,90,95)]].to_numpy()
        check(np.isfinite(quantiles).all() and (np.diff(quantiles,axis=1)>=0).all(), f"Finite ordered predictive quantiles in {filename}")
    check(not experiment["hyperparameters_retuned"] and not experiment["production_promoted"], "Evidence update does not retune or auto-promote a production model")
    roles=pd.read_csv(DATA/"score_roles_by_school_year.csv")
    check(int(roles.n.sum())==summary["unique_readable_score_rows_after"], "Every de-duplicated readable score retains an explicit statistical role")
    check(int(roles.loc[roles.statistical_role.eq("exact_label_and_distribution"),"n"].sum())==int(exact.candidate_n.sum()), "Exact-role count agrees with empirical label population")
    check(payload["summary"]==summary and payload["experiment"]==experiment and len(payload["schools"])==81, "Website uses the same evidence and experiment snapshot")
    tongji = next(row for row in payload["schools"] if row["school"]=="同济大学")
    check(tongji["needsForecastReview"] and tongji["knownEvent"]["publishDate"]=="2026-06-26", "Known scope errors and syllabus event prevent stale steady/safe labels")
    t=exact[exact.school.eq("同济大学")].set_index("year")
    check(int(t.loc[2025,"candidate_n"])==33 and int(t.loc[2026,"candidate_n"])==29 and abs(t.loc[2026,"score_q10"]-412.2)<1e-8, "Tongji ordinary population and empirical Q10 reconcile")
    for path in DATA.glob("*.csv"):
        columns=pd.read_csv(path,nrows=0).columns
        check(not any(column in columns for column in ["candidate_id_hash","row_index","initial_score","姓名","考生编号","local_private_path"]), f"Public CSV is aggregate or provenance: {path.name}")
    text=(ROOT/"app/data/evidence-refresh.json").read_text(encoding="utf-8")
    check(not any(token in text for token in ["candidate_id_hash", "local_private_path", "repeat_url", "row_index"]), "Website does not expose candidate records or image-index endpoints")
    sys.path.insert(0,str(ROOT/"model"))
    from verify_frozen_forecast_outputs import FROZEN_OUTPUTS
    manifest=json.loads((ROOT/"data/audit/forecast_freeze_2027.json").read_text(encoding="utf-8"))
    indexed={row["path"]:row for row in manifest["files"]}
    for filename in FROZEN_OUTPUTS:
        check(hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==indexed[filename]["sha256"], f"Frozen numeric output unchanged: {filename}")
    result={"status":"passed","checks":len(checks),"details":checks}
    (EXP/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    input_files=["data/processed/program_year.csv", "data/processed/national_lines.json",
        "data/processed/evidence_refresh_20261024/exact_distribution_summary.csv",
        "data/processed/evidence_refresh_20261024/candidate_label_audit.csv",
        "data/curated/evidence_adjudications_20261024.json",
        "model/experiment_evidence_refresh.py", "model/experiment_statistical_inference.py",
        "model/candidate_score_layer.py"]
    input_hashes=[]
    for relative in input_files:
        content=(ROOT/relative).read_bytes()
        input_hashes.append({"path":relative,"raw_sha256":hashlib.sha256(content).hexdigest(),
            "lf_normalized_sha256":hashlib.sha256(content.replace(b"\r\n",b"\n")).hexdigest()})
    reproducibility={"verified_python":sys.version,"packages":{name:importlib.metadata.version(name) for name in ["numpy","pandas","scipy","scikit-learn"]},
        "model_random_seed":20261011,"q10_bootstrap_draws":2000,
        "inputs":input_hashes,"snapshot_version":"evidence-refresh-20261024",
        "text_hash_policy":"Use LF-normalized SHA256 across Git checkout newline conventions. Official original captures always use raw bytes.",
        "privacy":"Public replication reads only school-year aggregates. It cannot redo OCR without the authorized private originals."}
    (EXP/"reproducibility.json").write_text(json.dumps(reproducibility,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"passed","checks":len(checks)},ensure_ascii=False))


if __name__ == "__main__":
    main()
