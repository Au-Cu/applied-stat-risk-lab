from __future__ import annotations

import unittest

import pandas as pd

from candidate_score_layer import (
    candidate_distribution_by_program,
    exact_q10_by_program,
    validate_candidate_scores,
)


class CandidateScoreLayerTests(unittest.TestCase):
    def test_only_clean_normal_exam_rows_form_exact_label(self):
        rows = []
        for score in range(300, 310):
            rows.append({
                "school": "测试大学",
                "year": 2026,
                "major_code": "025200",
                "study_mode": "全日制",
                "candidate_type": "normal_exam",
                "initial_score": score,
                "special_plan": "false",
                "adjustment_status": "一志愿",
                "full_time": "true",
                "label_available_date": "2027-04-01",
                "source_url": "https://example.edu/list.pdf",
                "model_eligible": "true",
            })
        rows.append({**rows[0], "candidate_type": "special", "initial_score": 499, "model_eligible": "false"})
        frame = pd.DataFrame(rows)
        report = validate_candidate_scores(frame)
        self.assertEqual(report["errors"], [])
        exact = exact_q10_by_program(frame)
        self.assertEqual(len(exact), 1)
        self.assertEqual(int(exact.iloc[0]["candidate_n"]), 10)
        self.assertAlmostEqual(float(exact.iloc[0]["q10_exact"]), 300.9, places=6)

        distribution = candidate_distribution_by_program(frame, bootstrap_draws=100)
        self.assertEqual(len(distribution), 1)
        self.assertAlmostEqual(float(distribution.iloc[0]["score_q50"]), 304.5, places=6)
        self.assertAlmostEqual(float(distribution.iloc[0]["score_iqr"]), 4.5, places=6)
        self.assertAlmostEqual(
            float(distribution.iloc[0]["lower_tail_span_q50_q10"]),
            3.6,
            places=6,
        )
        self.assertGreater(float(distribution.iloc[0]["q10_bootstrap_sd"]), 0.0)


if __name__ == "__main__":
    unittest.main()
