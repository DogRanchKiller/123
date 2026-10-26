"""网站队徽：FotMob 当前赛季联赛赛程页（HTML 的 __NEXT_DATA__，不碰 /api/）取球队 id，
再从 images.fotmob.com 下载 150px 队徽到 web/public/crests/{id}.png，写 web/src/features/match/crests.json
（本库队名 → FotMob 球队 id）。已下载的图片不重下；请求间隔沿用 fotmob.DELAY。

    PYTHONPATH=. python _diag/web_crests.py
"""
import json, os, sqlite3, sys, time

import requests

from football_prediction.data import fotmob
from football_prediction.data.fotmob_parse import LEAGUE_IDS, next_data, team_map

IMG = "https://images.fotmob.com/image_resources/logo/teamlogo/{}_small.png"
OUT_DIR = os.path.join("web", "public", "crests")
MAP_PATH = os.path.join("web", "src", "features", "match", "crests.json")
SEASON = "2627"


def league_teams(league: str) -> dict[str, str]:
    """当前赛季赛程页 → {FotMob 队名: 球队 id}。"""
    lid, slug = LEAGUE_IDS[league]
    nd = next_data(fotmob._get(f"/leagues/{lid}/fixtures/{slug}")) or {}
    ms = ((nd.get("props", {}).get("pageProps", {}).get("fixtures") or {}).get("allMatches")) or []
    return {m[s]["name"]: str(m[s]["id"]) for m in ms for s in ("home", "away")}


def our_teams(conn, league: str) -> list[str]:
    q = "SELECT home_team, away_team FROM {} WHERE league=? AND season=?"
    rows = conn.execute(q.format("matches"), (league, SEASON)).fetchall()
    rows += conn.execute(q.format("fixtures"), (league, SEASON)).fetchall()
    return sorted({n for r in rows for n in r})


def main() -> None:
    conn = sqlite3.connect("file:football.db?mode=ro", uri=True)
    crests, missing = {}, []
    for league in LEAGUE_IDS:
        fm = league_teams(league)
        ours = our_teams(conn, league)
        pairs = team_map(fm, ours)
        for f, o in pairs.items():
            crests[o] = fm[f]
        lost = sorted(set(ours) - set(pairs.values()))
        missing += [(league, n) for n in lost]
        print(league, len(ours), "配上", len(pairs), "未配上", lost, flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    got = 0
    for name, tid in sorted(crests.items()):
        path = os.path.join(OUT_DIR, tid + ".png")
        if os.path.exists(path):
            continue
        time.sleep(fotmob.DELAY)
        try:
            r = requests.get(IMG.format(tid), headers={"User-Agent": fotmob.UA}, timeout=30)
        except requests.RequestException as e:
            print("下载失败", name, tid, type(e).__name__, flush=True)
            continue
        if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
            print("下载失败", name, tid, r.status_code, flush=True)
            continue
        with open(path, "wb") as f:
            f.write(r.content)
        got += 1
    # 只登记已有图片的队，下载失败的队在网站上显示文字标记
    crests = {n: t for n, t in crests.items() if os.path.exists(os.path.join(OUT_DIR, t + ".png"))}
    with open(MAP_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(crests.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("球队", len(crests), "新下载", got, "未配上", missing, flush=True)
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
