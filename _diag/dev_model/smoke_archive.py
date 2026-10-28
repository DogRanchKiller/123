"""冒烟：在 football.db 的内存副本上跑 predict_upcoming，看动态 DC 两版是否每场多存两行。不写真实库。"""
import sqlite3
import time
from datetime import datetime, timezone

from football_prediction.services import live_round

src = sqlite3.connect("file:football.db?mode=ro", uri=True)
conn = sqlite3.connect(":memory:")
src.backup(conn)
src.close()
conn.row_factory = sqlite3.Row

now = datetime.now(timezone.utc)
before = dict(conn.execute("SELECT model_name, COUNT(*) FROM predictions GROUP BY model_name").fetchall())
t0 = time.time()
n = live_round.predict_upcoming(conn, now, log=lambda *a: None)
after = dict(conn.execute("SELECT model_name, COUNT(*) FROM predictions GROUP BY model_name").fetchall())
print(f"新存 {n} 行，用时 {time.time() - t0:.0f}s")
for k in sorted(set(before) | set(after)):
    if after.get(k, 0) != before.get(k, 0):
        print(f"  {k}: +{after.get(k, 0) - before.get(k, 0)}")
conn.row_factory = sqlite3.Row
rows = conn.execute("""SELECT p.model_name, p.model_ver, p.p_home_win, p.p_draw, p.p_away_win, p.extra_markets, f.home_team, f.away_team
                       FROM predictions p JOIN fixtures f ON p.match_id = f.match_id
                       WHERE p.model_name IN ('dc_dyn', 'dc_dyn_shots', 'dc_market', 'market_implied')
                       ORDER BY p.match_id, p.model_name LIMIT 12""").fetchall()
for r in rows:
    print(f"  {r['home_team']} vs {r['away_team']}  {r['model_name']} {r['model_ver']}  "
          f"{r['p_home_win']:.3f}/{r['p_draw']:.3f}/{r['p_away_win']:.3f}  extra {len(r['extra_markets'] or '')}B")
