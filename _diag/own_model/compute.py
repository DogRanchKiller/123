"""自研模型 vs 市场：11 联赛逐场样本外概率（研究脚本，不写 football.db、不改实盘）。
football.db 以只读方式打开，整库 backup 到内存后再拟合，原库不受影响。
模型：射正版 DC（dc_sot，11 联赛都有射正；dc_xg 在六个新联赛没有 xG，不公平）与 Elo，按月重拟合
（cutoff = 当月第一场比赛日期，只用之前的比赛）。市场：赛前平均赔率按比例去水；市场隐含比分矩阵
（1X2 + 大小2.5 + 亚盘反推 λ，rho 用默认 −0.05）。亚盘用该场赛前市场线算五种结算。
测试赛季 2324–2627（2122–2223 作起始历史）。2526 只作留出，不在上面选参。
用法：PYTHONPATH=. python -u _diag/own_model/compute.py E1   -> _diag/own_model/rows_E1.csv
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

from football_prediction.model_dc.sot_dc import SotDixonColesModel
from football_prediction.model_elo.elo import EloModel
from football_prediction.model_market.implied import implied_matrix
from football_prediction.output.analysis import devig, odds_dict
from football_prediction.output.derive import AH_KEYS, ah_outcome, margin_pmf

TESTS = ["2324", "2425", "2526", "2627"]


def memory_copy(path: str = "football.db") -> sqlite3.Connection:
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    mem = sqlite3.connect(":memory:")
    src.backup(mem)
    src.close()
    return mem


def main(lg: str) -> None:
    conn = memory_copy()
    df = pd.read_sql_query(
        f"""SELECT m.match_id, m.season, m.match_date, m.home_team, m.away_team,
                   m.home_goals, m.away_goals, o.avg_h, o.avg_d, o.avg_a,
                   o.avg_over25, o.avg_under25, o.ah_line, o.avg_ahh, o.avg_aha
            FROM matches m JOIN match_odds o USING(match_id)
            WHERE m.league = ? AND m.season IN ({','.join('?' * len(TESTS))})
              AND m.home_goals IS NOT NULL AND o.avg_h > 1 AND o.avg_d > 1 AND o.avg_a > 1
            ORDER BY m.match_date""", conn, params=[lg] + TESTS)
    rows, key, sot, elo = [], None, None, None
    for r in df.to_dict("records"):
        r = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        if r["match_date"][:7] != key:
            key = r["match_date"][:7]
            sot, elo = SotDixonColesModel(), EloModel()
            sot.fit(conn, lg, r["match_date"])
            elo.fit(conn, lg, r["match_date"])
            print(f"{lg} {key}", flush=True)
        h, a = r["home_team"], r["away_team"]
        mk = devig(r["avg_h"], r["avg_d"], r["avg_a"])
        ms = sot.score_matrix(h, a)
        lam_s = sot._lambda(h, a)
        pe = elo.predict(h, a)
        out = {k: r[k] for k in ("match_id", "season", "match_date", "home_team", "away_team",
                                 "home_goals", "away_goals", "ah_line")}
        out.update(league=lg, mk_h=mk[0], mk_d=mk[1], mk_a=mk[2],
                   sot_h=float(np.tril(ms, -1).sum()), sot_d=float(np.trace(ms)),
                   sot_a=float(np.triu(ms, 1).sum()),
                   elo_h=pe["home_win"], elo_d=pe["draw"], elo_a=pe["away_win"],
                   lam_sot_h=float(lam_s[0]), lam_sot_a=float(lam_s[1]),
                   sot_known=int(h in sot.attack and a in sot.attack))
        od = odds_dict(r)
        got = implied_matrix(od) if devig(r["avg_over25"], r["avg_under25"]) else None
        if got is not None:
            mi, fit = got
            out.update(lam_mk_h=fit["lam_h"], lam_mk_a=fit["lam_a"])
            if r["ah_line"] is not None:
                for name, m in (("mk", mi), ("sot", ms)):
                    o = ah_outcome(margin_pmf(m), float(r["ah_line"]))
                    out.update({f"ah_{name}_{k}": o[k] for k in AH_KEYS})
        rows.append(out)
    pd.DataFrame(rows).to_csv(f"_diag/own_model/rows_{lg}.csv", index=False)
    print(f"{lg} done n={len(rows)}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
