from __future__ import annotations

import math
import unittest

import pandas as pd

from quota_features import DEFAULT_PATH, attach_quota_features, load_quota_events, validate_quota_events


class QuotaFeatureTests(unittest.TestCase):
    def test_strict_policy_excludes_registration_day(self):
        strict = load_quota_events(strict=True)
        relaxed = load_quota_events(strict=True, include_registration_window=True)
        self.assertEqual(len(strict), 6)
        self.assertEqual(len(relaxed), 7)
        self.assertFalse((strict["availability_stage"] == "registration_window").any())

    def test_regular_quota_column_is_not_shifted(self):
        strict = load_quota_events(strict=True)
        sjtu = strict[(strict["school"] == "上海交通大学") & (strict["year"] == 2026)].iloc[0]
        self.assertEqual(float(sjtu["_regular_value"]), 43.0)
        self.assertTrue(pd.isna(sjtu["published_recommended_quota"]))

    def test_no_future_event_leaks_into_prior_year(self):
        events = load_quota_events(strict=True)
        frame = pd.DataFrame([
            {"school": "河北工业大学", "year": 2026},
            {"school": "河北工业大学", "year": 2027},
        ])
        attached = attach_quota_features(frame, events)
        self.assertEqual(int(attached.iloc[0]["quota_missing"]), 1)
        self.assertEqual(float(attached.iloc[1]["quota_regular_value"]), 17.0)

    def test_log_shock_uses_prior_official_event(self):
        events = load_quota_events(strict=True)
        frame = pd.DataFrame([{"school": "重庆大学", "year": 2026}])
        attached = attach_quota_features(frame, events).iloc[0]
        self.assertAlmostEqual(float(attached["quota_shock_log"]), math.log(39 / 35), places=10)

    def test_source_table_passes_contract(self):
        raw = pd.read_csv(DEFAULT_PATH, encoding="utf-8")
        report = validate_quota_events(raw)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["errors"], [])


if __name__ == "__main__":
    unittest.main()
