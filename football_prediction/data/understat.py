"""
data/understat.py  v1.8.0（数据层的一部分）
v1.5.0: 联赛映射新增意甲 I1 / 法甲 F1（研究库扩样本用）。
v1.6.0: 本文件未改；实盘加入 I1 / F1，每次运行刷新它们当前赛季的 xG。
v1.7.0: 导出 US_LEAGUES（understat 覆盖的联赛）。英冠等六个新联赛 understat 没有，xG 只靠 FotMob 补。
v1.8.0: 本文件未改（数据层 oddsportal 改 fetched_at）。
从 understat.com 下载每场 xG，按"联赛 + 日期±1天 + 主客队"对齐到 matches 表，写入 match_xg 表。
- 两个数据源队名写法不同（如 "Wolverhampton Wanderers" / "Wolves"），
  用"同联赛、日期±1天、比分相同"的场次投票自动建立队名映射，无需手工维护。
- 已结束赛季的原始 JSON 缓存在 _cache/understat/，重跑不重复下载；当前赛季每次重新下载。
- 只 INSERT OR IGNORE，已入库的 xG 不覆盖。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import json, os, sqlite3, time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta

import requests

from football_prediction.data.loader import season_of   # match_xg 表结构在 loader.DB_SCHEMA

LAYER_VERSION = "1.8.0"

_US_URL   = "https://understat.com/getLeagueData/{name}/{year}"
_US_NAMES = {"E0": "EPL", "D1": "Bundesliga", "SP1": "La_liga", "I1": "Serie_A", "F1": "Ligue_1"}
US_LEAGUES = frozenset(_US_NAMES)
CACHE_DIR = os.path.join("_cache", "understat")


def _fetch(league: str, season: str) -> list[dict]:
    """下载（或读缓存）某联赛某赛季的 understat 场次列表。"""
    name = _US_NAMES[league]
    year = 2000 + int(season[:2])
    path = os.path.join(CACHE_DIR, f"{league}_{season}.json")
    current = season == season_of(date.today().isoformat())
    if not current and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://understat.com/league/{name}/{year}",
    }
    url = _US_URL.format(name=name, year=year)
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            break
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    dates = resp.json()["dates"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dates, f, ensure_ascii=False)
    return dates


def _team_map(us_rows: list[dict], fd_rows: list[tuple]) -> dict[str, str]:
    """同日期±1天且比分相同的场次互相投票，得到 understat 队名 -> matches 队名。"""
    by_day = defaultdict(list)
    for _, d, h, a, hg, ag in fd_rows:
        by_day[d].append((h, a, hg, ag))
    votes = defaultdict(Counter)
    for m in us_rows:
        d0 = date.fromisoformat(m["datetime"][:10])
        hg, ag = int(m["goals"]["h"]), int(m["goals"]["a"])
        for off in (-1, 0, 1):
            for h, a, fhg, fag in by_day.get((d0 + timedelta(days=off)).isoformat(), []):
                if (fhg, fag) == (hg, ag):
                    votes[m["h"]["title"]][h] += 1
                    votes[m["a"]["title"]][a] += 1
    mapping = {t: c.most_common(1)[0][0] for t, c in votes.items()}
    dup = [v for v, n in Counter(mapping.values()).items() if n > 1]
    if dup:
        raise ValueError(f"understat 队名映射冲突: {dup}")
    return mapping


def load_xg(conn: sqlite3.Connection, league: str, season: str) -> tuple[int, int]:
    """下载并写入某联赛某赛季已完赛场次的 xG，返回（新写入场数, 未对齐场数）。"""
    us_rows = [m for m in _fetch(league, season) if m.get("isResult")]
    fd_rows = conn.execute(
        """SELECT match_id, match_date, home_team, away_team, home_goals, away_goals
           FROM matches WHERE league=? AND season=? AND home_goals IS NOT NULL""",
        (league, season),
    ).fetchall()
    if not us_rows or not fd_rows:
        return 0, len(us_rows)

    mapping = _team_map(us_rows, fd_rows)
    fd_idx = {(h, a): (mid, d) for mid, d, h, a, _, _ in fd_rows}
    now = datetime.now(timezone.utc).isoformat()
    rows, unmatched = [], 0
    for m in us_rows:
        key = (mapping.get(m["h"]["title"]), mapping.get(m["a"]["title"]))
        hit = fd_idx.get(key)
        # 同赛季主客组合唯一；日期相差超过 3 天视为对齐错误
        if not hit or abs((date.fromisoformat(hit[1])
                           - date.fromisoformat(m["datetime"][:10])).days) > 3:
            unmatched += 1
            continue
        rows.append((hit[0], float(m["xG"]["h"]), float(m["xG"]["a"]),
                     m["id"], now, LAYER_VERSION))

    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO match_xg
           (match_id, home_xg, away_xg, us_match_id, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?)""", rows)
    conn.commit()
    return conn.total_changes - before, unmatched
