"""Statistical inference on audited rosters; public outputs are group aggregates.

Finite realised roster quantiles, hypothetical population quantiles and future
forecast distributions are distinct estimands. This script never edits the
frozen forecast. REML and all proxy calibration are fitted within each origin.
"""
from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize, brentq
from scipy.stats import binom, chi2, norm, spearmanr, t as student_t
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.cluster import KMeans
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
import warnings

from candidate_score_layer import candidate_distribution_by_program, load_candidate_scores
from experiment_candidate_distribution import exact_candidate_rows

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/experiments/v6_statistical_inference_20261011'
SEED = 20261011
PROBS = (.05, .10, .20, .50, .80, .90, .95)
KINDS = ('random_intercept', 'local_level', 'local_level_equal_precision')


def quantile_interval(scores, probability=.10, confidence=.95):
    """Equal-tail binomial inversion, conditional on an iid population model.

    Atoms/ties yield conservative order-statistic bounds. 0/500 are score
    support bounds, not observed order statistics; expose when they are needed.
    """
    y = np.sort(np.asarray(scores, float))
    n = len(y)
    alpha = 1 - confidence
    lower_rank = int(binom.ppf(alpha / 2, n, probability))
    upper_rank = int(binom.ppf(1 - alpha / 2, n, probability)) + 1
    return {
        'lower': float(y[lower_rank - 1]) if lower_rank >= 1 else 0.,
        'upper': float(y[upper_rank - 1]) if upper_rank <= n else 500.,
        'lower_rank': lower_rank, 'upper_rank': upper_rank,
        'lower_support_bound': lower_rank < 1,
        'upper_support_bound': upper_rank > n,
        'binomial_coverage_continuous_model': float(
            binom.cdf(upper_rank - 1, n, probability)
            - binom.cdf(lower_rank - 1, n, probability)),
    }


def quantile_diagnostics(candidates):
    rows = []
    for (school, year), g in candidates.groupby(['school', 'year']):
        y = g.initial_score.to_numpy(float)
        row = {'school': school, 'year': int(year), 'n': len(y)}
        for p in (.05, .10, .15, .20):
            row[f'q{int(p*100):02d}'] = float(np.quantile(y, p, method='linear'))
        for method in ('inverted_cdf', 'linear', 'median_unbiased'):
            row[f'q10_{method}'] = float(np.quantile(y, .10, method=method))
        ci = quantile_interval(y)
        row.update({f'population_ci95_{k}': v for k, v in ci.items()})
        row['q10_definition_range'] = max(row[f'q10_{m}'] for m in
            ('inverted_cdf', 'linear', 'median_unbiased')) - min(row[f'q10_{m}'] for m in
            ('inverted_cdf', 'linear', 'median_unbiased'))
        rows.append(row)
    return pd.DataFrame(rows)


def covariance_reml(values, design, covariance):
    factor = cho_factor(covariance, lower=True, check_finite=False)
    vi_x = cho_solve(factor, design, check_finite=False)
    vi_y = cho_solve(factor, values, check_finite=False)
    info = design.T @ vi_x
    beta = np.linalg.solve(info, design.T @ vi_y)
    resid = values - design @ beta
    vi_resid = cho_solve(factor, resid, check_finite=False)
    objective = (2 * np.log(np.diag(factor[0])).sum()
                 + np.linalg.slogdet(info)[1] + resid @ vi_resid)
    return float(objective), beta, np.linalg.inv(info), factor


