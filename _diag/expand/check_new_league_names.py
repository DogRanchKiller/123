"""核对 I1/F1 在 FotMob 的联赛 id 与队名配对（只读 football.db，不写库）。
    PYTHONPATH=. python _diag/expand/check_new_league_names.py
"""
import sqlite3

from football_prediction.data import fotmob
from football_prediction.data.fotmob_parse import LEAGUE_IDS, fm_sim

conn = sqlite3.connect("football.db")
for lg in ("I1", "F1"):
    ours = sorted({t for (t,) in conn.execute(
        "SELECT home_team FROM matches WHERE league=? AND season='2627' "
        "UNION SELECT home_team FROM fixtures WHERE league=?", (lg, lg))})
    ms = fotmob.fetch_league(lg, "2627")
    theirs = sorted({m["home"] for m in ms} | {m["away"] for m in ms})
    print(f"\n{lg} {LEAGUE_IDS[lg]}：FotMob {len(ms)} 场，{len(theirs)} 队；本库 {len(ours)} 队")
    for t in theirs:
        best = max(ours, key=lambda o: fm_sim(t, o))
        s = fm_sim(t, best)
        print(f"  {'  ' if s >= 0.9 else '✗ '}{t:<28} -> {best:<18} {s:.2f}")
