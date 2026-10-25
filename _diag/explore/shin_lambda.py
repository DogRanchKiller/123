"""Shin vs 按比例去水：完整 λ 反推流程（1X2 + 大小2.5 + 亚盘，赛前平均赔率）在 research.db 上同场对比。
指标：1X2 log loss / Brier（backtest._log_loss_one / _brier_one）、大小2.5 与精确比分 log loss
（review.store.market_log_losses），配对差用 backtest.paired_compare。
选择期 1415–2425，2526 留出只做确认。rho 固定 −0.056（5 联赛合并值），两种方法相同。
运行：PYTHONPATH=. python _diag/explore/shin_lambda.py > _diag/explore/shin_lambda.log
"""
import sqlite3
import sys

import pandas as pd

from football_prediction.model_market.implied import implied_matrix
from football_prediction.output.derive import derive_markets
from football_prediction.review.store import market_log_losses
from football_prediction.validation.backtest import _brier_one, _log_loss_one, paired_compare

RHO = -0.056
METHODS = ("proportional", "shin")
OUT = {(1, 0): "home_win", (0, 0): "draw", (0, 1): "away_win"}


def outcome(hg, ag):
    return "home_win" if hg > ag else "draw" if hg == ag else "away_win"


def rows(conn):
    return pd.read_sql_query(
        """SELECT m.match_id, m.league, m.season, m.home_goals hg, m.away_goals ag,
                  o.avg_h h, o.avg_d d, o.avg_a a, o.avg_over25 "over", o.avg_under25 under,
                  o.ah_line, o.avg_ahh ah_h, o.avg_aha ah_a
           FROM matches m JOIN match_odds o USING (match_id)
           WHERE o.avg_h > 1 AND o.avg_d > 1 AND o.avg_a > 1
             AND o.avg_over25 > 1 AND o.avg_under25 > 1""", conn)


def evaluate(df, method):
    recs = []
    for r in df.itertuples(index=False):
        odds = {"h": r.h, "d": r.d, "a": r.a, "over": r.over, "under": r.under,
                "ah_line": r.ah_line, "ah_h": r.ah_h, "ah_a": r.ah_a}
        m, _ = implied_matrix(odds, RHO, method)
        mk = derive_markets(m)
        p = {k: mk[k] for k in ("home_win", "draw", "away_win")}
        o = outcome(r.hg, r.ag)
        extra = {"over_2.5": mk["over_2.5"], "score_matrix": list(m.ravel())}
        ou, sc = market_log_losses(extra, int(r.hg), int(r.ag))
        recs.append({"match_id": r.match_id, "season": r.season, "league": r.league,
                     "log_loss": _log_loss_one(p, o), "brier": _brier_one(p, o),
                     "ou_ll": ou, "score_ll": sc})
    return pd.DataFrame(recs)


def report(res, label):
    a, b = res["shin"], res["proportional"]
    print(f"\n== {label}  n={len(a)}  （shin − 按比例，负=shin 更好）")
    for metric in ("log_loss", "brier", "ou_ll", "score_ll"):
        c = paired_compare(a, b, metric)
        print(f"  {metric:<9} 按比例 {b[metric].mean():.5f}  shin {a[metric].mean():.5f}  "
              f"差 {c['diff']:+.5f} ± {c['se']:.5f}")


def main():
    conn = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "research.db")
    df = rows(conn)
    print(f"有 1X2+大小2.5 赛前赔率的场次 {len(df)}（含亚盘 {df['ah_line'].notna().sum()}）")
    res = {m: evaluate(df, m) for m in METHODS}
    sel = {m: r[r["season"] != "2526"] for m, r in res.items()}
    hold = {m: r[r["season"] == "2526"] for m, r in res.items()}
    report(sel, "选择期 1415–2425")
    for lg in sorted(df["league"].unique()):
        c = paired_compare(sel["shin"][sel["shin"]["league"] == lg],
                           sel["proportional"][sel["proportional"]["league"] == lg])
        print(f"    {lg:<4} 1X2 差 {c['diff']:+.5f} ± {c['se']:.5f}  n={c['n']}")
    report(hold, "留出 2526")


if __name__ == "__main__":
    main()
