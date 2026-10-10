from __future__ import annotations

import unittest

from interval_calibration import (
    RobustOriginFloorCalibrator,
    prequential_robust_origin_floor,
)


def _row(school: str, year: int, actual: float, center: float) -> dict:
    return {
        "school": school,
        "year": year,
        "actual": actual,
        "weight": 1.0,
        "pred_q50": center,
        "pred_q80": center + 5.0,
        "pred_q90": center + 8.0,
        "pred_q95": center + 10.0,
        "history_n": 3,
        "history_weight_mean": 0.6,
        "history_margin_mad": 8.0,
        "history_interpolation_share": 0.5,
        "history_minimum_share": 0.5,
        "history_official_share": 0.5,
        "is_985": False,
        "national_zone": "A",
        "selected_model": "robust_margin_anchor",
    }


class RobustOriginFloorTests(unittest.TestCase):
    def test_never_narrows_raw_upper_quantiles(self):
        history = [
            _row(f"A{i}", 2024, 370 + i, 350 + i / 2) for i in range(30)
        ]
        calibrator = RobustOriginFloorCalibrator.fit(history)
        future = _row("future", 2025, 0, 360)
        result = calibrator.apply([future])[0]
        self.assertGreaterEqual(result["robust_q80"], future["pred_q80"])
        self.assertGreaterEqual(result["robust_q90"], future["pred_q90"])
        self.assertGreaterEqual(result["robust_q95"], future["pred_q95"])
        self.assertLessEqual(result["robust_q80"], result["robust_q90"])
        self.assertLessEqual(result["robust_q90"], result["robust_q95"])

    def test_prequential_path_does_not_use_current_origin(self):
        rows = [
            _row(f"A{i}", 2024, 360 + i / 10, 350) for i in range(30)
        ] + [
            _row(f"B{i}", 2025, 500, 350) for i in range(30)
        ]
        calibrated = prequential_robust_origin_floor(rows)
        first = [row for row in calibrated if row["year"] == 2024]
        second = [row for row in calibrated if row["year"] == 2025]
        self.assertTrue(all(row["robust_calibration_prior_rows"] == 0 for row in first))
        self.assertTrue(all(row["robust_calibration_prior_rows"] == 30 for row in second))
        # If the 2025 outcomes had leaked, the robust upper bound would be near
        # 500 rather than being determined by the modest 2024 residuals.
        self.assertTrue(all(row["robust_q90"] < 400 for row in second))


if __name__ == "__main__":
    unittest.main()
