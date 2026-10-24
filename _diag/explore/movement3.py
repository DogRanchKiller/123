import numpy as np, pandas as pd
from _diag.explore.harness import load_all
df = load_all().dropna(subset=["mc_h"]).copy()
BIG = {"Man City","Manchester Utd","Liverpool","Arsenal","Chelsea","Tottenham","Bayern Munich",
       "Dortmund","Barcelona","Real Madrid","Ath Madrid"}
df["big"] = df.home_team.isin(BIG) & ~df.away_team.isin(BIG)
df["res"] = (df.actual==0) - df.mc_h
df["bigA"] = df.away_team.isin(BIG) & ~df.home_team.isin(BIG)
df["resA"] = (df.actual==2) - df.mc_a
for name, ss in [("样本外 2122+2223", ["2122","2223"]), ("发现期 2324-2627", ["2324","2425","2526","2627"])]:
    d = df[df.season.isin(ss)]
    for lab, m, r in [("大球队主场", d.big & (d.mc_h>=0.5), "res"), ("其他主场热门", ~d.big & (d.mc_h>=0.5), "res"),
                      ("大球队客场", d.bigA & (d.mc_a>=0.5), "resA")]:
        g = d[m][r]
        print(f"{name} {lab:8} n={len(g):4d} 残差 {g.mean()*100:+.1f}pp ±{g.std()/np.sqrt(len(g))*100:.1f}")
    for s, g in d[d.big & (d.mc_h>=0.5)].groupby("season"):
        print(f"    {s} n={len(g)} {g.res.mean()*100:+.1f}pp")
# 逐队（全部6季）
print("\n逐队 主场且收盘≥50%")
d = df[df.big & (df.mc_h>=0.5)]
for t, g in d.groupby("home_team"):
    print(f"  {t:15} n={len(g):3d} 收盘{g.mc_h.mean():.1%} 残差 {g.res.mean()*100:+.1f}pp")