def fit_nested_reml(groups, year_fixed=True, profile=False):
    """Exact sufficient-statistic likelihood for the candidate nested model.

    The within-group sum of squares retains all candidate-level information;
    group means have variance sigma_within^2/n. No candidate rows are exported.
    """
    n = groups.candidate_n.to_numpy(float)
    y = groups.score_mean.to_numpy(float)
    schools = groups.school.to_numpy()
    school_kernel = (schools[:, None] == schools[None, :]).astype(float)
    x = pd.get_dummies(groups.year.astype(str), dtype=float).to_numpy() if year_fixed else np.ones((len(y), 1))
    within_ss = float(np.sum((n - 1) * groups.score_sd.to_numpy(float)**2))
    within_df = int(np.sum(n - 1))

    def objective(log_variances):
        between, cohort, within = np.exp(log_variances)
        v = between * school_kernel + np.diag(cohort + within / n)
        base = covariance_reml(y, x, v)[0]
        return .5 * (base + within_df*np.log(within) + within_ss/within)

    start = np.log([150., 80., max(within_ss/within_df, 1.)])
    result = minimize(objective, start, method='L-BFGS-B', bounds=[(-10., 10.)]*3)
    variances = np.exp(result.x)
    v = variances[0]*school_kernel + np.diag(variances[1]+variances[2]/n)
    _, beta, beta_cov, _ = covariance_reml(y, x, v)
    names = ('between_school', 'school_year', 'within_school_year')
    output = {
        'year_fixed': year_fixed, 'converged': bool(result.success),
        'variances': dict(zip(names, map(float, variances))),
        'variance_shares': dict(zip(names, map(float, variances/variances.sum()))),
        'same_school_different_year_icc': float(variances[0]/variances.sum()),
        'same_school_year_icc': float(sum(variances[:2])/variances.sum()),
        'fixed_effects': [float(z) for z in beta],
        'fixed_effects_se': [float(z) for z in np.sqrt(np.diag(beta_cov))],
        'n_candidates': int(n.sum()), 'n_groups': len(groups),
        'n_schools': int(groups.school.nunique()), 'within_df': within_df,
        'negative_restricted_loglik_up_to_constants': float(result.fun),
        'interpretation': 'Gaussian working REML; candidate likelihood weighting, conditional on observed audited schools',
    }
    profiles = []
    if profile:
        for index, name in enumerate(names):
            grid = np.unique(np.r_[np.linspace(max(-10.,result.x[index]-3), min(10.,result.x[index]+3), 23), result.x[index]])
            for fixed in grid:
                free = [j for j in range(3) if j != index]
                def conditional(z):
                    full = result.x.copy(); full[index] = fixed; full[free] = z
                    return objective(full)
                opt = minimize(conditional, result.x[free], method='L-BFGS-B', bounds=[(-10.,10.)]*2)
                profiles.append({'component': name, 'variance': float(np.exp(fixed)),
                    'deviance': float(max(2*(opt.fun-result.fun),0)), 'converged': bool(opt.success)})
        pf = pd.DataFrame(profiles)
        output['profile95_intervals'] = {}
        for name, g in pf.groupby('component'):
            index = names.index(name)
            free = [j for j in range(3) if j != index]
            def profile_root(fixed):
                def conditional(z):
                    full = result.x.copy(); full[index] = fixed; full[free] = z
                    return objective(full)
                opt = minimize(conditional, result.x[free], method='L-BFGS-B', bounds=[(-10.,10.)]*2)
                return 2*(opt.fun-result.fun)-chi2.ppf(.95,1)
            low = brentq(profile_root, -10., result.x[index]) if profile_root(-10.) > 0 else -10.
            high = brentq(profile_root, result.x[index], 10.) if profile_root(10.) > 0 else 10.
            output['profile95_intervals'][name] = {
                'lower': float(np.exp(low)), 'upper': float(np.exp(high)),
                'approximate': True, 'note': 'profile likelihood with chi-square cutoff; Gaussian working model and boundary limitations apply'}
    return output, pd.DataFrame(profiles)


def calibrate_observations(periods, distributions, origin):
    """Exact labels take priority. Paired proxies are used only to calibrate.

    Bias and variance estimates cannot access origin or later labels. The
    sampling term describes a hypothetical repeated cohort, not a census error.
    """
    prior = periods[periods.year < origin].copy()
    exact = distributions[distributions.year < origin].copy()
    pairs = prior.merge(exact[['school','year','score_q10','q10_bootstrap_sd']], on=['school','year'])
    pairs['delta'] = pairs.score_q10 - pairs.q10_value
    params = {}
    default_sampling = float(np.median(exact.q10_bootstrap_sd**2)) if len(exact) else 25.
    for method in prior.q10_method.unique():
        g = pairs[(pairs.q10_method == method) & pairs.delta.notna()]
        usable = len(g) >= 5 and g.school.nunique() >= 3
        params[method] = {
            'bias': float(g.delta.mean()) if usable else 0.,
            'discrepancy_variance': float(g.delta.var(ddof=1)) if usable else 100.,
            'pairs': len(g), 'schools': int(g.school.nunique()), 'calibrated': usable}
    exact_map = exact.set_index(['school','year']).to_dict('index')
    rows=[]
    for _, r in prior.iterrows():
        item = exact_map.get((r.school,int(r.year)))
        if item is not None:
            value = item['score_q10']; variance = max(item['q10_bootstrap_sd']**2, .25)
            tier = 'exact'; method='exact'
        elif pd.notna(r.q10_value) and r.target_weight >= .12:
            par=params[r.q10_method]
            value = float(r.q10_value)+par['bias']
            variance = default_sampling+par['discrepancy_variance']
            tier='proxy'; method=r.q10_method
        else:
            continue
        rows.append({'school':r.school,'year':int(r.year),'margin':value-float(r.national_line),
            'observation_variance':variance,'tier':tier,'method':method})
    return pd.DataFrame(rows), {'origin':origin,'methods':params,'default_sampling_variance':default_sampling,
        'max_training_year': int(prior.year.max()), 'exact_training_groups': len(exact)}


