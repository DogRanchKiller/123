"""射正版回测（计算）：逐场保存 DC v1.3.0、射正版各 w、市场赛前概率。月度重拟合。"""
import functools
import pandas as pd
from football_prediction.data.loader import init_db
from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.model_dc.sot_dc import SotDixonColesModel
from football_prediction.validation.backtest import run_backtest, run_market_backtest

ALL = ["2122", "2223", "2324", "2425", "2526"]
WS = [1.0, 0.7, 0.5, 0.3, 0.0]
conn = init_db("football.db")
out = []
for lg in ["E0", "D1", "SP1"]:
    for test in ["2324", "2425", "2526"]:
        train = ALL[:ALL.index(test)]
        models = {"dc": DixonColesModel}
        for w in WS:
            models[f"sot_w{w}"] = functools.partial(SotDixonColesModel, goal_weight=w)
        for name, cls in models.items():
            r = run_backtest(conn, lg, train, [test], cls, refit_freq="monthly")
            out.append(r.assign(model=name, league=lg, season=test))
        mk = run_market_backtest(conn, lg, [test], closing=False)
        out.append(mk.assign(model="market", league=lg, season=test))
        print(f"### done {lg} {test}", flush=True)
cols = ["match_id", "league", "season", "match_date", "actual", "model",
        "p_home_win", "p_draw", "p_away_win", "log_loss"]
pd.concat(out)[cols].to_csv("_diag/sot_matches.csv", index=False)
print("saved")
