"""亚盘基线（research.db，只读）：市场隐含模型在【赛前市场亚盘线】上的五种结算 log loss、
赢盘方命中率（不含走盘），以及按「赢盘概率」分档的命中，给报告的亚盘信心档标定。
样本 1213–2425 标定，2526 留出复核（与 reliability.py 相同）；赛前平均赔率 avg_*，rho 用默认 −0.05。
命中定义：赢盘概率 > 50% 的一方为选择方；结算为 赢 / 赢半 记中，输 / 输半 记不中，走盘不计。
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/explore/ah_baseline.py > _diag/explore/ah_baseline.log
"""
import sqlite3
from math import log

import numpy as np
import pandas as pd

from football_prediction.model_market.implied import fair_probs, implied_matrix
from football_prediction.output.derive import AH_KEYS, ah_fair_prob, ah_outcome, margin_pmf

DB = "research.db"
FROM = "2012-07-01"
HOLDOUT = "2526"
BINS = (0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 1.01)


def load() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        """SELECT m.match_id, m.league, m.season, m.match_date, m.home_goals hg, m.away_goals ag,
                  o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25,
                  o.ah_line, o.avg_ahh, o.avg_aha
           FROM matches m JOIN match_odds o USING(match_id)
           WHERE m.match_date >= ? AND o.ah_line IS NOT NULL AND o.avg_ahh > 1 AND o.avg_aha > 1
             AND o.avg_h > 1 AND o.avg_over25 > 1 AND m.home_goals IS NOT NULL
           ORDER BY m.match_date""", conn, params=(FROM,))
    conn.close()
    return df


def line_type(line: float) -> str:
    q = round(abs(line) * 4) % 4
    return {0: "整数", 2: "半球", 1: "四分之一", 3: "四分之一"}[q]


def rows(df: pd.DataFrame):
    for r in df.itertuples():
        od = {"h": r.avg_h, "d": r.avg_d, "a": r.avg_a, "over": r.avg_over25,
              "under": r.avg_under25, "ah_line": r.ah_line, "ah_h": r.avg_ahh, "ah_a": r.avg_aha}
        got = implied_matrix(od, -0.05)
        if got is None:
            continue
        o = ah_outcome(margin_pmf(got[0]), r.ah_line)
        res = ah_outcome({int(r.hg - r.ag): 1.0}, r.ah_line)
        k = max(res, key=res.get)                               # 实际结算
        fair = ah_fair_prob(o)
        mkt = fair_probs(od)["ah"][1]
        home_side = fair >= 0.5
        hit = None if k == "push" else (k in ("win", "half_win")) == home_side
        yield {"season": r.season, "league": r.league, "line": r.ah_line, "type": line_type(r.ah_line),
               "settle": k, "ll5": -log(max(o[k], 1e-7)), "fair": fair, "mkt": mkt,
               "pcover": max(fair, 1 - fair), "pmkt": max(mkt, 1 - mkt), "hit": hit,
               **{f"p_{x}": o[x] for x in AH_KEYS}}


def summary(d: pd.DataFrame, name: str) -> None:
    h = d.dropna(subset=["hit"])
    print(f"\n== {name}  n={len(d)}（不含走盘 {len(h)}）")
    print(f"  五种结算 log loss {d.ll5.mean():.4f}   选择方命中 {h.hit.mean():.3f}   "
          f"走盘占比 {(d.settle == 'push').mean():.3f}")
    print(f"  隐含赢盘概率 vs 市场去水（主队方向）平均绝对差 {np.abs(d.fair - d.mkt).mean():.4f}")
    d = h.assign(bin=pd.cut(h.pcover, BINS, right=False))
    t = d.groupby("bin", observed=True).agg(n=("hit", "size"), p=("pcover", "mean"), hit=("hit", "mean"))
    print("  赢盘概率分档（选择方）：")
    for b, r in t.iterrows():
        se = np.sqrt(r.hit * (1 - r.hit) / r.n)
        print(f"    {str(b):<14} n={int(r.n):>6}  平均概率 {r.p:.3f}  实际命中 {r.hit:.3f}±{se:.3f}")
    t = h.groupby("type").agg(n=("hit", "size"), hit=("hit", "mean"))
    print("  按盘口类型：" + "  ".join(f"{k} n={int(r.n)} 命中 {r.hit:.3f}" for k, r in t.iterrows()))


def main():
    df = load()
    print(f"样本 {len(df)} 场（{FROM} 起，赛前平均亚盘）")
    print("盘口绝对值分布：", df.ah_line.abs().round(2).value_counts().sort_index().to_dict())
    d = pd.DataFrame(rows(df))
    summary(d[d.season != HOLDOUT], "标定 1213–2425")
    summary(d[d.season == HOLDOUT], "留出 2526")
    cal = d[(d.season != HOLDOUT)].dropna(subset=["hit"])
    print("\n各联赛（标定期）选择方命中：" + "  ".join(
        f"{lg} {g.hit.mean():.3f}(n={len(g)})" for lg, g in cal.groupby("league")))


if __name__ == "__main__":
    main()