@dataclass
class StateModel:
    kind: str
    intercept: float
    intercept_variance: float
    school_variance: float
    innovation_variance: float
    observations: pd.DataFrame
    min_year: int
    converged: bool

    def predict(self, school, year):
        g=self.observations[self.observations.school==school]
        tstar=year-self.min_year
        if g.empty:
            variance=self.school_variance+self.innovation_variance*(tstar if 'local_level' in self.kind else 1.)
            return self.intercept, variance+self.intercept_variance
        age=g.year.to_numpy(float)-self.min_year
        kernel=np.minimum.outer(age,age) if 'local_level' in self.kind else np.eye(len(g))
        v=self.school_variance*np.ones((len(g),len(g)))+self.innovation_variance*kernel+np.diag(g.observation_variance)
        cross=np.full(len(g),self.school_variance)
        priorvar=self.school_variance+self.innovation_variance
        if 'local_level' in self.kind:
            cross+=self.innovation_variance*np.minimum(age,tstar)
            priorvar=self.school_variance+self.innovation_variance*tstar
        factor=cho_factor(v,lower=True,check_finite=False)
        a=cho_solve(factor,cross,check_finite=False)
        center=self.intercept+a@(g.margin.to_numpy(float)-self.intercept)
        variance=priorvar-cross@a+(1-a.sum())**2*self.intercept_variance
        return float(center),float(max(variance,.01))


def fit_state(observations, kind):
    frame=observations.copy()
    if kind=='local_level_equal_precision':
        frame['observation_variance']=float(np.median(frame.observation_variance))
    minimum=int(frame.year.min())
    blocks=[g for _,g in frame.groupby('school')]
    def objective(logvars, details=False):
        schoolvar,innovation=np.exp(logvars)
        logdet=0.; info=0.; score=0.; quad=0.
        for g in blocks:
            age=g.year.to_numpy(float)-minimum
            kernel=np.minimum.outer(age,age) if 'local_level' in kind else np.eye(len(g))
            v=schoolvar*np.ones((len(g),len(g)))+innovation*kernel+np.diag(g.observation_variance)
            f=cho_factor(v,lower=True,check_finite=False)
            one=np.ones(len(g)); y=g.margin.to_numpy(float)
            vione=cho_solve(f,one,check_finite=False); viy=cho_solve(f,y,check_finite=False)
            logdet+=2*np.log(np.diag(f[0])).sum(); info+=one@vione; score+=one@viy; quad+=y@viy
        loss=.5*(logdet+np.log(info)+quad-score**2/info)
        return (score/info,1/info) if details else float(loss)
    result=minimize(objective,np.log([200.,100.]),method='L-BFGS-B',bounds=[(-8.,11.)]*2)
    mu,muvar=objective(result.x,details=True)
    schoolvar,innovation=np.exp(result.x)
    return StateModel(kind,float(mu),float(muvar),float(schoolvar),float(innovation),frame,minimum,bool(result.success))


def national_prediction(payload, origin, zone):
    vals={int(k):v['A'] for k,v in payload['values'].items()}
    def point(t):
        prior=np.array([vals[k] for k in sorted(vals) if k<t],float)
        return float(prior[-1] if len(prior)<3 else .55*prior[-1]+.45*prior[-5:].mean())
    years=[k for k in sorted(vals) if k<origin]
    residuals=[vals[k]-point(k) for k in years[3:]]
    sd=max(float(np.std(residuals,ddof=1)) if len(residuals)>1 else 7.,7.)
    return point(origin)-(10. if zone=='B' else 0.),sd**2


