"""临场档为什么在实盘上比首次存档差：同一批已评分场次上，比较几种赔率来源的 1X2 去水 log loss。

来源：
  first  = 首次存档 market_implied 存下的赔率（赛程表 fixtures，约开球前 24 小时）
  t1     = 临场档 market_implied_t1 存下的赔率（OddsPortal 5 家美国公司中位数，开球前 1.5 小时内）
  avgc   = football-data 收盘平均（match_odds.avgc_*，赛后才有）
  psc    = football-data Pinnacle 收盘（match_odds.psc_*）
都按比例去水，只看 1X2，与存档的模型概率无关。另列各来源的平均抽水（Σ1/odds − 1）。
只读 football.db。用法：PYTHONPATH=. python _diag/near_quality/compare.py
"""
import json
import math
import sqlite3

import numpy as np

conn = sqlite3.connect("file:football.db?mode=ro", uri=True)
rows = conn.execute(
    """select t.match_id, f.extra_markets, t.extra_markets, t.actual_outcome,
              o.avgc_h, o.avgc_d, o.avgc_a, o.psc_h, o.psc_d, o.psc_a
       from predictions t
       join predictions f on f.match_id = t.match_id and f.model_name = 'market_implied'
       left join match_odds o on o.match_id = t.match_id
       where t.model_name = 'market_implied_t1' and t.log_loss is not null
         and f.log_loss is not null""").fetchall()
IDX = {"home_win": 0, "draw": 1, "away_win": 2}


def ll(prices, outcome):
    if prices is None or any(p is None or p != p or p <= 1 for p in prices):
        return None, None
    inv = np.array([1 / p for p in prices])
    q = inv / inv.sum()
    return -math.log(q[IDX[outcome]]), inv.sum() - 1


res = {k: [] for k in ("first", "t1", "avgc", "psc")}
margin = {k: [] for k in res}
seen = set()
for mid, fe, te, out, *close in rows:
    if mid in seen or out not in IDX:
        continue
    seen.add(mid)
    fo, to = json.loads(fe)["odds"], json.loads(te)["odds"]
    src = {"first": (fo["avg_h"], fo["avg_d"], fo["avg_a"]),
           "t1": (to["avg_h"], to["avg_d"], to["avg_a"]),
           "avgc": tuple(close[:3]), "psc": tuple(close[3:])}
    got = {k: ll(v, out) for k, v in src.items()}
    if got["first"][0] is None or got["t1"][0] is None:
        continue
    for k, (v, m) in got.items():
        res[k].append(v)          # 收盘赔率要等 football-data 赛后 CSV，没到时为 None
        margin[k].append(m)


def paired(a, b):
    ok = [(x, y) for x, y in zip(res[a], res[b]) if x is not None and y is not None]
    if len(ok) < 2:
        return f"  {a} − {b}: 样本不足（n={len(ok)}）"
    d = np.array([x - y for x, y in ok])
    return f"  {a} − {b}: {d.mean():+.4f} ± {d.std(ddof=1) / math.sqrt(len(d)):.4f}  (n={len(d)})"


print(f"首次存档与临场档都有 1X2 的已评分场次 n={len(res['first'])}")
for k in res:
    v = [x for x in res[k] if x is not None]
    m = [x for x in margin[k] if x is not None]
    print(f"  {k:5s} n={len(v):3d}" + (f"  LL {np.mean(v):.4f}  平均抽水 {np.mean(m):.4f}" if v else ""))
for a, b in (("t1", "first"), ("avgc", "first"), ("psc", "first"), ("t1", "avgc")):
    print(paired(a, b))
