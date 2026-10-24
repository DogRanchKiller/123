"""xG 版回测（计算）：逐场保存 xG 版各 w 概率，月度重拟合；与 sot_matches.csv 同场次、同切分。"""
import functools
import pandas as pd
from football_prediction.data.loader import init_db
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.validation.backtest import run_backtest

ALL = ["2122", "2223", "2324", "2425", "2526"]
WS = [1.0, 0.7, 0.5, 0.3, 0.0]
conn = init_db("football.db")
out = []
for lg in ["E0", "D1", "SP1"]:
    for test in ["2324", "2425", "2526"]:
        train = ALL[:ALL.index(test)]
        for w in WS:
            cls = functools.partial(XgDixonColesModel, goal_weight=w)
            r = run_backtest(conn, lg, train, [test], cls, refit_freq="monthly")
            out.append(r.assign(model=f"xg_w{w}", league=lg, season=test))
        print(f"### done {lg} {test}", flush=True)
cols = ["match_id", "league", "season", "match_date", "actual", "model",
        "p_home_win", "p_draw", "p_away_win", "log_loss"]
pd.concat(out)[cols].to_csv("_diag/xg_matches.csv", index=False)
print("saved")