def evaluate(frame, prefix='pred'):
    y=frame.actual.to_numpy(float); m=frame[f'{prefix}_q50'].to_numpy(float)
    total=.5*np.abs(y-m)
    for lo,hi in ((5,95),(10,90),(20,80)):
        lower=frame[f'{prefix}_q{lo:02d}'].to_numpy(float); upper=frame[f'{prefix}_q{hi:02d}'].to_numpy(float)
        alpha=2*lo/100
        score=upper-lower+2/alpha*np.maximum(lower-y,0)+2/alpha*np.maximum(y-upper,0)
        total+=alpha/2*score
    out={'n':len(frame),'mae':float(np.abs(y-m).mean()),'rmse':float(np.sqrt(np.mean((y-m)**2))),
         'bias_actual_minus_prediction':float(np.mean(y-m)),'wis':float(np.mean(total/3.5))}
    for q in (80,90,95):
        upper=frame[f'{prefix}_q{q}'].to_numpy(float)
        out[f'q{q}_coverage']=float(np.mean(y<=upper)); out[f'q{q}_mean_width']=float(np.mean(upper-m))
    out['year_equal_mae']=float(frame.assign(ae=np.abs(y-m)).groupby('year').ae.mean().mean())
    return out


def small_year_inference(paired):
    g=paired.copy()
    g['difference']=np.abs(g.enhanced_error)-np.abs(g.baseline_error)
    means=g.groupby('year').difference.mean(); n=len(means)
    est=float(means.mean()); se=float(means.std(ddof=1)/np.sqrt(n))
    signs=np.array(list(itertools.product((-1.,1.),repeat=n)))
    flips=signs@means.to_numpy(float)/n
    p=float(np.mean(np.abs(flips)>=abs(est)-1e-12))
    return {'n_calendar_years':n,'year_mean_differences':{str(k):float(v) for k,v in means.items()},
        'year_equal_difference':est,'t90_interval_df2':[est-student_t.ppf(.95,n-1)*se,est+student_t.ppf(.95,n-1)*se],
        'exact_year_signflip_two_sided_p':p,
        'note':'t interval requires iid Gaussian year effects; sign flips require independent symmetric year effects; neither repairs selection or justifies universal superiority'}


def historical_features(observations, school, year):
    """No contemporary or future target participates in a feature."""
    history=observations[observations.year<year]
    local=history[history.school==school].sort_values('year')
    fallback=float(history.margin.median()) if len(history) else 30.
    values=local.margin.to_numpy(float)
    last=values[-1] if len(values) else fallback
    med=float(np.median(values)) if len(values) else fallback
    trend=values[-1]-values[-2] if len(values)>1 else 0.
    scale=float(np.std(values,ddof=1)) if len(values)>1 else 0.
    age=year-int(local.year.max()) if len(local) else 5.
    return [last,med,trend,scale,float(len(values)),age,float(year-2022)]


