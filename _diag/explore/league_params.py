"""Per-league differences on research.db: base rates, market calibration, rho.

Run: PYTHONPATH=. python _diag/explore/league_params.py
"""
import sqlite3

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

from football_prediction.model_market.implied import fit_lambdas

c = sqlite3.connect("research.db")
rows = c.execute("""
    select m.league, m.season, m.home_goals, m.away_goals,
           o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25,
           o.ah_line, o.avg_ahh, o.avg_aha
    from matches m join match_odds o using(match_id)
    where o.avg_h > 1 and o.avg_d > 1 and o.avg_a > 1
""").fetchall()
L = sorted({r[0] for r in rows})

print("== base rates (all seasons) ==")
print("lg     n   goals  home  draw  away  hg/ag  over25  overround")
for lg in L:
    R = [r for r in rows if r[0] == lg]
    hg = np.array([r[2] for r in R]); ag = np.array([r[3] for r in R])
    ovr = np.mean([1 / r[4] + 1 / r[5] + 1 / r[6] for r in R])
    print(f"{lg:4} {len(R):5} {np.mean(hg+ag):5.2f} {np.mean(hg>ag):5.3f} {np.mean(hg==ag):5.3f}"
          f" {np.mean(hg<ag):5.3f} {hg.mean()/ag.mean():5.2f} {np.mean(hg+ag>2.5):6.3f} {ovr:8.3f}")

print("\n== market calibration by league (proportional devig) ==")
print("lg   draw_pred draw_act | fav>=.70: n pred act | top-pick hit")
for lg in L:
    R = [r for r in rows if r[0] == lg]
    P = np.array([[1 / r[4], 1 / r[5], 1 / r[6]] for r in R]); P /= P.sum(1, keepdims=True)
    y = np.array([0 if r[2] > r[3] else 1 if r[2] == r[3] else 2 for r in R])
    top = P.argmax(1); pm = P.max(1); f = pm >= 0.70
    print(f"{lg:4} {P[:,1].mean():9.3f} {np.mean(y==1):8.3f} | {f.sum():5} {pm[f].mean():.3f}"
          f" {np.mean(top[f]==y[f]):.3f} | {np.mean(top==y):.3f}")


def dc_logp(hg, ag, lh, la, rho):
    p = poisson.pmf(hg, lh) * poisson.pmf(ag, la)
    tau = np.ones_like(p)
    tau = np.where((hg == 0) & (ag == 0), 1 - lh * la * rho, tau)
    tau = np.where((hg == 0) & (ag == 1), 1 + lh * rho, tau)
    tau = np.where((hg == 1) & (ag == 0), 1 + la * rho, tau)
    tau = np.where((hg == 1) & (ag == 1), 1 - rho, tau)
    return np.log(np.clip(p * tau, 1e-12, None))


print("\n== rho by league (market lambdas, score log-lik) ==")
cache = {}
for lg in L:
    R = [r for r in rows if r[0] == lg]
    lam = []
    for r in R:
        f = fit_lambdas({"h": r[4], "d": r[5], "a": r[6], "over": r[7], "under": r[8],
                         "ah_line": r[9], "ah_h": r[10], "ah_a": r[11]})
        lam.append((f["lam_h"], f["lam_a"]))
    cache[lg] = (np.array([r[2] for r in R]), np.array([r[3] for r in R]), np.array(lam),
                 np.array([r[1] for r in R]))

# leave-one-season-out style check: fit rho on other seasons, score on this season
pool = {k: v for k, v in cache.items()}
allhg = np.concatenate([v[0] for v in pool.values()])
allag = np.concatenate([v[1] for v in pool.values()])
alllam = np.concatenate([v[2] for v in pool.values()])


def best_rho(hg, ag, lam):
    return minimize_scalar(lambda r: -dc_logp(hg, ag, lam[:, 0], lam[:, 1], r).sum(),
                           bounds=(-0.3, 0.3), method="bounded").x


g = best_rho(allhg, allag, alllam)
print(f"pooled rho = {g:+.3f}")
print("lg   rho_lg   score-LL gain/match vs pooled (in-sample) | out-of-season gain +- SE")
for lg, (hg, ag, lam, ss) in cache.items():
    r = best_rho(hg, ag, lam)
    gain = (dc_logp(hg, ag, lam[:, 0], lam[:, 1], r) - dc_logp(hg, ag, lam[:, 0], lam[:, 1], g)).mean()
    d = []
    for s in sorted(set(ss)):
        tr, te = ss != s, ss == s
        rl = best_rho(hg[tr], ag[tr], lam[tr])
        d.append(dc_logp(hg[te], ag[te], lam[te, 0], lam[te, 1], rl)
                 - dc_logp(hg[te], ag[te], lam[te, 0], lam[te, 1], g))
    d = np.concatenate(d)
    print(f"{lg:4} {r:+.3f}   {gain:+.5f}   | {d.mean():+.5f} +- {d.std()/np.sqrt(len(d)):.5f}")
