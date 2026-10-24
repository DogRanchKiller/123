"""今日首发 vs 近期主力：读 understat 缓存，列出两队本赛季出场分钟 / 每90(xG+xA)，
标出今日先发、替补、不在大名单的人。用法：python today_lineup.py <espn_summary.json> [主队 客队]"""
import json, os, sqlite3, sys, unicodedata
import pandas as pd


def norm(s):
    s = s.lower().replace("ø", "o").replace("ł", "l").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = "".join(ch for ch in s if ch.isalpha())
    return s.replace("vitalii", "vitaliy")   # understat / ESPN 拼写差异


espn = json.load(open(sys.argv[1], encoding="utf-8"))
today = {}
for r in espn["rosters"]:
    for p in r["roster"]:
        today[norm(p["athlete"]["displayName"])] = "先发" if p.get("starter") else "替补"

conn = sqlite3.connect("football.db")
for team in (sys.argv[2:4] if len(sys.argv) >= 4 else ["Arsenal", "Everton"]):
    m = pd.read_sql_query(
        """SELECT m.match_date, m.home_team, m.away_team, x.us_match_id FROM matches m
           JOIN match_xg x USING(match_id) WHERE m.league='E0' AND m.season='2627'
           AND (m.home_team=? OR m.away_team=?) ORDER BY m.match_date""", conn, params=(team, team))
    agg, last = {}, {}
    n = 0
    for r in m.itertuples():
        p = f"_cache/understat/matches/{r.us_match_id}.json"
        if not os.path.exists(p):
            continue
        n += 1
        side = "h" if r.home_team == team else "a"
        for q in json.load(open(p, encoding="utf-8"))[side].values():
            a = agg.setdefault(q["player"], [0, 0, 0.0])
            a[0] += int(q["time"]); a[1] += q["position"] != "Sub"; a[2] += float(q["xG"]) + float(q["xA"])
            last[q["player"]] = (r.match_date, q["position"])
    rows = []
    for name, (mins, starts, xa) in agg.items():
        k = norm(name)
        st = today.get(k) or next((v for t, v in today.items() if k in t or t in k), "不在大名单")
        rows.append((name, starts, mins, round(xa / mins * 90, 2) if mins else 0, round(xa, 2), st, last[name][0]))
    df = pd.DataFrame(rows, columns=["球员", "先发", "分钟", "每90xG+xA", "xG+xA", "今日", "最近出场"])
    df = df.sort_values("分钟", ascending=False)
    print(f"\n===== {team}  本赛季联赛（缓存 {n} 场）=====")
    print(df[df["分钟"] >= 90].to_string(index=False))
