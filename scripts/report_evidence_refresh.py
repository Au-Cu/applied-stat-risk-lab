"""Build public provenance, complete coverage tables and reader-facing data.

This is an evidence report, not a numeric 2027 forecast overwrite. Every
school-year remains in the inventory, including unreadable and missing ones.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/evidence_refresh_20261024"
PRIVATE = ROOT / "data/private/evidence_refresh_20261024"


def truth(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def official_sources():
    definitions = [
        ("TJ25-CUTOFF", 2025, "同济大学数学科学学院2025年硕士研究生进入复试的初试成绩基本要求", "2025-03-14", "https://math.tongji.edu.cn/info/1037/11954.htm", "tongji_auto_11954.html", "cutoff_notice", "官方学院原文：01、02方向385分，03、04方向323分"),
        ("TJ25-CUTOFF-PDF", 2025, "同济大学数学科学学院2025年进入复试初试成绩基本要求附件", "2025-03-14", "https://math.tongji.edu.cn/__local/3/1A/33/AF6A002A4BB347DE45D3402442F_84DEA1DF_14A81.pdf", "tongji_2025_cutoff.pdf", "cutoff", "更正全日制01、02方向的385分；不混入323分的非全日制方向"),
        ("TJ26-CUTOFF", 2026, "同济大学数学科学学院2026年硕士研究生进入复试的初试成绩基本要求", "2026-03-18", "https://math.tongji.edu.cn/info/1037/13264.htm", "tongji_auto_13264.html", "cutoff_notice", "官方学院发布页，日期来自网页"),
        ("TJ26-CUTOFF-PDF", 2026, "同济大学数学科学学院2026年进入复试初试成绩基本要求附件", "2026-03-18", "https://math.tongji.edu.cn/__local/1/E0/BA/E8D86468F3671102B822631B627_6ACD045A_19C00.pdf", "tongji_2026_cutoff.pdf", "cutoff", "01、02方向396分；03、04及专项324分，不混合"),
        ("TJ25-SCORES", 2025, "2025年应用统计硕士研究生招生复试总成绩（01、02方向）", "2025-03-27", "https://math.tongji.edu.cn/info/1037/12617.htm", "tongji_auto_12617.html", "retest_results", "复试总成绩公示不是最终拟录取名单"),
        ("TJ26-SCORES", 2026, "2026年应用统计硕士研究生招生总成绩（研究方向01、02）", "2026-03-28", "https://math.tongji.edu.cn/info/1038/13286.htm", "tongji_2026_results.html", "retest_results", "初试404分记录及末行386分专项可交叉核对；不按综合排名截取录取者"),
        ("TJ26-SCORES-PDF", 2026, "2026年应用统计硕士研究生招生总成绩（01、02）附件", "2026-03-28", "https://math.tongji.edu.cn/__local/B/E9/9A/816F32689DF13FC9C4BDA1E7F08_219E63FB_1127B.pdf", "tongji_2026_total_scores.pdf", "retest_results", "官方复试成绩附件；个人原文只作私有核验，不再公开镜像"),
        ("TJ24-SCORES", 2024, "同济大学数学科学学院2024年应用统计专业型硕士研究生招生复试总成绩公示", "2024-03-30", "https://math.tongji.edu.cn/info/1038/11302.htm", "tongji_2024_results.html", "retest_results", "已取得官方附件；缺最终录取状态，保留为复试池证据"),
        ("TJ23-SCORES", 2023, "2023年应用统计专业型硕士研究生招生复试总成绩", "2023-03-31", "https://math.tongji.edu.cn/info/1037/10601.htm", "tongji_auto_10601.html", "retest_results", "已取得官方附件；不能仅按人数推断谁被录取"),
        ("TJ26-FINAL-NOTICE", 2026, "同济大学2026年硕士研究生（统考）拟录取名单公示（第一批）", "2026-04-27", "https://yz.tongji.edu.cn/info/1012/4169.htm", "tongji_2026_final_notice.html", "admission_notice", "仅有公示说明，名单入口现已关闭；不能声称取得官方最终逐人名单"),
        ("TJ26-FINAL-ENDPOINT", 2026, "同济大学硕士研究生招生拟录取名单公示入口", "", "https://yzbm.tongji.edu.cn/xxgs/ssLq", "tongji_2026_final_closed.html", "unavailable_roster", "抓取时页面显示尚未开放，不恢复或绕过权限"),
        ("TJ27-SYLLABUS-NOTICE", 2027, "关于调整我校统计学（科目代码432）2027年硕士研究生招生考试科目大纲的通知", "2026-06-26", "https://yz.tongji.edu.cn/info/1018/4206.htm", "tongji_2027_syllabus_notice.html", "syllabus_event", "公告已在原冻结截点前公开，旧事件表遗漏；事件方向、概率及幅度仍未经验估计"),
        ("TJ27-SYLLABUS-PDF", 2027, "同济大学432统计学2027年考试科目大纲", "2026-06-26", "https://yz.tongji.edu.cn/yingyongtongji432dagangnew.pdf", "tongji_2027_syllabus.pdf", "syllabus", "150分180分钟；单选50、简答40、计算分析60分；参考茆第4版2026及贾第9版2025"),
        ("TJ27-DIRECTIONS", 2027, "同济大学2027年应用统计专业目录（数学科学学院）", "2026-09-30", "https://yzbm.tongji.edu.cn/zsml/sszsml/zsmlYjfx/2027/102/025200?ksfs=21", "tongji_2027_025200_catalog.html", "program_scope", "01、02全日制，03、04非全日制；历史网页抓取不等于各时点版本均有存档"),
        ("TJ27-SCHOOL-PLAN", 2027, "同济大学2027年数学科学学院专业目录及招生计划说明", "2026-09-30", "https://yzbm.tongji.edu.cn/zsml/sszsml/zsmlZy/2027/102", "tongji_2027_school_catalog.html", "excluded_quota", "97为上一年学院实际总招生人数，含推免、专项且跨专业；排除作为当年应用统计普通统考净额"),
    ]
    rows = []
    for source_id, year, title, date, url, filename, role, notes in definitions:
        path = PRIVATE / "official" / filename
        if not path.exists():
            raise ValueError(f"Missing official snapshot {filename}")
        capture = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        rows.append({"source_id": source_id, "school": "同济大学", "year": year, "title": title,
            "source_url": url, "publish_date": date, "publication_precision": "date" if date else "unknown",
            "capture_time": capture, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "authority_grade": "primary_official", "source_role": role, "notes": notes,
            "version_basis": "current_capture_of_dated_official_page; not a contemporaneous historical archive"})
    pd.DataFrame(rows).to_csv(DATA / "official_source_registry.csv", index=False, encoding="utf-8-sig")
    return rows


def main():
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    experiment_path = ROOT / "output/experiments/evidence_refresh_20261024/summary.json"
    experiment = json.loads(experiment_path.read_text(encoding="utf-8")) if experiment_path.exists() else None
    sources = official_sources()
    event = [{"school": "同济大学", "year": 2027, "unit": "数学科学学院", "major_code": "025200",
        "study_mode": "全日制", "event_type": "syllabus_change", "event_name": "432统计学2027年考试大纲调整",
        "publish_date": "2026-06-26", "source_id": "TJ27-SYLLABUS-NOTICE",
        "source_url": "https://yz.tongji.edu.cn/info/1018/4206.htm", "existence_verified": True,
        "impact_direction": "unknown", "impact_size": None, "scenario_weights": None,
        "production_applied": False, "reason": "Verified occurrence does not identify score impact or scenario probabilities"}]
    pd.DataFrame(event).to_csv(DATA / "events_2027_evidence.csv", index=False, encoding="utf-8-sig")
    schools = pd.read_csv(ROOT / "data/processed/schools.csv").fillna("")
    periods = pd.read_csv(ROOT / "data/processed/program_year.csv")
    programs = pd.read_csv(DATA / "candidate_label_audit.csv").fillna("")
    images = pd.read_csv(PRIVATE / "roster_ocr_audit.csv").fillna("")
    index = pd.read_csv(PRIVATE / "mini_program_roster_index.csv").fillna("")
    distributions = pd.read_csv(DATA / "exact_distribution_summary.csv")
    quotas = pd.read_csv(ROOT / "output/research/quota_deadline_20261023_r2/coverage_gaps.csv").fillna("")
    quota_records=pd.read_csv(ROOT/"output/experiments/deadline_quota_20261024/record_eligibility.csv").fillna("")
    quota_records=quota_records[quota_records.policy.eq("strict_ordinary") & quota_records.evidence_eligible.map(truth) & pd.to_numeric(quota_records.year).eq(2027)]
    provenance = pd.read_csv(ROOT / "data/processed/program_year_provenance.csv").fillna("")
    # Secondary metadata updates do not establish a definition-compatible
    # applications/admissions ratio, nor an official historical data vintage.
    old_year = pd.read_csv(ROOT / "data/processed/mini_program_year_index.csv").fillna("").astype(str)
    new_year = pd.read_csv(PRIVATE / "mini_program_year_index.csv").fillna("").astype(str)
    key = ["school", "college", "year", "detail_id"]
    joined = old_year.merge(new_year, on=key, suffixes=("_old", "_new"))
    metadata_changes = []
    for _, row in joined.iterrows():
        for column in [c for c in old_year if c not in key + ["retrieved_at"]]:
            if row[column + "_old"] != row[column + "_new"]:
                metadata_changes.append({"school": row.school, "unit": row.college, "year": int(row.year),
                    "field": column, "old_value": row[column + "_old"], "new_value": row[column + "_new"],
                    "source_url": row.api_url_new, "capture_time": row.retrieved_at_new,
                    "publish_date": "", "authority_grade": "secondary_structured", "model_eligible": False,
                    "reason": "Definition and historical publication time unverified; preserve as a source observation, not a fitted feature"})
    pd.DataFrame(metadata_changes).to_csv(DATA / "secondary_metadata_changes.csv", index=False, encoding="utf-8-sig")
    header_records = json.loads((PRIVATE / "header_audit.json").read_text(encoding="utf-8"))
    public_headers = [{key: row.get(key) for key in ["school", "year", "source_sha256", "score_header", "header_confidence", "score_column_disagrees", "error"]} for row in header_records]
    pd.DataFrame(public_headers).to_csv(DATA / "score_column_audit.csv", index=False, encoding="utf-8-sig")
    rows, school_data = [], []
    for _, school_row in schools.iterrows():
        school = school_row.school
        local = images[images.school.eq(school)]
        exact = distributions[distributions.school.eq(school)]
        urls = provenance[provenance['学校'].eq(school)]
        official = sorted({url for url in urls.source_url if (urlparse(url).hostname or "").endswith("edu.cn")})
        school_sources = [row for row in sources if row["school"] == school]
        missing = []
        for year in range(2022, 2027):
            image_year = local[pd.to_numeric(local.year).eq(year)]
            label_year = programs[programs.school.eq(school) & pd.to_numeric(programs.year).eq(year)]
            exact_year = exact[pd.to_numeric(exact.year).eq(year)]
            q = quotas[quotas.school.eq(school) & pd.to_numeric(quotas.year).eq(year)]
            n_images = len(image_year)
            readable = int(pd.to_numeric(image_year.score_row_count).sum()) if n_images else 0
            n_exact = int(exact_year.iloc[0].candidate_n) if len(exact_year) else 0
            quota_count = int(pd.to_numeric(q.strict_ordinary_net_records).sum()) if len(q) else 0
            if n_exact:
                status = "审计通过经验Q10"
            elif n_images and readable:
                status = "名单可读但拟录取口径未闭环"
            elif n_images:
                status = "已有原件，未取得可用初试总分"
            else:
                status = "当前入口未取得逐人名单"
            if not n_exact:
                missing.append(f"{year}年拟录取名单口径或摘要核对")
            rows.append({"school": school, "year": year, "roster_images": n_images,
                "parsed_images": int(image_year.layout_status.eq("parsed").sum()),
                "readable_initial_score_rows": readable, "exact_candidate_n": n_exact,
                "empirical_q10": float(exact_year.iloc[0].score_q10) if len(exact_year) else None,
                "label_status": status, "validation_status": ";".join(sorted(set(label_year.validation_status))),
                "strict_before_deadline_quota_records": quota_count,
                "remaining_need": "" if n_exact else "最终录取状态、目标人群、漏页及独立摘要核对；不能以复试名单代替",
                "official_final_roster_reverified_this_refresh": False})
        q27 = quotas[quotas.school.eq(school) & pd.to_numeric(quotas.year).eq(2027)]
        strict27 = int(pd.to_numeric(q27.strict_ordinary_net_records).sum()) if len(q27) else 0
        school_quota=quota_records[quota_records.school.eq(school)]
        quota_evidence=[{"unit":r.unit, "netSeats":int(float(r.current_net_quota)),
            "publishDate":r.effective_publish_date,"deadline":r.registration_deadline,
            "url":r.primary_source_url,"method":r.net_method,"reviewStatus":r.review_status,
            "unitLinked":truth(r.unit_link_verified),"usedInProduction":False} for r in school_quota.itertuples()]
        if not strict27:
            missing.insert(0, "2027年报名截止前可见的普通统考净名额及实际接收推免数")
        elif len(school_quota) and not school_quota.unit_link_verified.map(truth).any():
            missing.insert(0,"已取得学院净名额，但尚需核对其与校级预测标签的培养单位对应关系")
        item = {"school": school, "rosterImages": len(local), "parsedImages": int(local.layout_status.eq("parsed").sum()),
            "readableRows": int(pd.to_numeric(local.score_row_count).sum()),
            "exactYears": sorted(map(int, exact.year)), "exactCandidates": int(exact.candidate_n.sum()),
            "strictQuota2027": bool(strict27), "units": sorted(set(index[index.school.eq(school)].college) - {""}),
            "quotaEvidence2027":quota_evidence,
            "missing": missing, "officialLinks": [{"title": r["title"], "url": r["source_url"], "publishDate": r["publish_date"]} for r in school_sources if r["source_role"] not in {"unavailable_roster", "retest_results"}],
            "existingOfficialSourceLinks": official[:5],
            "needsForecastReview": school == "同济大学",
            "evidenceStatus": "已补审计名单，前瞻预测需复核" if school == "同济大学" else "本轮名单及分数列核查已记录",
            "cutoffCorrections": [{"year": 2025, "previous": 323, "verified": 385}, {"year": 2026, "previous": 324, "verified": 396}] if school == "同济大学" else [],
            "currentDistribution": [{"year": int(r.year), "n": int(r.candidate_n), "q10": float(r.score_q10),
                "minimum": float(r.score_min), "median": float(r.score_q50), "maximum": float(r.score_max)} for _, r in exact.iterrows()],
            "knownEvent": {"year": 2027, "name": "432统计学2027年考试大纲调整", "publishDate": "2026-06-26",
                "url": "https://yz.tongji.edu.cn/info/1018/4206.htm", "impactEstimated": False,
                "description": "官方已发布调整；新大纲参考茆第4版、贾第9版。存在性已核实，分数冲击方向和情景权重尚未由历史事件估计。"} if school == "同济大学" else None}
        school_data.append(item)
    coverage = pd.DataFrame(rows)
    if len(coverage) != 405 or coverage.duplicated(["school", "year"]).any():
        raise ValueError("Incomplete or duplicate school-year inventory")
    coverage.to_csv(DATA / "coverage_by_school_year.csv", index=False, encoding="utf-8-sig")
    summary.update(header_audited_images=len(header_records),
        header_geometry_disagreements=sum(bool(row.get("score_column_disagrees")) for row in header_records),
        no_identifiable_initial_score_column=sum(bool(row.get("error")) for row in header_records),
        supplemental_official_sources=len(sources), secondary_metadata_changes=len(metadata_changes))
    save(DATA / "summary.json", summary)
    payload = {"summary": summary, "experiment": experiment, "schools": school_data,
        "definition": "本轮数据证据快照与原2027冻结预测分开；审计通过不等于官方逐人原件均已取得，也不等于预测正确概率。",
        "dataDeadline": "2026-10-24T22:00:00+08:00", "snapshotCapturedAt": summary["generated_at"]}
    save(ROOT / "app/data/evidence-refresh.json", payload)
    save(DATA / "school_evidence_summary.json", {"summary": summary, "schools": school_data})
    print(json.dumps({"coverage_rows": len(coverage), "schools": len(school_data), "sources": len(sources), "metadata_changes": len(metadata_changes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
