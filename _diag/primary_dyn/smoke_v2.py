"""冒烟（2.0.0 主模型 dc_dyn）：在 football.db 的内存副本上跑存档、报告、快照、读存档与替换检查。
不写真实库，不写 reports/；快照写到临时目录。用法：PYTHONPATH=. python _diag/primary_dyn/smoke_v2.py"""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone

from football_prediction import version
from football_prediction.review.scorecard import promotion_check
from football_prediction.services import live_round, match_read
from football_prediction.services.match_analysis import ModelCache, analyse_upcoming, build_report


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


before_md5 = md5("football.db")
src = sqlite3.connect("file:football.db?mode=ro", uri=True)
conn = sqlite3.connect(":memory:")
src.backup(conn)
src.close()
conn.row_factory = sqlite3.Row

now = datetime.now(timezone.utc)
t0 = time.time()
cache = ModelCache(conn, now.date().isoformat())
n = live_round.predict_upcoming(conn, now, cache, log=lambda *a: None)
print(f"[存档] 新存 {n} 行，用时 {time.time() - t0:.0f}s")
dyn = conn.execute("""SELECT match_id, extra_markets FROM predictions
                      WHERE model_name = 'dc_dyn' AND generated_at >= ?""", (now.isoformat()[:19],)).fetchall()
with_odds = sum(1 for r in dyn if any(v is not None for v in (json.loads(r[1]).get("odds") or {}).values()))
print(f"  本次 dc_dyn 行 {len(dyn)}，其中 extra.odds 有赔率 {with_odds}")

t0 = time.time()
analysed = analyse_upcoming(conn, live_round.LEAGUES, now, cache)
rep = build_report(conn, live_round.LEAGUES, now, analysed=analysed)
views = [live_round.match_view(r, a, s) for r, a, s in analysed]
print(f"[报告] {len(rep)} 行，用时 {time.time() - t0:.0f}s")
if len(rep):
    print(rep[["主队", "客队", "概率来源", "比分来源", "主胜", "市场 主/平/客", "信心", "亚盘信心", "重点"]].head(10).to_string())
bad = [v["match_id"] for v in views if v["model_name"] != version.PRIMARY_MODEL[0]
       or abs(sum(v["probabilities"]) - 1) > 1e-3
       or (v["market_probabilities"] is not None and abs(sum(v["market_probabilities"]) - 1) > 1e-3)]
print(f"[快照] {len(views)} 场；不合格 {bad}；有市场对照 {sum(v['market_probabilities'] is not None for v in views)}；"
      f"重点 {sum(v['recommended'] for v in views)}；亚盘档 {sorted({v['asian']['tier'] for v in views})}")

with tempfile.TemporaryDirectory() as d:
    snap = os.path.join(d, "latest_round.json")
    live_round.write_snapshot(snap, now, views, [])
    for v in views[:3]:
        m = match_read.read_match(conn, v["match_id"], snap)
        a = m["archived"]
        print(f"[读存档] {v['home']} vs {v['away']}：current {m['current']['model_name']}，"
              f"archived {a and a['model_name']} 档 {a and a['confidence']} 亚盘 {a and a['asian'] and a['asian']['tier']}")
    recent = match_read.read_recent(conn, now, 3)
    names = {}
    for r in recent:
        k = r["archived"]["model_name"]
        names[k] = names.get(k, 0) + 1
    print(f"[最近已开球] {len(recent)} 场，首次存档来源 {names}")

pc = promotion_check(conn, (version.PRIMARY_MODEL[0], version.get(version.PRIMARY_MODEL[1])), version.PROMOTE_MIN_N)
print("[替换检查]")
print(pc.to_string() if pc is not None and not pc.empty else "  （无）")
conn.close()
print(f"[真实库] md5 不变：{md5('football.db') == before_md5}")
