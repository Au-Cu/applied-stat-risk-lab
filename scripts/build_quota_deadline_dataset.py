"""Build an auditable, deadline-vintage research dataset; never train or publish forecasts.

Numerical review decisions below are deliberately explicit. A discovery hit is
not a verified quota; planned recommendation, actual acceptance, and later
re-examination plans are kept distinct. Source captures are aggregate only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data/research/quota_deadline_20261023"
OUT = ROOT / "output/research/quota_deadline_20261023"
SNAP = OUT / "snapshots"
TZ = ZoneInfo("Asia/Shanghai")
sys.stdout.reconfigure(encoding="utf-8")

CALENDARS = [
    (2022, "2021-10-05", "2021-10-25", "2021-09-24", "2021-09-27", "calendar_2022"),
    (2023, "2022-10-05", "2022-10-25", "2022-09-24", "2022-09-27", "calendar_2023"),
    (2024, "2023-10-08", "2023-10-25", "2023-09-24", "2023-09-27", "calendar_2024_primary"),
    (2025, "2024-10-15", "2024-10-28", "2024-10-09", "2024-10-12", "calendar_2025"),
    (2026, "2025-10-16", "2025-10-27", "2025-10-10", "2025-10-13", "calendar_2026"),
    (2027, "2026-10-15", "2026-10-24", "2026-10-09", "2026-10-12", "calendar_2027"),
]


def read_meta(source_id):
    return json.loads((SNAP / f"{source_id}.json").read_text(encoding="utf-8"))


def read_text(source_id):
    return (SNAP / f"{source_id}.txt").read_text(encoding="utf-8")


def target_rows(source_id):
    meta = read_meta(source_id)
    tables = meta.get("target_tables")
    if tables is None:
        from collect_quota_evidence import EvidenceHTML
        parser = EvidenceHTML()
        parser.feed((SNAP / f"{source_id}.html").read_text(encoding="utf-8"))
        tables = parser.tables
    rows = [row for table in tables for row in table if "应用统计" in " ".join(row) or "025200" in " ".join(row)]
    return list({tuple(row): row for row in rows}.values())


def timing(published, deadline, precision="date"):
    if not published:
        return "时间待核"
    value = datetime.fromisoformat(published).replace(tzinfo=TZ)
    end = datetime.fromisoformat(deadline).replace(tzinfo=TZ)
    if value.date() < end.date():
        return "截止前"
    if value.date() > end.date():
        return "截止后"
    if precision != "minute":
        return "截止当日时刻待核"
    return "截止前" if value <= end else "截止后"


def build_records():
    records = []
    def add(school, year, unit, kind, source_id, published=None, *, reported=None, total=None,
            accepted=None, planned=None, special="未明确拆分", sources=(), total_date=None,
            accepted_date=None, net_date=None, precision="date", locator="", notes="", basis="reviewed_aggregate"):
        ids = list(dict.fromkeys([source_id, *sources]))
        sources_meta = [read_meta(source) for source in ids]
        if any(row["status"] != "ok" for row in sources_meta):
            raise ValueError(f"Unavailable supporting source: {ids}")
        identifier = hashlib.sha256(f"{school}|{year}|{unit}|{kind}|{source_id}".encode()).hexdigest()[:14]
        records.append({
            "record_id": identifier, "school": school, "year": year, "unit": unit,
            "major_code": "025200", "study_mode": "全日制", "record_kind": kind,
            "reported_exam_quota": reported, "total_plan_same_scope": total,
            "accepted_recommended": accepted, "planned_recommended": planned,
            "total_less_accepted": total - accepted if total is not None and accepted is not None else None,
            "special_scope": special, "effective_publish_date": published,
            "publication_precision": precision, "total_plan_publish_date": total_date,
            "accepted_recommended_publish_date": accepted_date, "exam_quota_publish_date": net_date,
            "source_ids": ids, "primary_source_url": sources_meta[0]["url"],
            "supporting_urls": [row["url"] for row in sources_meta[1:]],
            "source_sha256": [row["sha256"] for row in sources_meta], "source_locator": locator,
            "publication_date_basis": basis,
            "historical_snapshot_limitation": "现存官方页标注日或官方目录日期；本次快照不是当年的网页存档",
            "human_review_status": "已核对原文，待用户人工终审", "notes": notes,
        })

    cufe_dates = {2022: "2021-10-24", 2023: "2022-10-18", 2024: "2023-10-17",
                  2025: "2024-10-21", 2026: "2025-10-16", 2027: "2026-10-16"}
    for year, published in cufe_dates.items():
        source = f"cufe_{year}"
        attachment = f"{source}_attach1"
        match = re.search(r"应用统计[（(]专硕[）)]\s+(\d+)", read_text(attachment))
        if not match:
            raise ValueError(f"Cannot identify CUFE MAS, rather than academic applied statistics: {year}")
        add("中央财经大学", year, "统计与数学学院", "推免后统考公告", source, published,
            reported=int(match.group(1)), special="明确不含专项", sources=[attachment], net_date=published,
            locator="附件：统计与数学学院—应用统计（专硕）行；不能误用经济学统计学中的应用统计",
            notes="官方根据已接收推免公布的剩余普通统考计划；不再次扣推免，不是最终录取人数。")

    for year, published in [(2024, "2023-10-24"), (2025, "2024-10-15")]:
        pdf = f"sjtu_{year}_pdf"
        line = next(line for line in read_text(pdf).splitlines() if "025200" in line and "应用统计" in line)
        value = int(re.search(r"(\d+)\s*$", line).group(1))
        add("上海交通大学", year, "数学科学学院", "推免后统考公告", pdf, published,
            reported=value, sources=[f"sjtu_{year}_publication_list"], net_date=published,
            special="专项另列，专业分配待核", locator=line.strip(),
            notes="日期从校信息公开网对应标题条目核对；附件路径中的2024/04不能当成2024招生年度的发布日。")
    row = next(row for row in target_rows("sjtu_2027") if "025200" in row)
    add("上海交通大学", 2027, "数学科学学院", "推免后统考公告", "sjtu_2027", "2026-10-15",
        reported=int(row[-1]), special="专项另列，专业分配待核", net_date="2026-10-15",
        locator=" | ".join(row), notes="学校报考公告说明将按实际推免录取数发布分专业统考计划；报名首日发布仍在截止前。")
    add("上海交通大学", 2026, "数学科学学院", "公告日期已核，数值正文待取", "sjtu_2026_publication", "2025-10-15",
        sources=["sjtu_2026"], net_date="2025-10-15", locator="信息公开网标题及发布时间；原招生网链接现返回首页",
        notes="旧表保留43人线索。本轮不把未从当前官方正文重新取到的数字当作新核定值。")

    row = next(row for row in target_rows("xmu_2026_net") if "全日制" in row and "非全日制" not in row)
    add("厦门大学", 2026, "统计学与数据科学系", "推免后统考公告", "xmu_2026_net", "2025-10-09T14:58:00",
        reported=int(row[-1]), special="该表未逐专业说明专项", precision="minute", net_date="2025-10-09T14:58:00",
        locator=" | ".join(row), notes="正文明确根据实际推免招生情况调整；排除了王亚南经济研究院非全日制25人。")
    line = next(line for line in read_text("notice_d4eead0c2a_attach1").splitlines() if "025200" in line and "全日制" in line)
    add("厦门大学", 2027, "统计学与数据科学系", "推免后统考公告", "notice_d4eead0c2a", "2026-10-10",
        reported=int(re.search(r"(\d+)\s*$", line).group(1)), sources=["notice_d4eead0c2a_attach1"], net_date="2026-10-10",
        special="明确不含少干、士兵等专项", locator=line.strip(),
        notes="附件首页说明3明确排除非全日制、少干及士兵等专项。采用校级扣除拟录取推免后的统考计划，不把未发布的最终录取人数作为输入。")

    for year, accepted_date, total_date, total_source in [
        (2026, "2025-10-10", "2025-10-02", "notice_978f5caf82"),
        (2027, "2026-10-16", "2026-09-28", "notice_953d653ca6"),
    ]:
        actual = f"dhu_{year}_actual"
        catalogue = f"dhu_{year}_unit_catalog"
        actual_row = next(row for row in target_rows(actual) if "025200" in row)
        plan_row = next(row for row in target_rows(catalogue) if "025200" in row)
        plan_label_column = next(index for index, cell in enumerate(plan_row) if "应用统计" in cell)
        plan_total = int(next(cell for cell in plan_row[plan_label_column + 1:] if re.fullmatch(r"\d+", cell)))
        add("东华大学", year, "数学与统计学院", "总计划及实际接收推免", actual, accepted_date,
            total=plan_total, accepted=int(actual_row[4]), total_date=total_date, accepted_date=accepted_date,
            sources=[catalogue, f"dhu_{year}_major_catalog", total_source], special="扣推免可核，专项仍需复核",
            locator="实际接收表："+" | ".join(actual_row)+"；目录："+" | ".join(plan_row),
            notes="目录由公开招生系统的年份、学院、专业选择器读取，专业详情核对为全日制。差额不冒充已核定普通计划。")

    swufe_actual = {2022: ("notice_1ce84d274c", "2021-09-30"), 2023: ("swufe_2023_actual", "2022-09-30"),
                    2024: ("notice_1ac3111983", "2023-10-07"), 2025: ("swufe_2025_actual", "2024-10-09"),
                    2026: ("notice_f6c32f2643", "2025-10-09"), 2027: ("notice_664f2f2604", "2026-10-09")}
    for year, (source, published) in swufe_actual.items():
        rows = [row for row in target_rows(source) if "025200" in row]
        accepted = sum(int(row[4]) for row in rows)
        total = None
        extras = []
        total_date = None
        if year in (2025, 2027):
            catalogue = f"swufe_{year}_catalog"
            total = int(next(row for row in target_rows(catalogue) if "025200应用统计" in row)[1])
            extras = [catalogue, "notice_83e107d755" if year == 2025 else "notice_d8a5267358"]
            total_date = "2024-10-08" if year == 2025 else "2026-10-08"
        add("西南财经大学", year, "统计学院" if year <= 2025 else "统计与数据科学学院",
            "总计划及实际接收推免" if total is not None else "仅实际接收推免", source, published,
            total=total, accepted=accepted, sources=extras, total_date=total_date, accepted_date=published,
            special="目录明确含专项，尚未拆分", locator="；".join(" | ".join(row) for row in rows),
            notes="2022、2023按本研究不区分方向的口径汇总同专业各方向。目录规定差额一般为统考下界，不能将差额认作精确普通统考计划。")

    for year, source, notice, published in [(2026, "ecust_2026_actual_pdf", "ecust_2026_actual_notice", "2025-10-21"),
                                            (2027, "ecust_2027_actual_pdf", "ecust_2027_actual", "2026-10-21")]:
        line = next(line for line in read_text(source).splitlines() if "025200" in line and "应用统计" in line)
        match = re.search(r"025200\s*应用统计\s+(\d+)", line)
        add("华东理工大学", year, "数学学院", "仅实际接收推免", notice, published,
            accepted=int(match.group(1)), sources=[source], accepted_date=published,
            locator=" ".join(line.split()), notes="只记录全日制硕士推免列，不把直博人数扣到硕士计划中。尚缺同口径总计划，净名额留空。")

    # Later re-examination plans are retained as counterexamples, not backfilled.
    later = [
        ("西南大学", 2025, "数学与统计学院", "swu_2025_post_deadline", "2025-03-24T18:40:00", 33, 35, 2, "minute"),
        ("华东师范大学", 2026, "统计学院", "ecnu_2026_post_deadline", "2026-03-19", 60, None, None, "date"),
        ("福州大学", 2026, "数学与统计学院", "fzu_2026_post_deadline", "2026-03-27", 23, None, None, "date"),
        ("辽宁大学", 2026, "数学与统计学院", "lnu_2026_post_deadline", "2026-03-26", None, 41, 4, "date"),
        ("兰州大学", 2026, "数学与统计学院", "lzu_2026_post_deadline", "2026-03-23", 70, 100, 30, "date"),
        ("中山大学", 2026, "数学学院", "sysu_2026_post_deadline", "2026-03-17", 36, 73, 37, "date"),
        ("中山大学", 2026, "数学学院（珠海）", "sysu_2026_zhuhai_post_deadline", "2026-03-18", 6, 21, 15, "date"),
        ("华中师范大学", 2025, "数学与统计学学院", "ccnu_2025_post_deadline", "2025-03-23", 40, None, 9, "date"),
    ]
    for school, year, unit, source, published, quota, total, accepted, precision in later:
        add(school, year, unit, "复试阶段计划（截止后）", source, published, reported=quota, total=total,
            accepted=accepted, precision=precision, special="以复试方案普通/专项说明为准",
            locator="招生计划表—025200应用统计行", notes="只证明该日公开过此值；不能据此推定它在上年报名截止前已公开。华东师大页面标注日与正文落款另存，均在截止后。")

    add("华中科技大学", 2026, "数学与统计学院", "拟接收推免计划，非实际", "hust_2026_recommended_plan_only", "2025-09-13",
        planned=18, locator="025200应用统计—拟接收计划数18；注：实际人数视申请及考核",
        notes="保留18为计划推免，不写入实际接收推免字段。")
    for year, total, planned in [(2025, 244, 61), (2026, 277, 70)]:
        source = f"bnu_{year}_catalog"
        if not re.search(r"025200\s*应用统计", read_text(source)):
            raise ValueError("BNU catalogue target not found")
        add("北京师范大学", year, "统计学院", "招生目录预估计划", source, total=total, planned=planned,
            locator=f"025200应用统计—招生人数{total}；接收推免生{planned}人左右",
            notes="‘左右’是拟接收规模，不是已接收人数；目录页面未显示可核发布日期，不能用抓取日或URL代替。")
    add("河北工业大学", 2027, "理学院", "招生目录预估计划", "hebut_2027_catalog_pdf",
        reported=17, total=22, planned=5, locator="025200原表总数32；统考拟招17、推免拟招5、非全日制10",
        notes="同口径全日制22=原表32-非全日制10。推免5是拟招数，不是实际接收数；尚缺官方页面发布日期。")
    add("南京大学", 2025, "数学学院", "仅总计划，实际推免待补", "nju_2025_total_pdf", total=25,
        locator="021数学学院—025200应用统计△—全日制专业学位25",
        notes="目录要求另查实际推免人数。本轮没有将未知推免当作0，PDF本身未给发布日。")

    # This PDF is an updated catalogue, not an independently dated final snapshot.
    from pypdf import PdfReader
    for page_idx, page in enumerate(PdfReader(SNAP / "sdu_2026_directory_pdf.pdf").pages):
        text = page.extract_text(extraction_mode="layout") or ""
        matches = re.findall(r"025200应用统计\s+(\d+)", text)
        if not matches:
            continue
        heading = [line.strip() for line in text.splitlines()[:8] if re.search(r"学院|研究院", line)]
        unit = heading[0] if heading else f"目录第{page_idx + 1}页所属培养单位（待核名称）"
        for number in matches:
            add("山东大学", 2026, unit, "净计划数可读，值版本日期待核", "sdu_2026_directory_notice",
                reported=int(number), sources=["sdu_2026_directory_pdf"], total_date="2025-09-26",
                locator=f"目录PDF第{page_idx + 1}页—025200应用统计行",
                notes="公告说10月20日左右会按推免更新目录，但未给出当前各数值的独立更新时间。9月26日不能直接冒充更新后数值发布日期。")

    for unit, total, accepted, quota, note in [
        ("数学学院", 50, 30, 21, "推免30含专项1；不能机械用50-30替代官方统考列21。"),
        ("统计与数据科学学院（普通项目）", 142, 100, 46, "四方向总计划38+38+33+33，推免24+24+25+27；含专项推免4，官方统考合并列46。"),
        ("统计与数据科学学院（上财—波士顿项目）", 20, 0, 20, "独立合作项目保留单行，不能与另一考试/培养项目无条件合并。"),
    ]:
        add("上海财经大学", 2026, unit, "复试前公开计划（截止后）", "notice_b39a0c42f9", "2026-02-26",
            reported=quota, total=total, accepted=accepted, sources=["sufe_2026_post_deadline_pdf"],
            special="按官方列值处理，推免含专项", locator="统考计划PDF：对应学院025200行及备注",
            notes=note+"发布日期是次年2月26日，不能回填2025年10月报名截止信息集。")
    return records


def export_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    calendars = []
    for year, start, end, pre_start, pre_end, source_id in CALENDARS:
        source = read_meta(source_id)
        calendars.append({"year": year, "registration_start": start+"T09:00:00+08:00",
                          "registration_deadline": end+"T22:00:00+08:00",
                          "pre_registration_start": pre_start, "pre_registration_end": pre_end,
                          "source_id": source_id, "source_url": source["url"], "source_sha256": source["sha256"]})
    calendar_by_year = {row["year"]: row for row in calendars}
    records = build_records()
    for row in records:
        calendar = calendar_by_year[row["year"]]
        row["registration_start"] = calendar["registration_start"]
        row["registration_deadline"] = calendar["registration_deadline"]
        row["deadline_timing"] = timing(row["effective_publish_date"], row["registration_deadline"], row["publication_precision"])
        if row["record_kind"] == "推免后统考公告":
            row["usability"] = "可核推免后统考计划；专项口径见说明" if row["deadline_timing"] == "截止前" else "不属于截止前可核净计划"
        elif row["record_kind"] == "总计划及实际接收推免":
            row["usability"] = "可核算术差额；不是已核定普通统考计划"
        elif row["deadline_timing"] == "截止后":
            row["usability"] = "仅作事后核对，不得回填报名截止预测"
        else:
            row["usability"] = "证据不完整，暂不作为净名额输入"
        for column in ("reported_exam_quota", "total_plan_same_scope", "accepted_recommended", "planned_recommended"):
            if row[column] is not None and (not isinstance(row[column], int) or row[column] < 0):
                raise ValueError(f"Invalid count: {row['record_id']} {column}")
        if row["record_kind"] == "招生目录预估计划" and row["accepted_recommended"] is not None:
            raise ValueError("Planned recommendation leaked into actual acceptance")
        if row["year"] == 2027 and row["effective_publish_date"] and row["effective_publish_date"][:10] > "2026-10-23":
            raise ValueError("Future publication claimed during collection")
    if len({row["record_id"] for row in records}) != len(records):
        raise ValueError("Duplicate reviewed record")
    schools = list(csv.DictReader((ROOT / "data/processed/schools.csv").open(encoding="utf-8-sig")))
    coverage = []
    for school in schools:
        for year in range(2022, 2028):
            rows = [row for row in records if row["school"] == school["school"] and row["year"] == year]
            direct = [row for row in rows if row["record_kind"] == "推免后统考公告" and row["deadline_timing"] == "截止前"]
            status = "已有截止前推免后净计划" if direct else "已有局部证据，仍需补齐" if rows else "尚未完成逐年核验，不代表无公开数据"
            coverage.append({"school": school["school"], "year": year, "reviewed_records": len(rows),
                             "before_deadline_net_records": len(direct), "coverage_status": status,
                             "registration_deadline": calendar_by_year[year]["registration_deadline"]})
    sources = []
    for path in sorted(SNAP.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("id"):
            sources.append({key: row.get(key) for key in ("id", "school", "year", "url", "parent_id", "method", "body", "status", "collected_at", "sha256", "bytes", "snapshot", "error")})
    source_by_id = {row["id"]: row for row in sources}
    for row in records:
        for source_id in row["source_ids"]:
            source = source_by_id[source_id]
            blob = ROOT / source["snapshot"]
            if hashlib.sha256(blob.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError(f"Source snapshot hash changed: {source_id}")
    summary = {"as_of_date": "2026-10-23", "information_boundary": "报名截止日22:00（北京时间），不是报名开始日",
               "records": len(records), "schools_with_reviewed_records": len({row['school'] for row in records}),
               "target_schools": len(schools), "target_school_years": len(coverage),
               "covered_school_years": len({(row['school'], row['year']) for row in records}),
               "deadline_timing": dict(Counter(row['deadline_timing'] for row in records)),
               "record_kinds": dict(Counter(row['record_kind'] for row in records)),
               "before_deadline_post_recommendation_records": sum(row['record_kind']=='推免后统考公告' and row['deadline_timing']=='截止前' for row in records),
               "before_deadline_explicit_ordinary_records": sum(row['record_kind']=='推免后统考公告' and row['deadline_timing']=='截止前' and row['special_scope'].startswith('明确不含') for row in records),
               "source_status": dict(Counter(row['status'] for row in sources)),
               "review_status": "首批研究台账，尚非81校逐年全覆盖；待用户人工终审",
               "frozen_model_changed": False,
               "limitations": ["现存网页标注日期不等于取得了当时的网页存档。", "已扣推免不必然等于已扣所有专项；专项口径单列。",
                               "只有日期而无时刻的截止当日公告不直接判为可用。", "目录拟招推免数、实际接收数和直博人数分别处理。",
                               "总计划减已接推免可能含专项，或只是公告规定的统考下界，不冒充核定普通计划。"]}
    payload = {"summary": summary, "records": records, "calendars": calendars, "coverage": coverage, "sources": sources}
    (OUT / "quota_deadline_dataset.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    export_csv(OUT / "quota_records.csv", records)
    export_csv(OUT / "registration_calendar.csv", calendars)
    export_csv(OUT / "coverage_gaps.csv", coverage)
    export_csv(OUT / "source_snapshot_index.csv", sources)
    (OUT / "collection_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
