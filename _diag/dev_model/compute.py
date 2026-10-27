"""自研模型单独开发线 · 第一步：dc_market 的逐场样本外 λ，供 evaluate.py 在全部盘口上打分。
不改实盘：拟合在 football.db 的内存副本上做，不写库，不 import services；实盘的 dc_market 存档不受影响。
11 个实盘联赛，测试赛季 2324–2627，训练从 2122 起、按月重拟合（与 _diag/fallback/compute.py 同设定）。
λ 由模型的公开参数 attack / defence / home_adv 算（未见过的球队用联赛均值，与 DixonColesModel 一致），
evaluate.py 用 implied.dc_matrix(λ主, λ客, rho) 重建比分矩阵，与 score_matrix 同算法。
用法：PYTHONPATH=. python -u _diag/dev_model/compute.py [联赛 ...]  -> _diag/dev_model/rows_{lg}.csv（gitignore）
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_dc.market_dc import MarketDixonColesModel

HERE = Path(__file__).parent
LEAGUES = ["E0", "D1", "SP1", "I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
TESTS = SEASONS[2:]


def team_lambdas(model: MarketDixonColesModel, home: str, away: str) -> tuple[float, float]:
    atk, dfc = model.attack, model.defence
    ma, md = float(np.mean(list(atk.values()))), float(np.mean(list(dfc.values())))
    lh = np.exp(atk.get(home, ma) - dfc.get(away, md) + model.home_adv)
    la = np.exp(atk.get(away, ma) - dfc.get(home, md))
    return float(lh), float(la)


def run(conn: sqlite3.Connection, lg: str) -> pd.DataFrame:
    test = pd.read_sql_query(
        f"""SELECT m.match_id, m.season, m.match_date, m.home_team, m.away_team,
                   m.home_goals AS hg, m.away_goals AS ag,
                   o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25, o.ah_line
            FROM matches m LEFT JOIN match_odds o ON m.match_id = o.match_id
            WHERE m.league = ? AND m.season IN ({",".join("?" * len(TESTS))})
              AND m.home_goals IS NOT NULL
            ORDER BY m.match_date""", conn, params=[lg, *TESTS])
    rows, model, month = [], None, None
    for r in test.itertuples():
        if r.match_date[:7] != month:
            month = r.match_date[:7]
            model = MarketDixonColesModel()
            model.fit(conn, lg, r.match_date)
        lh, la = team_lambdas(model, r.home_team, r.away_team)
        rows.append({**r._asdict(), "league": lg, "dc_lh": lh, "dc_la": la, "dc_rho": model.rho})
    return pd.DataFrame(rows).drop(columns="Index")


def main() -> None:
    leagues = sys.argv[1:] or LEAGUES
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    for lg in leagues:
        df = run(conn, lg)
        df.to_csv(HERE / f"rows_{lg}.csv", index=False)
        print(f"{lg}: {len(df)} 场", flush=True)


if __name__ == "__main__":
    main()
