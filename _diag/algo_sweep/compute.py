"""市场反推算法对照（研究脚本，只读 football.db，不改实盘）。
同一场比赛用不同的去水方法 / rho / 盘口权重 / 赔率来源反推 λ，按同一条赛前市场亚盘线评分。
变体：
  base     现行：按比例去水，rho −0.05，1X2 + 大小2.5 + 亚盘等权
  shin     Shin 去水
  power    幂函数去水（p = q^k，Σ=1）
  rho0 / rho10   rho 0 / −0.10
  ah3      亚盘一项权重 ×3
  only1x2  只用 1X2（看大小球和亚盘带来多少信息）
  pin1x2   1X2 换成 Pinnacle 赛前（大小球、亚盘仍用平均）
  close    全部换成收盘平均赔率（参考上限，存档时拿不到）
用法：PYTHONPATH=. python -u _diag/algo_sweep/compute.py E0  -> _diag/algo_sweep/rows_E0.csv
"""
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize

from football_prediction.model_market.devig import devig as devig_m
from football_prediction.model_market.implied import DEFAULT_RHO, _G, dc_matrix
from football_prediction.output.derive import AH_KEYS, ah_fair_prob, ah_outcome, margin_pmf
from football_prediction.review.store import ah_scores

TOT = np.add.outer(_G, _G)


def power(odds):
    q = 1 / np.asarray(odds, float)
    if q.sum() <= 1:   # 无水或负水：按比例
        return q / q.sum()
    k = brentq(lambda k: (q ** k).sum() - 1, 1.0, 20)
    return q ** k


def dv(odds, method):
    return power(odds) if method == "power" else devig_m(list(odds), method)


def ok(*xs):
    return all(x is not None and x == x and x > 1 for x in xs)


def fit(o, method="proportional", rho=DEFAULT_RHO, w_ah=1.0, use=("1x2", "ou", "ah")):
    if not ok(o["h"], o["d"], o["a"]):
        return None
    p1 = dv([o["h"], o["d"], o["a"]], method)
    pou = dv([o["over"], o["under"]], method)[0] if "ou" in use and ok(o["over"], o["under"]) else None
    pah = (dv([o["ahh"], o["aha"]], method)[0] if "ah" in use and o["line"] == o["line"]
           and ok(o["ahh"], o["aha"]) else None)

    def loss(x):
        lh, la = np.exp(np.clip(x, -3, 2))
        m = dc_matrix(lh, la, rho)
        s = sum((a - b) ** 2 for a, b in zip((np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()), p1))
        if pou is not None:
            s += (m[TOT > 2.5].sum() - pou) ** 2
        if pah is not None:
            s += w_ah * (ah_fair_prob(ah_outcome(margin_pmf(m), o["line"])) - pah) ** 2
        return s

    sup, tot = (p1[0] - p1[2]) * 2, 2.6 + ((pou or 0.5) - 0.5) * 3
    x0 = np.log(np.clip([(tot + sup) / 2, (tot - sup) / 2], 0.2, 5))
    r = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-10})
    lh, la = np.exp(np.clip(r.x, -3, 2))
    return dc_matrix(lh, la, rho)


def main(lg):
    conn = sqlite3.connect("file:football.db?mode=ro", uri=True)
    d = pd.read_sql_query(
        """SELECT m.match_id, m.season, m.match_date, m.home_goals hg, m.away_goals ag, o.*
           FROM matches m JOIN match_odds o USING(match_id)
           WHERE m.league = ? AND m.home_goals IS NOT NULL AND o.ah_line IS NOT NULL
           ORDER BY m.match_date""", conn, params=[lg])
    d = d.loc[:, ~d.columns.duplicated()]
    rows = []
    for r in d.to_dict("records"):
        r = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        line = float(r["ah_line"])
        pre = dict(h=r["avg_h"], d=r["avg_d"], a=r["avg_a"], over=r["avg_over25"], under=r["avg_under25"],
                   line=line, ahh=r["avg_ahh"], aha=r["avg_aha"])
        cl_line = r["ahc_line"] if r["ahc_line"] is not None else float("nan")
        variants = {
            "base": fit(pre), "shin": fit(pre, "shin"), "power": fit(pre, "power"),
            "rho0": fit(pre, rho=0.0), "rho10": fit(pre, rho=-0.10), "ah3": fit(pre, w_ah=3.0),
            "only1x2": fit(pre, use=("1x2",)),
            "pin1x2": fit({**pre, "h": r["ps_h"], "d": r["ps_d"], "a": r["ps_a"]}),
            "close": fit(dict(h=r["avgc_h"], d=r["avgc_d"], a=r["avgc_a"], over=r["avgc_over25"],
                              under=r["avgc_under25"], line=float(cl_line),
                              ahh=r["avgc_ahh"], aha=r["avgc_aha"])),
        }
        hg, ag = int(r["hg"]), int(r["ag"])
        y = 0 if hg > ag else 1 if hg == ag else 2
        out = dict(match_id=r["match_id"], league=lg, season=r["season"], ah_line=line, hg=hg, ag=ag)
        for k, m in variants.items():
            if m is None:
                continue
            p1 = (np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum())
            ah = ah_outcome(margin_pmf(m), line)
            ll_ah, hit = ah_scores({f"ah_{line + 0.0:+.2f}": [ah[x] for x in AH_KEYS]}, hg, ag, line)
            pov = m[TOT > 2.5].sum()
            out.update({f"{k}_ll1": -np.log(max(p1[y], 1e-7)), f"{k}_hit1": float(np.argmax(p1) == y),
                        f"{k}_llah": ll_ah, f"{k}_hitah": hit,
                        f"{k}_cover": ah["win"] + ah["half_win"] / 2,
                        f"{k}_coverlose": ah["lose"] + ah["half_lose"] / 2,
                        f"{k}_llou": -np.log(max(pov if hg + ag > 2 else 1 - pov, 1e-7))})
        rows.append(out)
    pd.DataFrame(rows).to_csv(f"_diag/algo_sweep/rows_{lg}.csv", index=False)
    print(f"{lg} done n={len(rows)}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
