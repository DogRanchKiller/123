"""诊断第 1 步（计算）：逐场保存 DC 月度 v1.3.0 与市场赛前概率，供 gap_analyze.py 拆解。
测试赛季 2425 与 2526 各跑一遍（训练集=测试赛季之前的全部赛季），两季结论一致才可信。
"""
import pandas as pd
from football_prediction.data.loader import init_db
from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.validation.backtest import run_backtest, run_market_backtest

ALL = ["2122", "2223", "2324", "2425", "2526"]
conn = init_db("football.db")
out = []
for lg in ["E0", "D1", "SP1"]:
    for test in ["2425", "2526"]:
        train = ALL[:ALL.index(test)]
        dc = run_backtest(conn, lg, train, [test], DixonColesModel, refit_freq="monthly")
        mk = run_market_backtest(conn, lg, [test], closing=False)
        m = dc.merge(mk[["match_id", "p_home_win", "p_draw", "p_away_win", "log_loss"]],
                     on="match_id", suffixes=("_dc", "_mk"))
        m["league"], m["season"] = lg, test
        out.append(m)
pd.concat(out).to_csv("_diag/gap_matches.csv", index=False)
print("saved", sum(len(x) for x in out))
