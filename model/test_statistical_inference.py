"""Check interval probability, sufficient likelihood and chronological isolation."""
import unittest
import numpy as np
import pandas as pd
from experiment_statistical_inference import quantile_interval, covariance_reml, fit_state, calibrate_observations, historical_features, evaluate

class StatisticalInferenceTests(unittest.TestCase):
    def test_small_quantile_sample_needs_support_bound(self):
        result=quantile_interval(np.arange(10)+350)
        self.assertTrue(result['lower_support_bound'])
        self.assertGreaterEqual(result['binomial_coverage_continuous_model'],.95)

    def test_sufficient_nested_likelihood_equals_full_data(self):
        groups=[np.array([2.,4.,5.]),np.array([6.,8.]),np.array([3.,9.,10.])]
        sizes=np.array([len(g) for g in groups]); means=np.array([g.mean() for g in groups])
        ids=np.repeat(np.arange(3),sizes); schools=np.array([0,0,1])
        a,u,e=3.,2.,4.
        v=a*(schools[:,None]==schools[None,:])+np.diag(u+e/sizes)
        small=covariance_reml(means,np.ones((3,1)),v)[0]
        within=sum(np.sum((g-g.mean())**2) for g in groups)
        sufficient=small+(sum(sizes)-3)*np.log(e)+within/e+np.log(sizes).sum()
        s=schools[ids]; fullv=a*(s[:,None]==s[None,:])+u*(ids[:,None]==ids[None,:])+e*np.eye(len(ids))
        full=covariance_reml(np.concatenate(groups),np.ones((len(ids),1)),fullv)[0]
        self.assertAlmostEqual(sufficient,full,places=8)

    def test_origin_observations_ignore_future_changes(self):
        p=pd.DataFrame({'school':['a','a'],'year':[2023,2025],'national_line':[340,323],
            'q10_value':[365.,420.],'q10_method':['minimum_only']*2,'target_weight':[1.,1.]})
        exact=pd.DataFrame({'school':['a','a'],'year':[2023,2025],'score_q10':[369.,423.],
            'q10_bootstrap_sd':[3.,2.]})
        first,_=calibrate_observations(p,exact,2024)
        exact.loc[exact.year==2025,'score_q10']=-10000
        p.loc[p.year==2025,'q10_value']=10000
        second,_=calibrate_observations(p,exact,2024)
        pd.testing.assert_frame_equal(first,second)

    def test_state_predictive_variance_is_nonnegative(self):
        frame=pd.DataFrame({'school':['a','a','b','b'],'year':[2022,2023,2022,2023],
            'margin':[20.,25.,40.,35.],'observation_variance':[9.]*4})
        for kind in ('random_intercept','local_level'):
            model=fit_state(frame,kind)
            center,variance=model.predict('a',2024)
            self.assertTrue(np.isfinite(center)); self.assertGreater(variance,0.)

    def test_regression_features_ignore_current_and_future_labels(self):
        frame=pd.DataFrame({'school':['a']*3,'year':[2022,2024,2025],'margin':[20.,100.,200.]})
        first=historical_features(frame,'a',2024)
        frame.loc[frame.year>=2024,'margin']=-10000
        self.assertEqual(first,historical_features(frame,'a',2024))

    def test_standard_wis_normalization(self):
        frame=pd.DataFrame({'actual':[10.],'year':[2024],
            **{f'pred_q{q:02d}':[10.] for q in (5,10,20,50,80,90,95)}})
        self.assertEqual(evaluate(frame)['wis'],0.)
        frame['actual']=12.
        # All intervals are degenerate at 10: each weighted miss = 2.
        self.assertAlmostEqual(evaluate(frame)['wis'],(1.+2.+2.+2.)/3.5)

if __name__=='__main__': unittest.main()