def regression_candidates(periods,distributions,national):
    """Small ridge / neural candidates; centers only, not calibrated CDFs.

    The neural architecture is fixed before this run (4 hidden units, strong
    alpha=10 shrinkage). Ridge alpha uses the latest *prior* training year.
    These remain retrospectively specified comparisons, not blind tests.
    """
    predictions=[]; fit_info=[]
    tests=distributions.merge(periods[['school','year','national_zone']],on=['school','year'])
    for origin in (2024,2025,2026):
        obs,_=calibrate_observations(periods,distributions,origin)
        training=obs[obs.year>obs.year.min()].copy()
        x=np.array([historical_features(obs,r.school,int(r.year)) for r in training.itertuples()])
        y=training.margin.to_numpy(float)
        weights=1/np.maximum(training.observation_variance.to_numpy(float),1.)
        weights/=weights.mean()
        alpha=10.; validation_year=None
        latest=int(training.year.max())
        # The INNER observation-bias calibration must also be refitted. Merely
        # splitting outer-origin features would leak validation-year pairs.
        inner_obs,_=calibrate_observations(periods,distributions,latest)
        inner=inner_obs[inner_obs.year>inner_obs.year.min()]
        validation=distributions[distributions.year==latest].merge(periods[['school','year','national_line']],on=['school','year'])
        if len(inner)>=20 and len(validation)>=10:
            ix=np.array([historical_features(inner_obs,r.school,int(r.year)) for r in inner.itertuples()])
            iy=inner.margin.to_numpy(float);iw=1/np.maximum(inner.observation_variance.to_numpy(float),1.);iw/=iw.mean()
            vx=np.array([historical_features(inner_obs,r.school,latest) for r in validation.itertuples()])
            vy=validation.score_q10.to_numpy(float)-validation.national_line.to_numpy(float)
            sc=StandardScaler().fit(ix)
            errors={a:float(np.abs(Ridge(alpha=a).fit(sc.transform(ix),iy,sample_weight=iw).predict(sc.transform(vx))-vy).mean()) for a in (1.,10.,100.)}
            alpha=min(errors,key=errors.get); validation_year=latest
        scaler=StandardScaler().fit(x); tx=scaler.transform(x)
        ridge=Ridge(alpha=alpha).fit(tx,y,sample_weight=weights)
        target_mean=float(np.average(y,weights=weights)); target_sd=max(float(np.sqrt(np.average((y-target_mean)**2,weights=weights))),1.)
        neural=MLPRegressor(hidden_layer_sizes=(4,),activation='tanh',alpha=10.,solver='lbfgs',max_iter=1000,random_state=SEED,tol=1e-5)
        with warnings.catch_warnings(record=True) as notes:
            warnings.simplefilter('always',ConvergenceWarning)
            neural.fit(tx,(y-target_mean)/target_sd,sample_weight=weights)
        fit_info.append({'origin':origin,'training_groups':len(training),'ridge_alpha':alpha,
            'ridge_validation_year':validation_year,'neural_hidden_units':4,'neural_alpha':10.,
            'neural_iterations':int(neural.n_iter_),'neural_convergence_warning':any(issubclass(w.category,ConvergenceWarning) for w in notes),
            'latest_training_year':int(obs.year.max())})
        for r in tests[tests.year==origin].itertuples():
            features=scaler.transform([historical_features(obs,r.school,origin)])
            line,_=national_prediction(national,origin,r.national_zone)
            for kind,pred in (('ridge',ridge.predict(features)[0]),('neural_4',target_mean+target_sd*neural.predict(features)[0])):
                predictions.append({'school':r.school,'year':origin,'kind':kind,'actual':r.score_q10,
                    'pred_q50':float(line+pred),'latest_training_year':int(obs.year.max())})
    frame=pd.DataFrame(predictions)
    metrics={k:{'n':len(g),'mae':float(np.abs(g.actual-g.pred_q50).mean()),
        'year_equal_mae':float(g.assign(ae=np.abs(g.actual-g.pred_q50)).groupby('year').ae.mean().mean()),
        'mae_by_year':{str(y):float(np.abs(h.actual-h.pred_q50).mean()) for y,h in g.groupby('year')}} for k,g in frame.groupby('kind')}
    return {'metrics':metrics,'fits':fit_info,'status':'center-only retrospective challengers; not promoted to a calibrated predictive distribution'},frame


