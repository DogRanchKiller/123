"""方向 D 上限测试：假设开赛前已知首发（实盘需在官方首发公布后、开球前约 1 小时预测）。
每队每场赛前、只用此前的联赛场次，按时间衰减（xi=0.005）累计每名球员的出场分钟与 xG+xA：
  att_delta = 今日首发的场均(xG+xA)率之和 − 该队按衰减分钟数排前 11 人的同一指标（阵容削弱/轮换）
  cont      = 今日首发的衰减分钟数之和 / 前 11 人的衰减分钟数之和（主力出勤度）
球员率做收缩：(xGxA + 5·0.2) / (分钟/90 + 5)。新球员取先验 0.2。
特征取主−客差，接到校准层（E8 = 模型概率 + 休息差）之后比较。仅 E0。"""
import json, os, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd

XI, PRIOR_RATE, PRIOR_N = 0.005, 0.2, 5.0


def build(lg="E0"):
    conn = sqlite3.connect("football.db")
    m = pd.read_sql_query(
        """SELECT m.match_id, m.match_date, m.home_team, m.away_team, x.us_match_id
           FROM matches m JOIN match_xg x USING(match_id) WHERE m.league = ?
           ORDER BY m.match_date""", conn, params=(lg,))
    m["day"] = (pd.to_datetime(m.match_date) - pd.Timestamp("2000-01-01")).dt.days
    state = defaultdict(dict)   # team -> player -> [dec_min, dec_xgxa, last_day]
    out = []
    for r in m.itertuples():
        p = f"_cache/understat/matches/{r.us_match_id}.json"
        if not os.path.exists(p):
            continue
        ro = json.load(open(p, encoding="utf-8"))
        feats = {"match_id": r.match_id}
        for side, team in [("h", r.home_team), ("a", r.away_team)]:
            st = state[team]
            cur = {pid: (v[0] * np.exp(-XI * (r.day - v[2])), v[1] * np.exp(-XI * (r.day - v[2])))
                   for pid, v in st.items()}
            rate = {pid: (x + PRIOR_N * PRIOR_RATE) / (mi / 90 + PRIOR_N) for pid, (mi, x) in cur.items()}
            starters = [q["player_id"] for q in ro[side].values() if q["position"] != "Sub"]
            top = sorted(cur, key=lambda k: -cur[k][0])[:11]
            have_hist = sum(v[0] for v in cur.values()) > 0
            feats[f"att_{side}"] = (sum(rate.get(s, PRIOR_RATE) for s in starters)
                                    - sum(rate[k] for k in top) - PRIOR_RATE * (11 - len(top))) if have_hist else 0.0
            tm = sum(cur[k][0] for k in top)
            feats[f"cont_{side}"] = (sum(cur[s][0] for s in starters if s in cur) / tm) if tm > 0 else 1.0
        out.append(feats)
        for side, team in [("h", r.home_team), ("a", r.away_team)]:
            st = state[team]
            for q in ro[side].values():
                pid, mins = q["player_id"], float(q["time"])
                v = st.get(pid, [0.0, 0.0, r.day])
                d = np.exp(-XI * (r.day - v[2]))
                st[pid] = [v[0] * d + mins, v[1] * d + float(q["xG"]) + float(q["xA"]), r.day]
    return pd.DataFrame(out)


if __name__ == "__main__":
    f = build()
    f.to_csv("_diag/explore/lineup_E0.csv", index=False)
    print(len(f)); print(f.describe().round(3).to_string())
