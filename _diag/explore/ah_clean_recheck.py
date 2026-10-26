"""剔除亚盘坏行后复核（只读 research.db 与 football.db）。
坏行：赛前平均亚盘两边隐含概率和 1/avg_ahh + 1/avg_aha < 1（docs/issues.md「AvgAHA 约 4.4」那一条）。
复核三件事，都按实盘 analysis.asian 的做法算（市场隐含比分矩阵、rho −0.05、选择方 = 等效赢盘概率 ≥ 0.5 的一方）：
  1. 亚盘信心档 AH_TIERS（市场线上选择方赢盘概率 ≥0.56 高 / ≥0.54 中 / 其余低）的命中；
  2. 稳妥线（analysis.safe_line，SAFE_TARGET 0.65）的平均概率与命中；
  3. 胜平负市场档（Shin 最大概率 ≥0.60 为高，即「★ 重点」）的命中，以及重点场次的亚盘选择方命中。
命中：赢 / 赢半 记中，输 / 输半 记不中，走盘不计。另查 1X2、大小 2.5 有没有同类「和 < 1」的行。
research.db：1213–2425 标定，2526 留出；football.db（11 联赛）：2122–2425 对 2526–2627。
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/explore/ah_clean_recheck.py > _diag/explore/ah_clean_recheck.log
"""
import sqlite3

import numpy as np
import pandas as pd

from football_prediction.model_market.devig import shin
from football_prediction.model_market.implied import implied_matrix
from football_prediction.output.analysis import AH_TIERS, MARKET_TIERS, SAFE_TARGET, safe_line
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf

SQL = """SELECT m.league, m.season, m.match_date, m.home_goals hg, m.away_goals ag,
                o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25, o.ah_line, o.avg_ahh, o.avg_aha
         FROM matches m JOIN match_odds o USING(match_id)
         WHERE m.match_date >= ? AND o.ah_line IS NOT NULL AND o.avg_ahh > 1 AND o.avg_aha > 1
           AND o.avg_h > 1 AND o.avg_over25 > 1 AND m.home_goals IS NOT NULL
         ORDER BY m.match_date"""
SOURCES = (("research.db", "2012-07-01", lambda s: s == "2526", "标定 1213–2425", "留出 2526"),
           ("football.db", "2021-07-01", lambda s: s >= "2526", "2122–2425", "2526–2627"))
HIGH_1X2 = MARKET_TIERS[0][0]


def load(db: str, since: str) -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    df = pd.read_sql_query(SQL, conn, params=(since,))
    conn.close()
    df["bad"] = 1 / df.avg_ahh + 1 / df.avg_aha < 1
    return df


def hit_of(hg: int, ag: int, line: float, side: str) -> float | None:
    """选择方按主队方向 line 的结果：1 赢 / 赢半，0 输 / 输半，走盘 None。"""
    res = ah_outcome({int(hg - ag): 1.0}, line)
    k = max(res, key=res.get)
    if k == "push":
        return None
    home_won = float(k in ("win", "half_win"))
    return home_won if side == "主" else 1 - home_won


def tier_name(p: float) -> str:
    return next(name for lo, name, _ in AH_TIERS if p >= lo)


def rows(df: pd.DataFrame):
    for r in df.itertuples():
        od = {"h": r.avg_h, "d": r.avg_d, "a": r.avg_a, "over": r.avg_over25,
              "under": r.avg_under25, "ah_line": r.ah_line, "ah_h": r.avg_ahh, "ah_a": r.avg_aha}
        got = implied_matrix(od, -0.05)
        if got is None:
            continue
        pmf = margin_pmf(got[0])
        fair = ah_fair_prob(ah_outcome(pmf, r.ah_line))
        side, p = ("主", fair) if fair >= 0.5 else ("客", 1 - fair)
        safe = safe_line(lambda x: ah_fair_prob(ah_outcome(pmf, x)), r.ah_line, side)
        ps = shin([r.avg_h, r.avg_d, r.avg_a])
        res = 0 if r.hg > r.ag else 1 if r.hg == r.ag else 2
        yield {"league": r.league, "season": r.season, "bad": r.bad, "p": p, "tier": tier_name(p),
               "hit": hit_of(r.hg, r.ag, r.ah_line, side),
               "safe_p": safe[1] if safe else None, "safe_steps": None if not safe else
               round(abs(safe[0] - r.ah_line) / 0.25),
               "safe_hit": hit_of(r.hg, r.ag, safe[0], side) if safe else None,
               "pmax": float(max(ps)), "hit1x2": float(int(np.argmax(ps)) == res)}


