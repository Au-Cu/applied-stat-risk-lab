"""Visual diagnostics of fitted V6 models, never decorative illustrations.

Reads only de-identified school-year aggregates; the training program owns
the substantive computations. Also exports the same metrics for the website.
"""
from pathlib import Path
import json
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
EXP=ROOT/'output/experiments/v6_statistical_inference_20261011'
OUT=ROOT/'paper/assets/v6'
LABELS={'frozen_baseline':'冻结基线','v5_exact_enhanced':'精确标签增强',
    'random_intercept':'观测误差随机截距','local_level':'局部水平随机过程',
    'local_level_equal_precision':'等精度局部水平'}
COLORS=['#708090','#2f6f9f','#2a9d8f','#d95d39','#b18a32']


def save(fig,name):
    svg=OUT/(name+'.svg')
    fig.savefig(svg,bbox_inches='tight',metadata={'Date':'2026-10-11'})
    # Matplotlib emits trailing blanks in multiline path attributes. Removing
    # only those blanks preserves SVG geometry and keeps generated diffs clean.
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    fig.savefig(OUT/(name+'.png'),bbox_inches='tight',dpi=180)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'axes.unicode_minus':False,'svg.fonttype':'none','svg.hashsalt':'statistical-inference-v6',
        'axes.spines.top':False,'axes.spines.right':False,'font.size':13,
        'axes.labelsize':13,'axes.titlesize':13,'xtick.labelsize':12,'ytick.labelsize':12,
        'figure.facecolor':'white','axes.labelcolor':'#183153','text.color':'#183153'})
    s=json.loads((EXP/'summary.json').read_text(encoding='utf-8'))
    q=pd.read_csv(EXP/'quantile_inference.csv')
    fig,ax=plt.subplots(1,2,figsize=(11.4,4.0),layout='constrained')
    flagged=q.population_ci95_lower_support_bound.astype(bool)
    for flag,color,label in ((False,'#2a9d8f','上下端均为观测顺序统计量'),(True,'#d95d39','下端只能取理论支持界 0')):
        g=q[flagged==flag]
        ax[0].scatter(g.n,g.population_ci95_upper-g.population_ci95_lower,c=color,label=label,s=28,alpha=.8)
    ax[0].set(xlabel='校年名单人数 n',ylabel='总体 Q10 的 95% 区间宽度 / 分',title='小名单难以识别总体低尾')
    ax[0].legend(fontsize=11,loc='upper right')
    ax[1].scatter(q.n,q.q10_definition_range,color='#2f6f9f',s=28,alpha=.8)
    ax[1].set(xlabel='校年名单人数 n',ylabel='三种 Q10 定义的最大差 / 分',title='插值定义的敏感性不是预测误差')
    for a in ax: a.grid(axis='y',alpha=.18);a.set_axisbelow(True)
    save(fig,'01_quantile_identification')

    profile=pd.read_csv(EXP/'reml_profiles.csv')
    reml=s['nested_reml_calendar_adjusted']
    fig,axs=plt.subplots(1,3,figsize=(11.4,3.3),layout='constrained')
    for a,(key,title),color in zip(axs,(('between_school','院校间'),('school_year','校年状态'),('within_school_year','校年内个体')),COLORS[1:4]):
        g=profile[profile.component==key].sort_values('variance')
        a.plot(g.variance,g.deviance,color=color,lw=2)
        a.axhline(3.841459,color='#708090',ls='--',lw=1)
        estimate=reml['variances'][key];bounds=reml['profile95_intervals'][key]
        a.axvline(estimate,color=color,alpha=.45)
        a.axvspan(bounds['lower'],bounds['upper'],color=color,alpha=.12)
        a.set(xlim=(max(1.,bounds['lower']*.45),bounds['upper']*1.5),ylim=(0,8),
            xlabel='方差 / 分²',ylabel='剖面偏差 2Δℓ' if a==axs[0] else '',title=f"{title}：{estimate:.1f}")
        a.text(.04,.93,f"近似 95% 区间\n[{bounds['lower']:.1f}, {bounds['upper']:.1f}]",transform=a.transAxes,va='top',fontsize=11)
    save(fig,'02_reml_profiles')

    metrics=s['rolling_metrics'];keys=['frozen_baseline','v5_exact_enhanced','random_intercept']
    fig,ax=plt.subplots(1,2,figsize=(11.4,4.2),layout='constrained')
    for i,key in enumerate(keys):
        m=metrics[key]
        ax[0].scatter(m['q90_mean_width'],m['wis'],s=85,color=COLORS[i])
        offset=(4,7) if i!=3 else (4,-17)
        ax[0].annotate(LABELS[key],(m['q90_mean_width'],m['wis']),xytext=offset,textcoords='offset points',fontsize=11)
        ax[1].plot([.8,.9,.95],[m[f'q{int(p*100)}_coverage'] for p in (.8,.9,.95)],marker='o',color=COLORS[i],lw=1.4,label=LABELS[key])
    ax[0].set(xlabel='平均 P90−P50 / 分（不是双侧区间宽度）',ylabel='标准 WIS（越小越好）',title='锐度与概率评分同时比较',xlim=(21,35))
    ax[1].plot([.78,.98],[.78,.98],ls='--',color='#9aa9b9',label='理想覆盖')
    ax[1].set(xlabel='名义上分位',ylabel='54 校年实际覆盖率',title='总体覆盖不代表每年覆盖',xlim=(.78,.98),ylim=(.65,1.01))
    ax[1].legend(fontsize=10,loc='lower right')
    for a in ax:a.grid(alpha=.18);a.set_axisbelow(True)
    save(fig,'03_distribution_tradeoff')

    pc=pd.read_csv(EXP/'shape_pca_scores.csv');load=pd.read_csv(EXP/'shape_pca_loadings.csv')
    shape=s['multivariate_shape_pca']
    fig,ax=plt.subplots(1,3,figsize=(12,3.7),layout='constrained')
    ax[0].plot(load['quantile'],load.pc1,marker='o',color=COLORS[1],label='PC1')
    ax[0].plot(load['quantile'],load.pc2,marker='s',color=COLORS[2],label='PC2')
    ax[0].axhline(0,color='#c4cdd6',lw=.7)
    ax[0].set(xlabel='原分位点 / %',ylabel='载荷',title='相对 Q10 形状的压缩方向');ax[0].legend(fontsize=11)
    scatter=ax[1].scatter(pc.pc1,pc.pc2,c=pc.score_iqr,cmap='viridis',s=18+np.minimum(pc.candidate_n,80)*.7,alpha=.8)
    ax[1].set(xlabel='PC1 得分',ylabel='PC2 得分',title='77 校年：点大小表示人数')
    fig.colorbar(scatter,ax=ax[1],label='校年内 IQR / 分',shrink=.75)
    names={'pooled':'全国池化','lag_full':'同校滞后','lag_pca1':'1 个 PC','lag_pca2':'2 个 PC','lag_factor1':'1 个因子','lag_cluster3':'3 类聚类'}
    items=[(names[k],v) for k,v in shape['rolling_shape_mae'].items()]
    ax[2].barh([a for a,b in items],[b for a,b in items],color=['#708090' if a=='全国池化' else '#2a9d8f' for a,b in items])
    ax[2].set(xlim=(0,8.2),xlabel='54 校年形状 MAE / 分',title='高解释率不保证预测增益')
    for i,(name,val) in enumerate(items):ax[2].text(val+.05,i,f'{val:.2f}',va='center',fontsize=11)
    save(fig,'04_multivariate_shape')

    infer=s['paired_small_year_inference'];years=list(infer['year_mean_differences']);vals=list(infer['year_mean_differences'].values())
    fig,ax=plt.subplots(1,2,figsize=(11.4,3.4),layout='constrained')
    ax[0].bar(years,vals,color=['#2a9d8f' if v<0 else '#d95d39' for v in vals])
    ax[0].axhline(0,color='#708090',lw=1)
    ax[0].set(xlabel='外层日历年',ylabel='精确增强−冻结基线的 MAE / 分',title='三个年份并非全部改善')
    previous=json.loads((ROOT/'output/experiments/v5_exact_labels_20261009/exact_evaluation/summary.json').read_text(encoding='utf-8'))
    block=next(v for v in previous.values() if isinstance(v,dict) and 'p05' in v and 'estimate' in v)
    intervals=[('年份重抽 Bootstrap（90%）',[block['p05'],block['p95']]),('年份 t（90%，df=2）',infer['t90_interval_df2'])]
    for i,(name,bounds) in enumerate(intervals):
        ax[1].plot(bounds,[i,i],lw=4,color=COLORS[i+1]);ax[1].scatter(infer['year_equal_difference'],i,color=COLORS[i+1],s=35)
    ax[1].axvline(0,color='#708090',ls='--');ax[1].set_yticks([0,1],[a for a,b in intervals],fontsize=11)
    ax[1].set(xlabel='年份等权 MAE 差 / 分',title='对少数年份的推断高度依赖假设')
    ax[1].text(.04,.94,f"年份符号翻转：双侧 p = {infer['exact_year_signflip_two_sided_p']:.2f}",transform=ax[1].transAxes,va='top',fontsize=11)
    save(fig,'05_small_year_inference')

    reg=s['regression_challengers'];yearly=pd.read_csv(EXP/'yearly_metrics.csv')
    fig,ax=plt.subplots(figsize=(8.4,3.6),layout='constrained')
    for key,label,color in (('random_intercept','观测误差随机截距','#2a9d8f'),('local_level','局部水平','#708090')):
        g=yearly[yearly.kind==key].sort_values('year');ax.plot(g.year,g.mae,marker='o',color=color,label=label)
    for key,label,color in (('ridge','岭回归','#2a9d8f'),('neural_4','4 隐节点神经网络','#d95d39')):
        m=reg['metrics'][key];ax.plot([2024,2025,2026],[m['mae_by_year'][str(y)] for y in (2024,2025,2026)],marker='s',ls='--',color=color,label=label)
    ax.set(xticks=[2024,2025,2026],xlabel='外层测试年份',ylabel='精确 Q10 MAE / 分',title='统计与机器学习中心候选：逐年而非只看均值')
    ax.legend(fontsize=11,ncol=2);ax.grid(axis='y',alpha=.18)
    save(fig,'06_regression_challengers')

    fig,ax=plt.subplots(1,2,figsize=(11.4,3.6),layout='constrained')
    for group,color in zip(shape['descriptive_cluster_profiles'],COLORS[1:4]):
        profile=np.array(group['relative_quantile_centroid'])
        ax[0].plot([5,10,25,50,75,90,95],np.r_[profile[0],0.,profile[1:]],marker='o',lw=2,color=color,
            label=f"形状类 {group['cluster']}（{group['groups']} 校年）")
    ax[0].set(xlabel='已实现分布分位点 / %',ylabel='相对本校年 Q10 的偏移 / 分',title='聚类描述宽窄，不描述学校难度')
    ax[0].legend(fontsize=11);ax[0].axhline(0,color='#a8b3c2',lw=.7)
    fa=shape['descriptive_factor1'];loads=np.array(fa['loadings']);noise=np.array(fa['unique_variances'])
    ax[1].bar(np.arange(6),loads**2,label='共同因子方差',color='#2a9d8f')
    ax[1].bar(np.arange(6),noise,bottom=loads**2,label='独特方差',color='#708090')
    ax[1].set(xticks=np.arange(6),xticklabels=['Q05','Q25','Q50','Q75','Q90','Q95'],ylabel='形状坐标方差 / 分²',title='单因子也保留各分位的独特差异')
    ax[1].legend(fontsize=11)
    save(fig,'07_shape_typology_and_factor')

    payload={k:s[k] for k in ('version','created_on','scope','quantile_diagnostics','nested_reml_calendar_adjusted',
        'multivariate_shape_pca','regression_challengers','rolling_metrics','paired_small_year_inference','promotion','limitations')}
    payload['yearly_metrics']=yearly.to_dict('records')
    payload['pca_loadings']=load[['quantile','pc1','pc2']].to_dict('records')
    (ROOT/'app/data/model-v6-statistics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'figures':7,'website_metrics':True,'source':str(EXP)},ensure_ascii=False))


if __name__=='__main__':main()
