"""Check: is the small 'market + ratings residual' gain just the favourite-longshot correction that Shin devig
already gives? Compares resid vs Shin on the same matches (ratings_gbm_pred.csv + research.db odds)."""
import sqlite3
import numpy as np
import pandas as pd
from football_prediction.model_market.devig import shin
from football_prediction.validation.backtest import paired_compare

res = pd.read_csv("_diag/explore/ratings_gbm_pred.csv", dtype={"season": str}).dropna(subset=["ll_resid"])
o = pd.read_sql_query("SELECT match_id, avg_h, avg_d, avg_a FROM match_odds", sqlite3.connect("research.db"))
res = res.merge(o, on="match_id")
P = np.array([shin(r) for r in res[["avg_h", "avg_d", "avg_a"]].to_numpy()])
res["ll_shin"] = -np.log(np.clip(P[np.arange(len(P)), res.y.astype(int)], 1e-7, None))
for label, part in (("select 1718-2425", res[res.season != "2526"]), ("holdout 2526", res[res.season == "2526"])):
    print(f"== {label} n={len(part)}")
    for a, b in (("ll_shin", "ll_market"), ("ll_resid", "ll_market"), ("ll_resid", "ll_shin")):
        r = paired_compare(part.rename(columns={a: "log_loss"}), part.rename(columns={b: "log_loss"}))
        print(f"  {a[3:]:>6} - {b[3:]:<7} {r['diff']:+.5f} +- {r['se']:.5f}")