def rate(s: pd.Series) -> str:
    s = s.dropna()
    if not len(s):
        return "n=0"
    m = s.mean()
    return f"{m:.3f}±{np.sqrt(m * (1 - m) / len(s)):.3f}（n={len(s)}）"


def report(d: pd.DataFrame, name: str) -> None:
    print(f"\n== {name}  共 {len(d)} 场，坏行 {int(d.bad.sum())}")
    for label, g in (("全部", d), ("剔除坏行", d[~d.bad]), ("只看坏行", d[d.bad])):
        if not len(g):
            continue
        print(f"  [{label}] 亚盘选择方命中 {rate(g.hit)}")
        for _, t, ref in AH_TIERS:
            x = g[g.tier == t]
            print(f"      亚盘{t}档 n={len(x):>5}（{len(x) / len(g):.1%}） 平均概率 "
                  f"{x.p.mean() if len(x) else float('nan'):.3f}  命中 {rate(x.hit)}  （代码里写 {ref}）")
        s = g.dropna(subset=["safe_p"])
        print(f"      稳妥线 T={SAFE_TARGET}：找到 {len(s)}/{len(g)}  平均概率 {s.safe_p.mean():.3f}  "
              f"命中 {rate(s.safe_hit)}  退步数 {s.safe_steps.value_counts().sort_index().to_dict()}")
        hi = g[g.pmax >= HIGH_1X2]
        print(f"      ★ 重点（胜平负高档）n={len(hi)}（{len(hi) / len(g):.1%}）  胜平负命中 {rate(hi.hit1x2)}  "
              f"同场亚盘选择方命中 {rate(hi.hit)}  稳妥线命中 {rate(hi.safe_hit)}")


def other_markets(db: str, since: str) -> None:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = """SELECT m.season, SUM(1/o.avg_h + 1/o.avg_d + 1/o.avg_a < 1) x12,
                  SUM(1/o.avg_over25 + 1/o.avg_under25 < 1) ou, COUNT(*) n
           FROM matches m JOIN match_odds o USING(match_id)
           WHERE m.match_date >= ? AND o.avg_h > 1 AND o.avg_d > 1 AND o.avg_a > 1
             AND o.avg_over25 > 1 AND o.avg_under25 > 1 GROUP BY m.season HAVING x12 > 0 OR ou > 0"""
    got = conn.execute(q, (since,)).fetchall()
    conn.close()
    print(f"  {db} 胜平负 / 大小 2.5 两边（三边）和 < 1 的赛季：{got or '没有'}")


def main():
    for db, since, is_hold, cal_name, hold_name in SOURCES:
        d = pd.DataFrame(rows(load(db, since)))
        print(f"\n######## {db}（{since} 起，赛前平均赔率）")
        other_markets(db, since)
        report(d[~d.season.map(is_hold)], cal_name)
        report(d[d.season.map(is_hold)], hold_name)
        h = d[d.season.map(is_hold) & ~d.bad]
        print(f"\n  {hold_name} 剔除坏行后各联赛稳妥线命中：")
        for lg, g in h.groupby("league"):
            print(f"    {lg:<4} {rate(g.safe_hit)}  亚盘选择方 {rate(g.hit)}")


if __name__ == "__main__":
    main()
