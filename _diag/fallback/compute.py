"""兜底模型核对：dc_market（实盘参数 w=0.3）对 dc_xg，11 个实盘联赛，football.db 只读副本。
测试赛季 2324–2627，按月重拟合，同场配对 1X2 log loss；另存 Elo 与三者的概率，供 analyze.py 算融合。2526 以前的 w 已在 research.db 选定，这里不重选。
用法：PYTHONPATH=. python -u _diag/fallback/compute.py E1  -> _diag/fallback/rows_E1.csv（gitignore）
"""
import contextlib
import io
import sqlite3
import sys

import pandas as pd

from football_prediction.model_dc.market_dc import MarketDixonColesModel
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.model_elo.elo import EloModel
from football_prediction.validation.backtest import run_backtest

SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
lg = sys.argv[1]
src = sqlite3.connect("file:football.db?mode=ro", uri=True)
conn = sqlite3.connect(":memory:")
src.backup(conn)          # 拟合在内存副本上做，不碰实盘库
src.close()
out = []
for test in SEASONS[2:]:
    train = SEASONS[:SEASONS.index(test)]
    got = {}
    for name, cls in (("xg", XgDixonColesModel), ("mk", MarketDixonColesModel), ("elo", EloModel)):
        with contextlib.redirect_stdout(io.StringIO()):
            r = run_backtest(conn, lg, train, [test], cls, refit_freq="monthly")
        cols = {"log_loss": f"ll_{name}", "p_home_win": f"h_{name}", "p_draw": f"d_{name}", "p_away_win": f"a_{name}"}
        got[name] = r[["match_id", "actual", *cols]].rename(columns=cols)
    m = (got["xg"].merge(got["mk"].drop(columns="actual"), on="match_id")
         .merge(got["elo"].drop(columns="actual"), on="match_id").assign(league=lg, season=test))
    out.append(m)
    print(f"{lg} {test}: n={len(m)} xg={m.ll_xg.mean():.4f} mk={m.ll_mk.mean():.4f}", flush=True)
pd.concat(out).to_csv(f"_diag/fallback/rows_{lg}.csv", index=False)