def multivariate_shape_analysis(distributions):
    """PCA of relative quantile curves; temporal tests refit the basis.

    Test Q10 is used to score shape error only, never as a prediction input.
    This study cannot establish threshold-forecast or admission gains.
    """
    quantiles=(5,25,50,75,90,95)
    def matrix(frame):
        return frame[[f'score_q{q:02d}' for q in quantiles]].to_numpy(float)-frame.score_q10.to_numpy(float)[:,None]
    full=matrix(distributions)
    pca=PCA(n_components=6).fit(full)
    descriptive_clusters=KMeans(n_clusters=3,random_state=SEED,n_init=20).fit(full)
    # Cluster labels are ordered by shape span, not school prestige or Q10.
    order=np.argsort(descriptive_clusters.cluster_centers_[:,-1]-descriptive_clusters.cluster_centers_[:,0])
    mapping={int(old):int(new+1) for new,old in enumerate(order)}
    cluster_labels=np.array([mapping[int(k)] for k in descriptive_clusters.labels_])
    fa=FactorAnalysis(n_components=1,random_state=SEED).fit(full)
    coordinates=pca.transform(full)
    scores=distributions[['school','year','candidate_n','score_iqr','bowley_skewness']].copy()
    scores['pc1']=coordinates[:,0]; scores['pc2']=coordinates[:,1]
    scores['descriptive_shape_cluster']=cluster_labels
    loadings=pd.DataFrame(pca.components_.T,columns=[f'pc{i+1}' for i in range(6)])
    loadings['quantile']=quantiles
    rows=[]
    for origin in (2024,2025,2026):
        train=distributions[distributions.year<origin]
        test=distributions[distributions.year==origin]
        tr=matrix(train); model=PCA(n_components=min(6,len(train))).fit(tr)
        factor=FactorAnalysis(n_components=1,random_state=SEED).fit(tr)
        clusters=KMeans(n_clusters=3,random_state=SEED,n_init=20).fit(tr)
        pooled=np.median(tr,axis=0)
        for _,r in test.iterrows():
            previous=train[train.school==r.school].sort_values('year')
            predicted={'pooled':pooled.copy()}
            if len(previous):
                latest=previous.iloc[-1]
                school_shape=matrix(previous.tail(1))[0]
                weight=min(float(latest.candidate_n)/(float(latest.candidate_n)+30),.75)*np.exp(-.35*(origin-int(latest.year)-1))
                predicted['lag_full']=(1-weight)*pooled+weight*school_shape
                for rank in (1,2):
                    z=model.transform(school_shape.reshape(1,-1)); z[:,rank:]=0
                    smooth=model.inverse_transform(z)[0]
                    predicted[f'lag_pca{rank}']=(1-weight)*pooled+weight*smooth
                latent=factor.transform(school_shape.reshape(1,-1))[0]
                predicted['lag_factor1']=(1-weight)*pooled+weight*(factor.mean_+latent@factor.components_)
                center=clusters.cluster_centers_[clusters.predict(school_shape.reshape(1,-1))[0]]
                predicted['lag_cluster3']=(1-weight)*pooled+weight*center
            else:
                for kind in ('lag_full','lag_pca1','lag_pca2','lag_factor1','lag_cluster3'): predicted[kind]=pooled.copy()
            truth=matrix(pd.DataFrame([r]))[0]
            for kind,offsets in predicted.items():
                # Quantile monotonicity with anchored Q10 is part of the fit.
                seq=np.r_[offsets[0],0.,offsets[1:]]
                seq=np.maximum.accumulate(seq); seq-=seq[1]
                offsets=np.r_[seq[0],seq[2:]]
                rows.append({'school':r.school,'year':origin,'kind':kind,
                    'shape_quantile_mae':float(np.abs(offsets-truth).mean()),
                    'latest_basis_training_year':int(train.year.max()),
                    'same_school_prior_available':bool(len(previous))})
    prediction=pd.DataFrame(rows)
    metrics={k:float(g.shape_quantile_mae.mean()) for k,g in prediction.groupby('kind')}
    yearly={k:{str(y):float(v) for y,v in g.groupby('year').shape_quantile_mae.mean().items()} for k,g in prediction.groupby('kind')}
    result={'explained_variance_ratio':pca.explained_variance_ratio_.tolist(),
        'pc1_iqr_spearman':float(spearmanr(scores.pc1,scores.score_iqr).statistic),
        'pc2_bowley_spearman':float(spearmanr(scores.pc2,scores.bowley_skewness).statistic),
        'rolling_shape_mae':metrics,'rolling_shape_mae_by_year':yearly,
        'selection_status':'descriptive and temporal candidate comparison; no full-sample PCA basis enters a forecast',
        'n_test_groups':int(prediction[prediction.kind=='pooled'].shape[0]),
        'target':'relative admitted quantile shape, separately from future Q10 threshold',
        'descriptive_cluster_profiles':[{'cluster':mapping[int(k)],
            'groups':int((descriptive_clusters.labels_==k).sum()),
            'distinct_schools':int(distributions.loc[descriptive_clusters.labels_==k,'school'].nunique()),
            'relative_quantile_centroid':descriptive_clusters.cluster_centers_[k].tolist(),
            'span_q95_q05':float(descriptive_clusters.cluster_centers_[k,-1]-descriptive_clusters.cluster_centers_[k,0])} for k in order],
        'descriptive_factor1':{'loadings':fa.components_[0].tolist(),'unique_variances':fa.noise_variance_.tolist(),
            'note':'Gaussian factor working model; sign arbitrary; exploratory full-sample description, not a new causal school classification'}}
    return result,scores,loadings,prediction


