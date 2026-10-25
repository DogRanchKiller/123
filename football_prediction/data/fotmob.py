"""
data/fotmob.py  v1.2.0（数据层的一部分）
FotMob 阵容与球员 xG：只抓 HTML 页面（robots.txt 允许），不调用 /api/（robots.txt 禁止），每次请求间隔 ≥3 秒。
  fotmob_matches：FotMob 场次 ↔ match_id、全队 xG；lineups：每次抓取一个批次（预测阵容 / 正式阵容 / 伤停）；
  player_match：赛后球员分钟、xG、xA、npxG；fotmob_shots：逐脚射门（分钟、xG）。
- 表在单独的 fotmob.db（已 gitignore；比赛级明细约 10KB/场，放进每次提交的 football.db 会让仓库迅速变大），
  attach() 挂到 football.db 连接上用。缓存在 _cache/fotmob/（纳入版本库）：match/ 已完赛比赛（永久），
  league/ 已结束赛季赛程，pre/ 每次赛前阵容批次；删掉 fotmob.db 后 --history 加 --reload-pre 可离线重建。
- 只挂到库里已有的 match_id（matches 或 fixtures），不新增比赛行。
- 只补不改：player_match / fotmob_shots INSERT OR IGNORE；lineups 以 (match_id, fetched_at, side, player_id) 为键。
- backfill_xg：understat 拿不到时，用 FotMob 全队 xG 补 match_xg 里缺的场次（us_match_id 记为 "fotmob:{id}"）。
v1.1.0: collect_results：当前赛季联赛赛程页（每联赛 1 页）里的完赛比分 → fotmob_results（判负场次不写）。
v1.2.0: 命令行 --leagues 默认取 fotmob_parse.LEAGUE_IDS 全部联赛（新增六个联赛）。
  football-data 赛果通常晚几天，review 层在 matches 还没有赛果时用它先评分；matches 与模型拟合不受影响。
  match_id 用 loader 同一算法（本库队名 + 日期），日期按 0 / -1 / +1 天依次试，优先取库里已有的 id。
修改此文件后请同步更新 version.py 中 "data_fotmob" 的版本号。
"""
import argparse, gzip, json, os, sqlite3, time
from datetime import date, datetime, timedelta, timezone

import requests

from football_prediction.data.fotmob_parse import (
    LEAGUE_IDS, compact_match, league_matches, next_data, pair_matches, season_param, team_map)
from football_prediction.data.loader import _make_match_id, season_of

LAYER_VERSION = "1.2.0"

BASE = "https://www.fotmob.com"
UA = "Mozilla/5.0 (football-prediction research; low-frequency)"
DELAY = 3.5
CACHE_DIR = os.path.join("_cache", "fotmob")
XG_BACKFILL_DAYS = 4      # 完赛满这么多天、understat 仍没有 xG 的场次才用 FotMob 补

DB_PATH = "fotmob.db"     # 单独的库（已 gitignore，可从 _cache/fotmob 重建），用 attach() 挂到 football.db 连接上

FOTMOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS {s}.fotmob_matches (
    match_id TEXT PRIMARY KEY, fotmob_id TEXT NOT NULL, page_url TEXT,
    home_xg REAL, away_xg REAL,                 -- FotMob 全队 xG（与 understat 不是同一个模型）
    fetched_at TEXT NOT NULL, layer_ver TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {s}.lineups (
    match_id TEXT NOT NULL, fetched_at TEXT NOT NULL,
    lineup_type TEXT,                           -- predicted（赛前预测） / standard（正式公布）
    side TEXT NOT NULL, player_id INTEGER NOT NULL, name TEXT,
    role TEXT NOT NULL,                         -- starter / sub / unavailable
    position_id INTEGER, sub_minute INTEGER, detail TEXT,
    PRIMARY KEY (match_id, fetched_at, side, player_id)
);
CREATE TABLE IF NOT EXISTS {s}.player_match (
    match_id TEXT NOT NULL, player_id INTEGER NOT NULL, side TEXT NOT NULL, name TEXT,
    minutes REAL, xg REAL, xa REAL, npxg REAL,
    PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS {s}.fotmob_shots (
    match_id TEXT NOT NULL, shot_id INTEGER NOT NULL, side TEXT NOT NULL, player_id INTEGER,
    minute INTEGER, xg REAL, own_goal INTEGER, situation TEXT,
    PRIMARY KEY (match_id, shot_id)
);
CREATE TABLE IF NOT EXISTS {s}.fotmob_results (
    match_id TEXT PRIMARY KEY, fotmob_id TEXT NOT NULL,
    home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL,   -- FotMob 完赛比分（不含判负场次）
    fetched_at TEXT NOT NULL, layer_ver TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS {s}.idx_lineups_match ON lineups(match_id, fetched_at);
CREATE INDEX IF NOT EXISTS {s}.idx_player_match_player ON player_match(player_id);
"""

_last_request = [0.0]


def init_fotmob(conn: sqlite3.Connection, schema: str = "main") -> None:
    conn.executescript(FOTMOB_SCHEMA.format(s=schema))
    conn.commit()


def attach(conn: sqlite3.Connection, path: str = DB_PATH) -> sqlite3.Connection:
    """把 FotMob 库挂到 conn（schema 名 fm）并建表；之后表名不加前缀即可读写。"""
    if "fm" not in {r[1] for r in conn.execute("PRAGMA database_list")}:
        conn.execute("ATTACH DATABASE ? AS fm", (path,))
    init_fotmob(conn, "fm")
    return conn


def _get(path: str) -> str:
    """限速 GET 一个 FotMob HTML 页面。"""
    if "/api/" in path:
        raise ValueError("FotMob /api/ 被 robots.txt 禁止")
    wait = DELAY - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        try:
            _last_request[0] = time.monotonic()
            r = requests.get(BASE + path, headers={"User-Agent": UA}, timeout=30)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"FotMob 请求失败: {path}")


def fetch_league(league: str, season: str) -> list[dict]:
    """某联赛某赛季的 FotMob 赛程（league_matches 记录）。"""
    lid, slug = LEAGUE_IDS[league]
    current = season == season_of(date.today().isoformat())
    cache = os.path.join(CACHE_DIR, "league", f"{league}_{season}.json")
    if not current and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    path = f"/leagues/{lid}/fixtures/{slug}"
    if not current:
        path += "?season=" + season_param(season).replace("/", "%2F")
    nd = next_data(_get(path))
    ms = league_matches(nd) if nd else []
    if not current and ms and all(m["finished"] or m["cancelled"] for m in ms):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(ms, f, ensure_ascii=False)
    return ms


def _cache_path(fotmob_id: str) -> str:
    return os.path.join(CACHE_DIR, "match", f"{fotmob_id}.json.gz")


def fetch_match(fotmob_id: str, use_cache: bool = True) -> dict | None:
    """/match/{id} 比赛页 → compact_match 记录；已完赛的写缓存。
    不用赛程里的 /matches/{slug}：去掉 #id 后它返回两队最近一场，不是要的那场。页面 matchId 对不上时丢弃。"""
    path = _cache_path(fotmob_id)
    if use_cache and os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    nd = next_data(_get(f"/match/{fotmob_id}"))
    pp = (nd or {}).get("props", {}).get("pageProps", {})
    if "general" not in pp or str(pp["general"].get("matchId")) != str(fotmob_id):
        return None
    rec = compact_match(pp)
    if rec["finished"]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    return rec


def save_match(conn: sqlite3.Connection, match_id: str, page_url: str, rec: dict,
               fetched_at: str) -> None:
    """写入一场的记录。阵容每次一个批次；赛后数据只在完赛时写。"""
    xg = rec.get("team_xg") or [None, None]
    conn.execute(
        """INSERT INTO fotmob_matches (match_id, fotmob_id, page_url, home_xg, away_xg, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(match_id) DO UPDATE SET
             home_xg=COALESCE(fotmob_matches.home_xg, excluded.home_xg),
             away_xg=COALESCE(fotmob_matches.away_xg, excluded.away_xg)""",
        (match_id, rec["fotmob_id"], page_url, xg[0], xg[1], fetched_at, LAYER_VERSION))
    conn.executemany(
        """INSERT OR IGNORE INTO lineups (match_id, fetched_at, lineup_type, side, player_id, name,
           role, position_id, sub_minute, detail) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(match_id, fetched_at, rec.get("lineup_type"), p["side"], p["player_id"], p["name"],
          p["role"], p["position_id"], p["sub_minute"], p["detail"])
         for p in rec["lineup"] if p.get("player_id") is not None])
    if rec["finished"]:
        conn.executemany(
            """INSERT OR IGNORE INTO player_match (match_id, player_id, side, name, minutes, xg, xa, npxg)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(match_id, p["player_id"], p["side"], p["name"], p["minutes"], p["xg"], p["xa"], p["npxg"])
             for p in rec["players"] if p.get("player_id") is not None])
        conn.executemany(
            """INSERT OR IGNORE INTO fotmob_shots (match_id, shot_id, side, player_id, minute, xg,
               own_goal, situation) VALUES (?,?,?,?,?,?,?,?)""",
            [(match_id, s["shot_id"], s["side"], s["player_id"], s["minute"], s["xg"],
              s["own_goal"], s["situation"]) for s in rec["shots"] if s.get("shot_id") is not None])
    conn.commit()


def _our_rows(conn: sqlite3.Connection, league: str, season: str) -> list[dict]:
    q = """SELECT match_id, match_date, home_team, away_team FROM {t} WHERE league=? AND season=?"""
    rows = conn.execute(q.format(t="matches"), (league, season)).fetchall()
    try:
        rows += conn.execute(q.format(t="fixtures"), (league, season)).fetchall()
    except sqlite3.OperationalError:
        pass
    seen, out = set(), []
    for mid, d, h, a in rows:
        if mid not in seen:
            seen.add(mid)
            out.append({"match_id": mid, "match_date": d, "home_team": h, "away_team": a})
    return out


def collect_history(conn: sqlite3.Connection, league: str, season: str,
                    limit: int | None = None, log=print) -> tuple[int, int]:
    """抓某联赛某赛季的已完赛场次（先读缓存），返回（新写入场数, 未配对场数）。"""
    fm = [m for m in fetch_league(league, season) if m["finished"] and not m["cancelled"]]
    paired = pair_matches(fm, _our_rows(conn, league, season))
    done = {r[0] for r in conn.execute("SELECT DISTINCT match_id FROM player_match")}
    todo = [m for m in fm if m["fotmob_id"] in paired and paired[m["fotmob_id"]]["match_id"] not in done]
    if limit is not None:
        todo = todo[:limit]
    new = failed = 0
    for i, m in enumerate(todo, 1):
        try:
            rec = fetch_match(m["fotmob_id"])
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"  {m['fotmob_id']} 抓取失败：{e}")
            continue
        if rec and rec["finished"]:
            save_match(conn, paired[m["fotmob_id"]]["match_id"], m["page_url"], rec,
                       datetime.now(timezone.utc).isoformat())
            new += 1
        if i % 50 == 0:
            log(f"  {league} {season}: {i}/{len(todo)}")
    if failed:
        log(f"  {league} {season}：{failed} 场失败，下次重跑会补")
    return new, len(fm) - len(paired)


def collect_upcoming(conn: sqlite3.Connection, now: datetime, hours: float,
                     log=print) -> list[tuple[str, str]]:
    """抓 hours 小时内开球场次的当前阵容（predicted 或 standard），返回 [(match_id, lineup_type)]。"""
    hi = (now + timedelta(hours=hours)).isoformat()
    fx = conn.execute(
        "SELECT match_id, league, season FROM fixtures WHERE kickoff_utc > ? AND kickoff_utc <= ?",
        (now.isoformat(), hi)).fetchall()
    out = []
    for league in sorted({r[1] for r in fx if r[1] in LEAGUE_IDS}):
        want = {r[0] for r in fx if r[1] == league}
        season = next(r[2] for r in fx if r[1] == league)
        try:
            fm = fetch_league(league, season)
        except Exception as e:  # noqa: BLE001  一个联赛失败不影响其他联赛
            log(f"  FotMob {league} 赛程页失败：{e}")
            continue
        paired = pair_matches(fm, _our_rows(conn, league, season))
        stamp = now.isoformat()
        for m in fm:
            row = paired.get(m["fotmob_id"])
            if not row or row["match_id"] not in want:
                continue
            try:
                rec = fetch_match(m["fotmob_id"], use_cache=False)
            except Exception as e:  # noqa: BLE001
                log(f"  FotMob {row['match_id']} 比赛页失败：{e}")
                continue
            if rec and rec["lineup"]:
                save_match(conn, row["match_id"], m["page_url"], rec, stamp)
                _save_pre(rec, row["match_id"], m["page_url"], stamp)
                out.append((row["match_id"], rec["lineup_type"]))
    return out


def _team_names(conn: sqlite3.Connection, league: str, season: str) -> list[str]:
    """本库队名：本赛季与上赛季 matches + 当前 fixtures（赛季初 matches 里还没有升班马）。"""
    prev = f"{(int(season[:2]) - 1) % 100:02d}{season[:2]}"
    q = "SELECT home_team, away_team FROM {t} WHERE league=? AND season IN (?, ?)"
    rows = conn.execute(q.format(t="matches"), (league, season, prev)).fetchall()
    try:
        rows += conn.execute(q.format(t="fixtures"), (league, season, prev)).fetchall()
    except sqlite3.OperationalError:
        pass
    return sorted({n for r in rows for n in r})


def _known_ids(conn: sqlite3.Connection) -> set[str]:
    ids = set()
    for t in ("matches", "fixtures", "predictions"):
        try:
            ids |= {r[0] for r in conn.execute(f"SELECT DISTINCT match_id FROM {t}")}
        except sqlite3.OperationalError:
            pass
    return ids


def collect_results(conn: sqlite3.Connection, leagues, season: str, log=print, fetch=None) -> int:
    """当前赛季各联赛赛程页的完赛比分 → fotmob_results（只补不改），返回新写入场数。一个联赛失败不影响其他。"""
    fetch = fetch or fetch_league
    known, stamp, new = _known_ids(conn), datetime.now(timezone.utc).isoformat(), 0
    for lg in leagues:
        if lg not in LEAGUE_IDS:
            continue
        try:
            fm = [m for m in fetch(lg, season)
                  if m.get("score") and not m["awarded"] and not m["cancelled"] and m.get("kickoff_utc")]
        except Exception as e:  # noqa: BLE001
            log(f"  FotMob {lg} 赛果页失败：{e}")
            continue
        tm = team_map([n for m in fm for n in (m["home"], m["away"])], _team_names(conn, lg, season))
        rows = []
        for m in fm:
            home, away = tm.get(m["home"]), tm.get(m["away"])
            if not home or not away:
                continue
            d0 = date.fromisoformat(m["kickoff_utc"][:10])
            ids = [_make_match_id(lg, season, (d0 + timedelta(days=k)).isoformat(), home, away)
                   for k in (0, -1, 1)]
            mid = next((i for i in ids if i in known), ids[0])
            rows.append((mid, m["fotmob_id"], *m["score"], stamp, LAYER_VERSION))
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO fotmob_results VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        new += conn.total_changes - before
    return new


def _save_pre(rec: dict, match_id: str, page_url: str, stamp: str) -> None:
    """赛前阵容也落一份缓存（fotmob.db 不进版本库，靠缓存重建）。"""
    d = os.path.join(CACHE_DIR, "pre")
    os.makedirs(d, exist_ok=True)
    name = f"{rec['fotmob_id']}_{stamp[:19].replace(':', '').replace('-', '')}.json.gz"
    with gzip.open(os.path.join(d, name), "wt", encoding="utf-8") as f:
        json.dump({"match_id": match_id, "page_url": page_url, "fetched_at": stamp, "rec": rec},
                  f, ensure_ascii=False)


def reload_pre(conn: sqlite3.Connection) -> int:
    """从 _cache/fotmob/pre 重放赛前阵容批次（重建 fotmob.db 用）；返回文件数。"""
    d = os.path.join(CACHE_DIR, "pre")
    n = 0
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with gzip.open(os.path.join(d, name), "rt", encoding="utf-8") as f:
            x = json.load(f)
        save_match(conn, x["match_id"], x["page_url"], x["rec"], x["fetched_at"])
        n += 1
    return n


def backfill_xg(conn: sqlite3.Connection, today: date) -> int:
    """完赛满 XG_BACKFILL_DAYS 天、match_xg 仍没有的场次，用 FotMob 全队 xG 补上；返回补入场数。"""
    cutoff = (today - timedelta(days=XG_BACKFILL_DAYS)).isoformat()
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO match_xg (match_id, home_xg, away_xg, us_match_id, fetched_at, layer_ver)
           SELECT f.match_id, f.home_xg, f.away_xg, 'fotmob:' || f.fotmob_id, ?, ?
           FROM fotmob_matches f JOIN matches m ON m.match_id = f.match_id
           WHERE f.home_xg IS NOT NULL AND f.away_xg IS NOT NULL AND m.match_date <= ?
             AND f.match_id NOT IN (SELECT match_id FROM match_xg)""",
        (datetime.now(timezone.utc).isoformat(), LAYER_VERSION, cutoff))
    conn.commit()
    return conn.total_changes - before


def main() -> None:
    ap = argparse.ArgumentParser(description="FotMob 阵容 / 球员 xG（默认：补抓当前赛季已完赛场次）")
    ap.add_argument("--db", default="football.db")
    ap.add_argument("--fotmob-db", default=DB_PATH)
    ap.add_argument("--reload-pre", action="store_true", help="从缓存重放赛前阵容（重建 fotmob.db 后用）")
    ap.add_argument("--leagues", default=",".join(LEAGUE_IDS))
    ap.add_argument("--history", default="", help="赛季，如 2324,2425,2526")
    ap.add_argument("--upcoming", type=float, default=0, help="抓未来 N 小时内开球场次的阵容")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    from football_prediction.data.loader import init_db
    conn = attach(init_db(args.db), args.fotmob_db)
    leagues = args.leagues.split(",")
    seasons = [s for s in args.history.split(",") if s] or [season_of(date.today().isoformat())]
    if args.reload_pre:
        print(f"重放赛前阵容 {reload_pre(conn)} 批")
    elif not args.upcoming:
        for s in seasons:
            for lg in leagues:
                new, miss = collect_history(conn, lg, s, args.limit)
                print(f"{lg} {s}：新写入 {new} 场，未配对 {miss} 场", flush=True)
        print(f"FotMob 补入 match_xg：{backfill_xg(conn, date.today())} 场")
    else:
        got = collect_upcoming(conn, datetime.now(timezone.utc), args.upcoming)
        print(f"抓到阵容 {len(got)} 场", got)
    conn.close()


if __name__ == "__main__":
    main()
