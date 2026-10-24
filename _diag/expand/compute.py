"""Per-match out-of-sample probs on research.db: dc_xg (monthly refit), Elo (monthly), market (pre-match avg).
Test seasons 1718..2526 (>= 3 prior seasons of history). One league per process.
Usage: PYTHONPATH=. python -u _diag/expand/compute.py I1   -> _diag/expand/probs_I1.csv
"""
import contextlib, io, sys
import pandas as pd

from football_prediction.data.loader import init_db
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.model_elo.elo import EloModel
from football_prediction.validation.backtest import run_backtest, run_market_backtest

ALL = [f"{y:02d}{y + 1:02d}" for y in range(14, 26)]
TESTS = ALL[3:]
lg = sys.argv[1]
conn = init_db("research.db")
out = []
for test in TESTS:
    train = ALL[:ALL.index(test)]
    with contextlib.redirect_stdout(io.StringIO()):
        xg = run_backtest(conn, lg, train, [test], XgDixonColesModel, refit_freq="monthly")
        elo = run_backtest(conn, lg, train, [test], EloModel, refit_freq="monthly")
        mk = run_market_backtest(conn, lg, [test], closing=False)
    cols = ["match_id", "p_home_win", "p_draw", "p_away_win", "log_loss"]
    m = (xg.merge(elo[cols], on="match_id", suffixes=("", "_elo"))
           .merge(mk[cols], on="match_id", suffixes=("", "_mk")))
    m = m.rename(columns={c: c + "_xg" for c in cols[1:]})
    m["league"], m["season"] = lg, test
    out.append(m)
    print(f"{lg} {test}: n={len(m)} xg={m['log_loss_xg'].mean():.4f} "
          f"elo={m['log_loss_elo'].mean():.4f} mk={m['log_loss_mk'].mean():.4f}", flush=True)
pd.concat(out).to_csv(f"_diag/expand/probs_{lg}.csv", index=False)