def rolling_experiment(periods, distributions, national):
    rows=[]; fits=[]; choices=[]
    test_frame=distributions.merge(periods[['school','year','national_zone']],on=['school','year'])
    paired=pd.read_csv(ROOT/'output/experiments/v5_exact_labels_20261009/exact_evaluation/paired_exact_backtest.csv')
    test_frame=test_frame.merge(paired[['school','year']],on=['school','year'])
    for origin in (2024,2025,2026):
        observations,calibration=calibrate_observations(periods,distributions,origin)
        earlier=distributions[distributions.year<origin]
        test=test_frame[test_frame.year==origin]
        for kind in KINDS:
            model=fit_state(observations,kind)
            fits.append({'origin':origin,'kind':kind,'n_training_groups':len(observations),
                'school_variance':model.school_variance,'innovation_variance':model.innovation_variance,
                'intercept':model.intercept,'converged':model.converged,'observation_calibration':calibration})
            for _,r in test.iterrows():
                margin,statevar=model.predict(r.school,origin)
                line,linevar=national_prediction(national,origin,r.national_zone)
                local=earlier[earlier.school==r.school].sort_values('year')
                cohortvar=float(local.iloc[-1].q10_bootstrap_sd**2) if len(local) else calibration['default_sampling_variance']
                variance=statevar+linevar+cohortvar
                row={'school':r.school,'year':origin,'kind':kind,'actual':float(r.score_q10),
                    'pred_sd':float(np.sqrt(variance)),'state_variance':statevar,'national_variance':linevar,
                    'future_cohort_variance':cohortvar,'latest_training_year':int(observations.year.max())}
                for p in PROBS: row[f'pred_q{int(p*100):02d}']=line+margin+norm.ppf(p)*np.sqrt(variance)
                rows.append(row)
        history=pd.DataFrame(rows); history=history[history.year<origin]
        # This candidate family is a newly specified retrospective comparison.
        # Two prior outer origins are required; only 2026 can be selected.
        selection='random_intercept'; reason='fewer than two prior evaluation years; fixed parsimonious default'
        if history.year.nunique()>=2:
            scores={k:evaluate(g) for k,g in history.groupby('kind')}
            best=min(KINDS,key=lambda k:(scores[k]['wis'],KINDS.index(k)))
            default=scores['random_intercept']
            worst=max(evaluate(history[(history.kind==best)&(history.year==y)])['mae']
                -evaluate(history[(history.kind=='random_intercept')&(history.year==y)])['mae'] for y in history.year.unique())
            if default['wis']-scores[best]['wis']>=.1 and worst<=2.:
                selection=best; reason='prior-year WIS improvement >=0.1; no prior-year MAE worsening >2'
            else: reason='prior-year predictive score or stability did not justify additional complexity'
        choices.append({'origin':origin,'selected':selection,'reason':reason,
            'selection_years':sorted(map(int,history.year.unique()))})
    result=pd.DataFrame(rows)
    selected=pd.concat([result[(result.year==c['origin'])&(result.kind==c['selected'])] for c in choices])
    selected['kind']='prequential_selected'
    result=pd.concat([result,selected],ignore_index=True)
    metrics={k:evaluate(g) for k,g in result.groupby('kind')}
    yearly=[{'kind':k,'year':int(y),**evaluate(g)} for (k,y),g in result.groupby(['kind','year'])]
    frozen=paired.rename(columns={'q10_exact':'actual'})
    metrics['frozen_baseline']=evaluate(frozen,'baseline')
    metrics['v5_exact_enhanced']=evaluate(frozen,'enhanced')
    return result,metrics,pd.DataFrame(yearly),fits,choices


