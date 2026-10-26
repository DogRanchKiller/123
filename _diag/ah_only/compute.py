"""只用亚盘 + 大小球反推比分（不用 1X2），对照现行 1X2 + 大小2.5 + 亚盘（研究脚本，只读）。
依据：Hegarty & Whelan (2025, IJF) 发现 1X2 有热门-冷门偏差、亚盘赔率换成概率更有效。
变体：
  base   现行：按比例去水，rho −0.05，1X2 + 大小2.5 + 亚盘等权
  ahou   只用亚盘 + 大小2.5（两个约束解 λh、λa），1X2 由比分矩阵推出
  ah1x2h 1X2 权重减半（介于两者之间）
评分：1X2 LL、同一条赛前亚盘线的五种结算 LL 与赢盘命中、大小 2.5 LL。
用法：PYTHONPATH=. python -u _diag/ah_only/compute.py research.db E0  -> _diag/ah_only/rows_E0.csv
"""
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from football_prediction.model_market.devig import devig
from football_prediction.model_market.implied import DEFAULT_RHO, _G, dc_matrix
from football_prediction.output.derive import AH_KEYS, ah_fair_prob, ah_outcome, margin_pmf
from football_prediction.review.store import ah_scores

TOT = np.add.outer(_G, _G)


def ok(*xs):
    return all(x is not None and x == x and x > 1 for x in xs)


def fit(o, w1=1.0):
    """w1 = 1X2 三项的权重；0 表示不用 1X2。大小球和亚盘都要有。"""
    if not (ok(o["over"], o["under"], o["ahh"], o["aha"]) and o["line"] == o["line"]):
        return None
    if w1 and not ok(o["h"], o["d"], o["a"]):
        return None
    p1 = devig([o["h"], o["d"], o["a"]], "proportional") if w1 else None
    pou = devig([o["over"], o["under"]], "proportional")[0]
    pah = devig([o["ahh"], o["aha"]], "proportional")[0]

    def loss(x):
        lh, la = np.exp(np.clip(x, -3, 2))
        m = dc_matrix(lh, la, DEFAULT_RHO)
        s = (m[TOT > 2.5].sum() - pou) ** 2
        s += (ah_fair_prob(ah_outcome(margin_pmf(m), o["line"])) - pah) ** 2
        if w1:
            s += w1 * sum((a - b) ** 2 for a, b in
                          zip((np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()), p1))
        return s

    sup, tot = -o["line"] + (pah - 0.5) * 2, 2.6 + (pou - 0.5) * 3   # 亚盘线给净胜球的起点
    x0 = np.log(np.clip([(tot + sup) / 2, (tot - sup) / 2], 0.2, 5))
    r = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-10})
    lh, la = np.exp(np.clip(r.x, -3, 2))
    return dc_matrix(lh, la, DEFAULT_RHO)


def main(db, lg):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    d = pd.read_sql_query(
        """SELECT m.match_id, m.season, m.match_date, m.home_goals hg, m.away_goals ag,
                  o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25, o.ah_line, o.avg_ahh, o.avg_aha
           FROM matches m JOIN match_odds o USING(match_id)
           WHERE m.league = ? AND m.home_goals IS NOT NULL AND o.ah_line IS NOT NULL
           ORDER BY m.match_date""", conn, params=[lg])
    rows = []
    for r in d.to_dict("records"):
        r = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        o = dict(h=r["avg_h"], d=r["avg_d"], a=r["avg_a"], over=r["avg_over25"], under=r["avg_under25"],
                 line=float(r["ah_line"]), ahh=r["avg_ahh"], aha=r["avg_aha"])
        # 坏赔率组（隐含概率和 < 1）跳过，与 data 1.9.0 入库规则一致
        if any(ok(*g) and sum(1 / x for x in g) < 1 for g in
               ((o["h"], o["d"], o["a"]), (o["over"], o["under"]), (o["ahh"], o["aha"]))):
            continue
        variants = {"base": fit(o), "ahou": fit(o, 0.0), "ah1x2h": fit(o, 0.5)}
        if any(m is None for m in variants.values()):
            continue
        hg, ag, line = int(r["hg"]), int(r["ag"]), o["line"]
        y = 0 if hg > ag else 1 if hg == ag else 2
        out = dict(match_id=r["match_id"], league=lg, season=r["season"], match_date=r["match_date"],
                   ah_line=line, hg=hg, ag=ag)
        for k, m in variants.items():
            p1 = (np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum())
            ah = ah_outcome(margin_pmf(m), line)
            ll_ah, hit = ah_scores({f"ah_{line + 0.0:+.2f}": [ah[x] for x in AH_KEYS]}, hg, ag, line)
            pov = m[TOT > 2.5].sum()
            out.update({f"{k}_ll1": -np.log(max(p1[y], 1e-7)), f"{k}_hit1": float(np.argmax(p1) == y),
                        f"{k}_llah": ll_ah, f"{k}_hitah": hit,
                        f"{k}_llou": -np.log(max(pov if hg + ag > 2 else 1 - pov, 1e-7))})
        rows.append(out)
    pd.DataFrame(rows).to_csv(f"_diag/ah_only/rows_{lg}.csv", index=False)
    print(f"{lg} done n={len(rows)}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
