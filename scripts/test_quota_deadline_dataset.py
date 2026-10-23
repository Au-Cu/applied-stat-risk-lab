"""Time-boundary and source/measurement checks for the standalone quota study."""
import json
import unittest
from pathlib import Path

from build_quota_deadline_dataset import OUT, timing


class DeadlineTests(unittest.TestCase):
    def test_during_registration_is_usable_before_deadline(self):
        self.assertEqual(timing("2026-10-16", "2026-10-24T22:00:00+08:00"), "截止前")

    def test_after_deadline_is_not_usable(self):
        self.assertEqual(timing("2026-10-25", "2026-10-24T22:00:00+08:00"), "截止后")

    def test_unknown_time_on_last_day_is_not_assumed(self):
        self.assertEqual(timing("2026-10-24", "2026-10-24T22:00:00+08:00"), "截止当日时刻待核")

    def test_known_time_on_last_day(self):
        deadline = "2026-10-24T22:00:00+08:00"
        self.assertEqual(timing("2026-10-24T21:59:00", deadline, "minute"), "截止前")
        self.assertEqual(timing("2026-10-24T22:00:00", deadline, "minute"), "截止前")
        self.assertEqual(timing("2026-10-24T22:01:00", deadline, "minute"), "截止后")

    def test_missing_date_is_not_collection_date(self):
        self.assertEqual(timing(None, "2026-10-24T22:00:00+08:00"), "时间待核")

    def test_year_specific_deadline(self):
        self.assertEqual(timing("2024-10-28T21:00:00", "2024-10-28T22:00:00+08:00", "minute"), "截止前")
        self.assertEqual(timing("2025-10-28", "2025-10-27T22:00:00+08:00"), "截止后")


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((OUT / "quota_deadline_dataset.json").read_text(encoding="utf-8"))

    def test_full_scope_gap_grid_not_false_full_coverage(self):
        self.assertEqual(len(self.data["coverage"]), 81 * 6)
        self.assertLess(self.data["summary"]["covered_school_years"], 81 * 6)

    def test_planned_is_not_actual(self):
        hust = next(row for row in self.data["records"] if row["school"] == "华中科技大学")
        self.assertEqual(hust["planned_recommended"], 18)
        self.assertIsNone(hust["accepted_recommended"])
        self.assertIsNone(hust["total_less_accepted"])

    def test_cufe_is_specialized_masters_and_not_academic_same_name(self):
        rows = sorted((row for row in self.data["records"] if row["school"] == "中央财经大学"), key=lambda row: row["year"])
        self.assertEqual([row["reported_exam_quota"] for row in rows], [29, 26, 25, 27, 25, 24])
        self.assertTrue(all(row["deadline_timing"] == "截止前" for row in rows))

    def test_sufe_specials_not_subtracted_twice_or_hidden(self):
        row = next(row for row in self.data["records"] if row["school"] == "上海财经大学" and row["unit"] == "数学学院")
        self.assertEqual(row["reported_exam_quota"], 21)
        self.assertEqual(row["total_less_accepted"], 20)
        self.assertEqual(row["deadline_timing"], "截止后")

    def test_unknown_quota_is_not_zero(self):
        row = next(row for row in self.data["records"] if row["school"] == "南京大学")
        self.assertEqual(row["total_plan_same_scope"], 25)
        self.assertIsNone(row["accepted_recommended"])
        self.assertIsNone(row["reported_exam_quota"])

    def test_net_quota_and_explicit_ordinary_scope_are_not_conflated(self):
        summary = self.data["summary"]
        self.assertEqual(summary["before_deadline_post_recommendation_records"], 11)
        self.assertEqual(summary["before_deadline_explicit_ordinary_records"], 7)
        xmu = next(row for row in self.data["records"] if row["school"] == "厦门大学" and row["year"] == 2027)
        self.assertEqual(xmu["reported_exam_quota"], 49)
        self.assertIn("明确不含", xmu["special_scope"])

    def test_department_and_study_mode_not_silently_pooled(self):
        rows = [row for row in self.data["records"] if row["school"] == "中山大学"]
        self.assertEqual({row["reported_exam_quota"] for row in rows}, {36, 6})
        self.assertEqual(len({row["unit"] for row in rows}), 2)
        hebut = next(row for row in self.data["records"] if row["school"] == "河北工业大学")
        self.assertEqual(hebut["total_plan_same_scope"], 22)
        self.assertEqual(hebut["reported_exam_quota"], 17)
        self.assertIsNone(hebut["accepted_recommended"])

    def test_revised_value_date_not_initial_catalogue_date(self):
        rows = [row for row in self.data["records"] if row["school"] == "山东大学"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["deadline_timing"] == "时间待核" for row in rows))

    def test_every_record_has_accessible_provenance_and_no_candidate_rows(self):
        sources = {row["id"]: row for row in self.data["sources"]}
        for row in self.data["records"]:
            for source in row["source_ids"]:
                self.assertEqual(sources[source]["status"], "ok")
                self.assertEqual(len(sources[source]["sha256"]), 64)
            self.assertNotIn("candidate_id", row)
            self.assertEqual(row["major_code"], "025200")


if __name__ == "__main__":
    unittest.main()
