"""用包内 EloModel（v1.1.0）同算法检验 dc_xg+Elo 融合权重：选择期 2324+2425，确认 2526+2627
每个联赛逐场更新；每到新赛季用此前全部赛前评分差重拟有序 logit（与 fit(cutoff) 等价，无泄漏）"""
import numpy as np, pandas as pd
from scipy.optimize import minimize_scalar
from _diag.explore.harness import load_all, run, BASE
from football_prediction.model_elo.elo import EloModel, fit_ordlogit
df = load_all()
r = run(df, BASE).set_index("match_id")
E = {}
for lg, L in df.groupby("league"):
    m, season, D, Y = EloModel(), None, [], []
    for x in L.sort_values(["day", "match_id"]).itertuples():
        if x.season != season:
            season, m.ab = x.season, fit_ordlogit(D, Y)
        p = m.predict(x.home_team, x.away_team)
        E[x.match_id] = (p["home_win"], p["draw"], p["away_win"])
        D.append(m.diff(x.home_team, x.away_team) / 100)
        Y.append(0 if x.hg > x.ag else 1 if x.hg == x.ag else 2)
        m.update_one(x.home_team, x.away_team, int(x.hg), int(x.ag))
r = r.join(pd.DataFrame.from_dict(E, orient="index", columns=["e_h", "e_d", "e_a"]))
y = r.actual.to_numpy()
A, B = r[["p_h", "p_d", "p_a"]].to_numpy(), r[["e_h", "e_d", "e_a"]].to_numpy()
ll = lambda P: -np.log(np.clip(P[np.arange(len(P)), y], 1e-9, None))
sel = r.season.isin(["2324", "2425"]).to_numpy()
w = minimize_scalar(lambda w: ll((1 - w) * A + w * B)[sel].mean(), bounds=(0, 1), method="bounded").x
print(f"n={len(y)} 选择期最优 Elo 权重 {w:.3f}")
for ww in (w, 0.23):
    d = ll((1 - ww) * A + ww * B) - ll(A)
    for nm, m in (("选择", sel), ("确认", ~sel)):
        print(f"  w={ww:.2f} {nm} {d[m].mean():+.4f}±{d[m].std(ddof=1)/np.sqrt(m.sum()):.4f}")
d = ll(B) - ll(A); print(f"  包内Elo 单独 vs dc_xg 确认 {d[~sel].mean():+.4f}")
