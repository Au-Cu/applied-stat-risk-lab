"""Chronology, population scope, no-fallback and covariance regression tests."""
import copy
import unittest

import numpy as np
import pandas as pd

from deadline_quota_research import (
    QuotaDesign, assess_record, attach_current_features, build_ledger, fit_covariate_state,
)
from experiment_deadline_quota import metrics, paired_uncertainty
from experiment_statistical_inference import fit_state


def record(**overrides):
    item = {"record_id": "r1", "school": "中央财经大学", "year": 2025,
        "unit": "统计与数学学院", "major_code": "025200", "study_mode": "全日制",
        "record_kind": "推免后统考公告", "reported_exam_quota": 27,
        "ordinary_scope_verified": True, "review_status": "已核对原文，待用户人工终审",
        "source_grade": "A-official", "source_ids": ["a"], "source_sha256": ["a" * 64],
        "effective_publish_date": "2024-10-26", "exam_quota_publish_date": "2024-10-26",
        "publication_precision": "date", "registration_deadline": "2024-10-28T22:00:00+08:00",
        "capture_time": "2026-10-23T18:00:00+08:00", "observed_before_deadline": False,
        "model_eligible": False}
    item.update(overrides)
    return item


class DeadlineQuotaTests(unittest.TestCase):
    def setUp(self):
        self.schools = pd.DataFrame({"school": ["中央财经大学", "厦门大学"],
            "unit_2026": ["统计与数学学院", "统计学与数据科学系；王亚南经济研究院"]})

    def test_deadline_not_registration_start(self):
        self.assertTrue(assess_record(record(), "strict_ordinary")["evidence_eligible"])

    def test_after_deadline_is_excluded(self):
        self.assertFalse(assess_record(record(effective_publish_date="2024-10-29"), "strict_ordinary")["evidence_eligible"])

    def test_deadline_date_only_is_ambiguous(self):
        self.assertFalse(assess_record(record(effective_publish_date="2024-10-28", exam_quota_publish_date="2024-10-28"), "strict_ordinary")["evidence_eligible"])

    def test_exact_22_clock_is_inclusive(self):
        value = "2024-10-28T22:00:00+08:00"
        item = record(effective_publish_date=value, exam_quota_publish_date=value, publication_precision="datetime")
        self.assertTrue(assess_record(item, "strict_ordinary")["evidence_eligible"])
        item["effective_publish_date"] = "2024-10-28T22:00:01+08:00"
        self.assertFalse(assess_record(item, "strict_ordinary")["evidence_eligible"])

    def test_capture_can_prove_current_visibility_not_publication(self):
        item = record(effective_publish_date=None, exam_quota_publish_date=None,
            capture_time="2024-10-28T21:59:00+08:00", observed_before_deadline=True)
        result = assess_record(item, "strict_ordinary")
        self.assertTrue(result["evidence_eligible"])
        self.assertEqual(result["availability_basis"], "captured_before_deadline")

    def test_later_revised_component_not_parent_date(self):
        item = record(exam_quota_publish_date="2025-02-26")
        self.assertFalse(assess_record(item, "strict_ordinary")["evidence_eligible"])

    def test_total_minus_actual_not_planned_recommended(self):
        item = record(record_kind="总计划及实际接收推免", reported_exam_quota=None,
            total_plan_same_scope=50, accepted_recommended=20, planned_recommended=30,
            total_plan_publish_date="2024-10-20", accepted_recommended_publish_date="2024-10-26")
        result = assess_record(item, "strict_ordinary")
        self.assertTrue(result["evidence_eligible"])
        self.assertEqual(result["current_net_quota"], 30)
        item["accepted_recommended"] = None
        self.assertFalse(assess_record(item, "strict_ordinary")["evidence_eligible"])

    def test_direct_post_recommended_not_deducted_twice(self):
        item = record(accepted_recommended=20)
        self.assertEqual(assess_record(item, "strict_ordinary")["current_net_quota"], 27)

    def test_special_unknown_is_sensitivity_only(self):
        item = record(ordinary_scope_verified=False, special_scope="专项待核")
        self.assertFalse(assess_record(item, "strict_ordinary")["evidence_eligible"])
        self.assertTrue(assess_record(item, "special_scope_sensitivity")["evidence_eligible"])

    def test_nonfulltime_and_rule_candidates_excluded(self):
        for changes in ({"study_mode": "非全日制"}, {"review_status": "规则读取，待核"},
                {"source_grade": "B-reprint"}, {"reported_exam_quota": -1}, {"reported_exam_quota": 0}):
            self.assertFalse(assess_record(record(**changes), "strict_ordinary")["evidence_eligible"])

    def test_conflicting_arithmetic_is_not_picked_silently(self):
        item = record(record_kind="总计划及实际接收推免", total_plan_same_scope=50,
            accepted_recommended=20, reported_exam_quota=31,
            total_plan_publish_date="2024-10-20", accepted_recommended_publish_date="2024-10-26")
        self.assertFalse(assess_record(item, "strict_ordinary")["evidence_eligible"])

    def test_multicollege_label_not_assigned_one_college_quota(self):
        item = record(school="厦门大学", unit="统计学与数据科学系")
        ledger = build_ledger({"records": [item]}, self.schools)
        self.assertTrue(ledger.evidence_eligible.all())
        self.assertFalse(ledger.linked_for_research.any())

    def test_duplicate_school_year_not_summed_or_first_match(self):
        ledger = build_ledger({"records": [record(), record(record_id="r2")]}, self.schools)
        self.assertFalse(ledger.linked_for_research.any())

    def test_calendar_conflict_fails_loudly(self):
        payload = {"records": [record()], "calendars": [{"year": 2025,
            "registration_deadline": "2024-10-27T22:00:00+08:00"}]}
        with self.assertRaises(ValueError):
            build_ledger(payload, self.schools)

    def test_missing_current_year_does_not_carry_forward(self):
        source = record()
        original = copy.deepcopy(source)
        ledger = build_ledger({"records": [source]}, self.schools)
        frame = pd.DataFrame({"school": ["中央财经大学"] * 2, "year": [2025, 2026]})
        result = attach_current_features(frame, ledger, "strict_ordinary")
        self.assertEqual(result.quota_current_net.iloc[0], 27)
        self.assertTrue(np.isnan(result.quota_current_net.iloc[1]))
        self.assertEqual(result.quota_available.iloc[1], 0)
        self.assertEqual(source, original)  # No promotion of immutable parent.

    def test_change_requires_adjacent_same_policy_years(self):
        old = record(record_id="old", year=2023)
        ledger = build_ledger({"records": [record(), old]}, self.schools)
        result = attach_current_features(pd.DataFrame({"school": ["中央财经大学"], "year": [2025]}), ledger, "strict_ordinary")
        self.assertTrue(np.isnan(result.quota_log2_change.iloc[0]))

    def test_training_transform_does_not_use_test_center(self):
        frame = pd.DataFrame({"quota_available": [1, 0], "quota_change_available": [0, 0],
            "quota_log2": [4., np.nan], "quota_log2_change": [np.nan, np.nan]})
        design = QuotaDesign.fit(frame, "level_change")
        future = frame.copy(); future.loc[0, "quota_log2"] = 100.
        design.transform(future)
        self.assertEqual(design.level_center, 4.)
        self.assertTrue(np.isnan(frame.quota_log2.iloc[1]))

    def test_future_quota_cannot_change_past_feature(self):
        old = record(year=2024, effective_publish_date="2023-10-20", exam_quota_publish_date="2023-10-20",
            registration_deadline="2023-10-25T22:00:00+08:00")
        frame = pd.DataFrame({"school": ["中央财经大学"], "year": [2024]})
        first = attach_current_features(frame, build_ledger({"records": [old]}, self.schools), "strict_ordinary")
        future = record(record_id="future", year=2027, reported_exam_quota=999,
            effective_publish_date="2026-10-20", exam_quota_publish_date="2026-10-20",
            registration_deadline="2026-10-24T22:00:00+08:00")
        second = attach_current_features(frame, build_ledger({"records": [old, future]}, self.schools), "strict_ordinary")
        pd.testing.assert_frame_equal(first, second)

    def test_no_features_reproduces_existing_random_intercept(self):
        frame = pd.DataFrame({"school": ["a", "a", "b", "b"], "year": [2022, 2023] * 2,
            "margin": [20., 25., 40., 35.], "observation_variance": [9.] * 4,
            "quota_available": [0] * 4, "quota_change_available": [0] * 4,
            "quota_log2": [np.nan] * 4, "quota_log2_change": [np.nan] * 4})
        baseline = fit_state(frame, "random_intercept")
        design = QuotaDesign.fit(frame, "level_change")
        model = fit_covariate_state(frame, design, (baseline.school_variance, baseline.innovation_variance))
        expected = baseline.predict("a", 2024)
        row = frame.iloc[0].to_dict(); row["year"] = 2024
        self.assertTrue(np.allclose(expected, model.predict(row), atol=.01))
        self.assertGreater(model.predict({**row, "school": "unseen"})[1], 0.)

    def test_scoring_identity_and_single_cluster_limit(self):
        frame = pd.DataFrame({"school": ["a"], "year": [2025], "actual": [10.],
            "evaluation_weight": [1.], "quota_available": [1], "row_wis": [0.],
            **{f"pred_q{q:02d}": [10.] for q in (5, 10, 20, 50, 80, 90, 95)}})
        self.assertEqual(metrics(frame)["wis"], 0.)
        result = paired_uncertainty(frame, frame, "school")
        self.assertIsNone(result["mae_ci90"])


if __name__ == "__main__":
    unittest.main()
