"""
_diag/ou_lines/probe.py  探测 OddsPortal（本机只能看到美国几家）开了哪些大小球线，有没有 .25 / .75。
只读 football.db（mode=ro），不写库；取最近未开球的 N 场（默认 2 场，不同联赛优先），
用 OddsHarvester 的 over_under 总括 token 让它按页面发现全部大小球线。原始输出存 probe_raw.json（gitignore）。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/ou_lines/probe.py [N] [联赛,…] > _diag/ou_lines/result_2.txt
"""
import json
import pathlib
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from football_prediction.data.oddsportal import _with_retry, run_harvester
from football_prediction.data.oddsportal_parse import LEAGUE_SLUGS, market_of, match_links, parse_record

HERE = pathlib.Path(__file__).parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 2

conn = sqlite3.connect(pathlib.Path("football.db").resolve().as_uri() + "?mode=ro", uri=True)
now = datetime.now(timezone.utc)
cols = ["match_id", "league", "match_date", "kickoff_utc", "home_team", "away_team", "ah_line"]
fx = [dict(zip(cols, r)) for r in conn.execute(
    f"SELECT {','.join(cols)} FROM fixtures WHERE kickoff_utc >= ? ORDER BY kickoff_utc",
    ((now + timedelta(hours=1)).isoformat(),))]
ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None   # 可选：只看这些联赛，如 E0,SP1
fx = [f for f in fx if f["league"] in LEAGUE_SLUGS and (ONLY is None or f["league"] in ONLY)]
pick, seen = [], set()
for f in fx:                                    # 先每个联赛一场，再按时间补足
    if f["league"] not in seen and len(pick) < N:
        pick.append(f)
        seen.add(f["league"])
for f in fx:
    if len(pick) >= N:
        break
    if f not in pick:
        pick.append(f)
print("探测时间（UTC）", now.isoformat(timespec="minutes"))
for f in pick:
    print("  ", f["league"], f["kickoff_utc"], f["home_team"], "vs", f["away_team"])

links = []
for slug in sorted({LEAGUE_SLUGS[f["league"]] for f in pick}):   # 同实盘：失败停 30 秒重试一次
    got = _with_retry(run_harvester, ["-l", slug, "--links-only", "-c", "1"], 300, print)
    print(f"  {slug}：{len(got)} 条链接")
    links += got
paired = match_links(links, pick)
print("配对到", len(paired), "场")
args = ["-m", "over_under", "-c", "1", "--request-delay", "2"]
for ln in paired:
    args += ["--match-link", ln]
if not paired:
    sys.exit("没有配对到比赛，不抓")
recs = _with_retry(run_harvester, args, 240 * len(paired) + 120, print)
(HERE / "probe_raw.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

for rec in recs:
    fxr = paired.get(rec.get("match_link"), {})
    print(f"\n{fxr.get('league')} {rec.get('home_team')} vs {rec.get('away_team')}")
    books = defaultdict(list)                   # 线 -> [(公司, 大, 小)]
    for b, mk, line, o1, o2, *_ in parse_record(rec):
        if mk == "ou":
            books[line].append((b, o1, o2))
    if not books:
        print("  没有大小球市场；记录里的键：", sorted(k for k in rec if k.endswith("_market")))
    for line in sorted(books):
        q = "四分之一线" if (line * 4) % 2 == 1 else ("整数线" if line == int(line) else "半球线")
        rows = "，".join(f"{b} {o1}/{o2}" for b, o1, o2 in sorted(books[line], key=lambda x: str(x[0])))
        print(f"  {line:<5} {q:<5} {len(books[line])} 家：{rows}")
    other = sorted(k for k in rec if k.endswith("_market") and not market_of(k))
    if other:
        print("  解析不了的市场键：", other)
