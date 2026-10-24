import numpy as np, pandas as pd
from _diag.explore.harness import load_all
df = load_all()
df = df[df.season.isin(["2324","2425","2526","2627"])].dropna(subset=["mo_h","mc_h"]).copy()
print(sorted(t for t in set(df.home_team) if "Man" in t or "Utd" in t))
BIG = {"Man City","Man United","Liverpool","Arsenal","Chelsea","Tottenham","Bayern Munich",
       "Dortmund","Barcelona","Real Madrid","Ath Madrid"}
# 主队一方，按收盘主胜概率分桶，大球队 vs 其他同概率主队
df["big"] = df.home_team.isin(BIG) & ~df.away_team.isin(BIG)
df["hw"] = (df.actual==0).astype(float)
df["pb"] = pd.cut(df.mc_h,[0,.5,.6,.7,.8,1.0])
print("\n主场：同收盘概率区间，大球队 vs 其他")
res=[]
for b,g in df.groupby("pb",observed=True):
    for k,gg in g.groupby("big"):
        if len(gg)<20: continue
        a=gg.hw.mean(); res.append((b,k,len(gg),gg.mc_h.mean(),a))
        print(f"  {str(b):12} {'大' if k else '他'} n={len(gg):4d} 收盘{gg.mc_h.mean():.1%} 实际{a:.1%} ({(a-gg.mc_h.mean())*100:+.1f}pp ±{np.sqrt(a*(1-a)/len(gg))*100:.1f})")
# 控制概率后的残差差异
df["res"]=df.hw-df.mc_h
for k,g in df[df.mc_h>=0.5].groupby("big"):
    print(f"  收盘≥50%主队 {'大球队' if k else '其他'} n={len(g)} 残差 {g.res.mean()*100:+.1f}pp ±{g.res.std()/np.sqrt(len(g))*100:.1f}")
# 分赛季稳定性
print("\n大球队主场残差分赛季")
for s,g in df[df.big].groupby("season"):
    print(f"  {s} n={len(g)} {g.res.mean()*100:+.1f}pp ±{g.res.std()/np.sqrt(len(g))*100:.1f}")
