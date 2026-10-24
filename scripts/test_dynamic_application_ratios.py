"""Protect quota provenance and the unit/denominator boundaries, without fitting a model."""
import unittest
from unittest.mock import patch
import build_dynamic_application_ratios as pipeline


class DynamicRatiosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=pipeline.build(write=False)
        cls.rows={r['source_rank']:r for r in cls.data['records']}
        cls.quotas={q['quota_id']:q for q in cls.data['quotas']}

    def test_exact_transcription_and_target_coverage(self):
        raw=pipeline.read_csv(pipeline.INPUT/'screenshot_rows.csv')
        self.assertEqual([int(r['rank']) for r in raw],list(range(1,243)))
        self.assertEqual(len(self.rows),108)
        self.assertEqual(len({r['school'] for r in self.rows.values()}),78)
        self.assertEqual(self.data['summary']['target_school_count'],81)
        self.assertEqual(self.rows[29]['observed_applicants'],85)  # Repeated top card is not added 25 times.

    def test_absence_does_not_become_zero_applications(self):
        missing=[r for r in self.data['school_coverage'] if r['observed_units']==0]
        self.assertEqual({r['school'] for r in missing},{'清华大学','合肥工业大学','湖南大学'})
        self.assertTrue(all('不能记零' in r['status'] for r in missing))
        self.assertIsNone(self.rows[49]['sample_dynamic_ratio'])  # Tongji remains an evidence gap.
        self.assertEqual(self.rows[49]['observed_applicants'],64)

    def test_no_double_subtraction_of_stated_exam_quota(self):
        sufe=self.rows[66]
        self.assertEqual(sufe['net_exam_quota'],21)
        self.assertAlmostEqual(sufe['sample_dynamic_ratio'],51/21)

    def test_planned_recommendations_not_mislabelled_actual(self):
        fixed=self.quotas['ecnu_2027_ordinary']
        self.assertIsNone(fixed['accepted_recommended'])
        self.assertEqual(fixed['planned_recommended'],59)
        self.assertEqual(pipeline.net_quota(fixed),38)
        self.assertIsNone(pipeline.net_quota(dict(quota_id='planned',quota_basis='total_less_actual_recommended',
            total_plan=100,planned_recommended=60)))
        wrong={**fixed,'stated_exam_quota':39}
        with self.assertRaises(ValueError):pipeline.net_quota(wrong)

    def test_actual_incoming_recommendations_used_once(self):
        self.assertEqual(self.rows[26]['net_exam_quota'],57-30)
        self.assertEqual(self.rows[52]['net_exam_quota'],36-13)  # Not proposed 16 recommendations.
        self.assertEqual(self.rows[139]['net_exam_quota'],12)  # Campus 4 + base 8 are not recommendations.

    def test_directions_and_campuses_not_pooled(self):
        self.assertAlmostEqual(self.rows[7]['sample_dynamic_ratio'],174/81)
        self.assertAlmostEqual(self.rows[9]['sample_dynamic_ratio'],155/88)
        self.assertAlmostEqual(self.rows[31]['sample_dynamic_ratio'],82/40)
        self.assertEqual(self.rows[23]['school'],'华北电力大学')
        self.assertEqual(self.rows[108]['school'],'华北电力大学')
        self.assertNotEqual(self.rows[23]['unit'],self.rows[108]['unit'])

    def test_fallback_and_reference_plans_remain_visible(self):
        for row in self.rows.values():
            self.assertEqual(row['fallback_2026'],row['quota_year']==2026)
            if row['quota_year']==2026:self.assertEqual(row['status'],'2026回退')
        self.assertEqual(self.rows[77]['net_exam_quota'],17)
        self.assertEqual(self.rows[77]['denominator_evidence'],'目录预计统考列')
        self.assertEqual(self.rows[60]['net_exam_quota'],17)  # Adjusted SDU plan, not initial 15.
        self.assertEqual(self.rows[158]['net_exam_quota'],2)  # Not initial 1.

    def test_missing_zero_and_invalid_denominators(self):
        for quota in [None,0]:self.assertIsNone(pipeline.ratio(20,quota))
        self.assertEqual(pipeline.ratio(0,10),0)
        with self.assertRaises(ValueError):pipeline.ratio(-1,10)
        with self.assertRaises(ValueError):pipeline.net_quota(dict(quota_id='bad',quota_basis='post_recommendation_notice',stated_exam_quota=-1))

    def test_complete_hash_and_public_url_provenance(self):
        for row in self.rows.values():
            self.assertRegex(row['screenshot_sha256'],r'^[0-9a-f]{64}$')
        for q in self.quotas.values():
            self.assertTrue(q['source_urls'],q['quota_id'])
            self.assertTrue(q['source_sha256'],q['quota_id'])
            self.assertTrue(all(u.startswith('https://') for u in q['source_urls']))
            self.assertTrue(all(len(h)==64 for h in q['source_sha256']))

    def test_ambiguous_join_is_rejected(self):
        original=list(self.quotas.values())
        with patch.object(pipeline,'load_quotas',return_value=[*original,original[0]]):
            with self.assertRaisesRegex(ValueError,'Ambiguous same-year'):pipeline.build(write=False)

    def test_not_expanded_or_used_as_admission_probability(self):
        summary=self.data['summary']
        self.assertIsNone(summary['actual_application_expansion_factor'])
        self.assertFalse(summary['common_underreporting_assumption_verified'])
        self.assertFalse(summary['forecast_model_changed'])
        self.assertFalse(summary['contains_individual_candidate_data'])
        duplicate=summary['duplicate_raw_unit_labels']
        self.assertEqual(duplicate,[dict(school='东北财经大学',unit='统计学院',ranks=[6,89])])


if __name__=='__main__':unittest.main()
