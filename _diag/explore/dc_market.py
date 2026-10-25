"""dc_market（进球与历史赔率反推 λ 的混合强度）对 dc_xg 的样本外比较，research.db，一个联赛一个进程。
测试赛季 1718..2526，按月重拟合；w 在 1718–2425 上选，2526 留出确认。
dc_xg 与市场的逐场概率读 _diag/expand/probs_{lg}.csv（同一套回测产物），按 match_id 配对。
用法：PYTHONPATH=. python -u _diag/explore/dc_market.py E0  -> _diag/explore/dc_market_E0.csv
"""
import contextlib
import io
import sys
from functools import partial

import pandas as pd

from football_prediction.data.loader import init_db
from football_prediction.model_dc.market_dc import MarketDixonColesModel
from football_prediction.validation.backtest import run_backtest

ALL = [f"{y:02d}{y + 1:02d}" for y in range(14, 26)]
TESTS = ALL[3:]
WEIGHTS = (0.0, 0.3, 0.6)

lg = sys.argv[1]
conn = init_db("research.db")
base = pd.read_csv(f"_diag/expand/probs_{lg}.csv", dtype={"season": str})
out = []
for test in TESTS:
    train = ALL[:ALL.index(test)]
    m = base[base["season"] == test][["match_id", "league", "season", "log_loss_xg", "log_loss_mk"]]
    for w in WEIGHTS:
        with contextlib.redirect_stdout(io.StringIO()):
            r = run_backtest(conn, lg, train, [test], partial(MarketDixonColesModel, goal_weight=w),
                             refit_freq="monthly")
        m = m.merge(r[["match_id", "log_loss"]].rename(columns={"log_loss": f"ll_w{w}"}),
                    on="match_id")
    out.append(m)
    print(f"{lg} {test}: n={len(m)} xg={m['log_loss_xg'].mean():.4f} mk={m['log_loss_mk'].mean():.4f} "
          + " ".join(f"w{w}={m[f'll_w{w}'].mean():.4f}" for w in WEIGHTS), flush=True)
pd.concat(out).to_csv(f"_diag/explore/dc_market_{lg}.csv", index=False)