def json_safe(value):
    if isinstance(value,dict): return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [json_safe(v) for v in value]
    if isinstance(value,np.generic): return value.item()
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=OUT)
    parser.add_argument('--aggregate-only',action='store_true',help='Reproduce from public sufficient statistics; no private roster is loaded')
    args=parser.parse_args(); args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.aggregate_only:
        distributions=pd.read_csv(ROOT/'output/experiments/v5_hierarchical_distribution_20261009/candidate_distribution_summary.csv')
        diagnostics=pd.read_csv(OUT/'quantile_inference.csv')
        candidate_count=int(distributions.candidate_n.sum())
    else:
        private=load_candidate_scores()
        if private.empty: raise SystemExit('Audited private roster input is required; use --aggregate-only for public replication, never synthetic substitution.')
        distributions=candidate_distribution_by_program(private)
        candidates=exact_candidate_rows(private).merge(distributions[['school','year']],on=['school','year'])
        diagnostics=quantile_diagnostics(candidates)
        candidate_count=len(candidates)
    diagnostics.to_csv(args.output_dir/'quantile_inference.csv',index=False,encoding='utf-8-sig')
    print(f'Quantile diagnostics: {len(diagnostics)} school-years',flush=True)
    reml,profiles=fit_nested_reml(distributions,year_fixed=True,profile=True)
    unadjusted,_=fit_nested_reml(distributions,year_fixed=False)
    profiles.to_csv(args.output_dir/'reml_profiles.csv',index=False,encoding='utf-8-sig')
    print('REML variance components fitted',flush=True)
    periods=pd.read_csv(ROOT/'data/processed/program_year.csv')
    national=json.loads((ROOT/'data/processed/national_lines.json').read_text(encoding='utf-8'))
    rolling,metrics,yearly,fits,choices=rolling_experiment(periods,distributions,national)
    rolling.to_csv(args.output_dir/'rolling_predictions.csv',index=False,encoding='utf-8-sig')
    yearly.to_csv(args.output_dir/'yearly_metrics.csv',index=False,encoding='utf-8-sig')
    paired=pd.read_csv(ROOT/'output/experiments/v5_exact_labels_20261009/exact_evaluation/paired_exact_backtest.csv')
    shape,pc_scores,pc_loadings,pc_predictions=multivariate_shape_analysis(distributions)
    pc_scores.to_csv(args.output_dir/'shape_pca_scores.csv',index=False,encoding='utf-8-sig')
    pc_loadings.to_csv(args.output_dir/'shape_pca_loadings.csv',index=False,encoding='utf-8-sig')
    pc_predictions.to_csv(args.output_dir/'shape_pca_rolling.csv',index=False,encoding='utf-8-sig')
    regression,reg_predictions=regression_candidates(periods,distributions,national)
    reg_predictions.to_csv(args.output_dir/'regression_rolling.csv',index=False,encoding='utf-8-sig')
    selected=metrics['prequential_selected']; v5=metrics['v5_exact_enhanced']
    # Pooled outer folds diagnose the new family; do not retune using them.
    promote=selected['mae']<=v5['mae']-.5 and selected['wis']<=v5['wis'] and selected['q90_coverage']>=.85
    output={
        'version':'V6 statistical inference','created_on':'2026-10-11','seed':SEED,
        'scope':{'candidates':candidate_count,'school_years':len(distributions),'schools':int(distributions.school.nunique())},
        'estimands':{'finite_roster':'fully observed realised cohort Q10 has no random-sampling error conditional on its roster',
            'population':'binomial CI and bootstrap use a hypothetical iid selected-population model',
            'forecast':'future realised cohort Q10; observation, state and common-year variability are distinct'},
        'quantile_diagnostics':{
            'support_bound_count':int(diagnostics.population_ci95_lower_support_bound.sum()),
            'definition_range_median':float(diagnostics.q10_definition_range.median()),
            'definition_range_max':float(diagnostics.q10_definition_range.max()),
            'rank_spearman_q05_q10':float(spearmanr(diagnostics.q05,diagnostics.q10).statistic),
            'rank_spearman_q10_q20':float(spearmanr(diagnostics.q10,diagnostics.q20).statistic)},
        'nested_reml_calendar_adjusted':reml,'nested_reml_unadjusted':unadjusted,
        'multivariate_shape_pca':shape,
        'regression_challengers':regression,
        'rolling_metrics':metrics,'origin_fits':fits,'prequential_selection':choices,
        'paired_small_year_inference':small_year_inference(paired),
        'promotion':{'promoted':bool(promote),'mae_requirement':v5['mae']-.5,
            'note':'retrospective statistical branch; frozen 2027 forecasts remain unchanged even if this diagnostic passes'},
        'limitations':['only three outer calendar years','Gaussian working likelihood; selected rosters and bounded discrete scores',
            'measurement variance is plug-in and proxy error may be correlated with bootstrap sampling',
            'variance parameters and proxy biases estimated by plug-in REML are not integrated out',
            'national and school-margin shocks may be dependent','retrospective source reconstruction is not an archived historical data vintage'],
    }
    (args.output_dir/'summary.json').write_text(json.dumps(json_safe(output),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'metrics':metrics,'promotion':output['promotion']},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__': main()
