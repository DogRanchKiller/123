"""
data/loader.py  v1.2.0
数据层：下载 football-data.co.uk CSV，写入 SQLite，标准化球队 ID。
v1.1.0: 保存赛前/收盘平均赔率（match_odds 表，作市场基准）；
        下载未开赛赛程 fixtures.csv（fixtures 表，供实盘预测）；CSV 按 utf-8-sig 解码。
v1.2.0: 保存射门/射正（match_stats 表），供射正版实力估计。
v1.3.0: 新增 match_xg 表结构（数据由 data/understat.py 下载对齐写入）。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import sqlite3, hashlib, requests, io, time
import pandas as pd
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

LAYER_VERSION = "1.3.0"

# football-data.co.uk 赛季 URL 模板（www 会 302 到裸域名，直接用裸域名少一次握手）
_CSV_URL      = "https://football-data.co.uk/mmz4281/{season}/{league}.csv"
_FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"
_UK_TZ = ZoneInfo("Europe/London")   # football-data 的开球时间为英国本地时间

# 赔率列：CSV 列名 -> match_odds 列名（Avg = 多家公司平均，C = 收盘）
_ODDS_COLS = {
    "AvgH": "avg_h",   "AvgD": "avg_d",   "AvgA": "avg_a",
    "AvgCH": "avgc_h", "AvgCD": "avgc_d", "AvgCA": "avgc_a",
    "B365H": "b365_h", "B365D": "b365_d", "B365A": "b365_a",
    "Avg>2.5": "avg_over25",   "Avg<2.5": "avg_under25",
    "AvgC>2.5": "avgc_over25", "AvgC<2.5": "avgc_under25",
}

# 技术统计列：CSV 列名 -> match_stats 列名
_STATS_COLS = {
    "HS": "home_shots", "AS": "away_shots",
    "HST": "home_sot",  "AST": "away_sot",
}

# 球队名称规范化映射（有新联赛时在此扩充）
TEAM_ALIASES: dict[str, str] = {
    "Man United":      "Manchester Utd",
    "Man Utd":         "Manchester Utd",
    "Manchester City": "Manchester City",
    "Spurs":           "Tottenham",
    "Wolves":          "Wolverhampton",
}

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id    TEXT PRIMARY KEY,
    league      TEXT NOT NULL,
    season      TEXT NOT NULL,
    match_date  TEXT NOT NULL,          -- ISO 8601, UTC
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    home_goals  INTEGER,
    away_goals  INTEGER,
    source_url  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,          -- ISO 8601, UTC
    layer_ver   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_odds (
    match_id     TEXT PRIMARY KEY,      -- 对应 matches.match_id
    avg_h REAL, avg_d REAL, avg_a REAL,         -- 赛前平均赔率
    avgc_h REAL, avgc_d REAL, avgc_a REAL,      -- 收盘平均赔率
    b365_h REAL, b365_d REAL, b365_a REAL,
    avg_over25 REAL, avg_under25 REAL,
    avgc_over25 REAL, avgc_under25 REAL,
    fetched_at   TEXT NOT NULL,
    layer_ver    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_stats (
    match_id     TEXT PRIMARY KEY,      -- 对应 matches.match_id
    home_shots INTEGER, away_shots INTEGER,     -- 射门
    home_sot   INTEGER, away_sot   INTEGER,     -- 射正
    fetched_at   TEXT NOT NULL,
    layer_ver    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_xg (
    match_id     TEXT PRIMARY KEY,      -- 对应 matches.match_id；由 data/understat.py 写入
    home_xg REAL, away_xg REAL,         -- understat 赛后 xG（含点球）
    us_match_id  TEXT,                  -- understat 场次 id，便于追溯
    fetched_at   TEXT NOT NULL,
    layer_ver    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    match_id     TEXT PRIMARY KEY,      -- 与赛后 matches.match_id 同算法
    league       TEXT NOT NULL,
    season       TEXT NOT NULL,
    match_date   TEXT NOT NULL,
    kickoff_utc  TEXT,                  -- ISO 8601 UTC
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    avg_h REAL, avg_d REAL, avg_a REAL, -- 下载时刻的平均赔率快照
    fetched_at   TEXT NOT NULL,
    layer_ver    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_aliases (
    raw_name    TEXT PRIMARY KEY,
    std_name    TEXT NOT NULL
);
"""


def _make_match_id(league: str, season: str, date: str,
                   home: str, away: str) -> str:
    key = f"{league}|{season}|{date}|{home}|{away}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _normalize(name: str) -> str:
    return TEAM_ALIASES.get(name.strip(), name.strip())


def _download_csv(url: str) -> pd.DataFrame:
    """下载 CSV；文件带 UTF-8 BOM，按 utf-8-sig 解码以免首列名变成 'ï»¿Div'。
    网络偶发连接重置，最多重试 3 次。"""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            break
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    try:
        text = resp.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = resp.content.decode("latin-1")
    return pd.read_csv(io.StringIO(text), on_bad_lines="skip")


def _parse_date(raw: str) -> str | None:
    """DD/MM/YY 或 DD/MM/YYYY -> YYYY-MM-DD，无法解析返回 None"""
    raw = str(raw).strip()
    try:
        fmt = "%d/%m/%y" if len(raw.split("/")[-1]) == 2 else "%d/%m/%Y"
        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _float_or_none(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None   # NaN -> None


def season_of(match_date: str) -> str:
    """按日期推断赛季代码：7 月及以后归入新赛季，如 2026-10-24 -> "2627"。"""
    d = date.fromisoformat(match_date)
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def init_db(db_path: str = "football.db") -> sqlite3.Connection:
    """初始化数据库，返回连接。可多次调用，幂等。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SCHEMA)
    conn.commit()
    return conn


def load_season(
    league: str,
    season: str,
    conn: sqlite3.Connection,
    db_path: str = "football.db",
) -> int:
    """
    下载一个赛季数据并写入数据库。
    league: 联赛代码，如 "E0"（英超）、"E1"（英冠）
    season: 格式 "2324"（2023-24 赛季）
    返回新写入的行数。
    """
    url = _CSV_URL.format(season=season, league=league)
    fetched_at = datetime.now(timezone.utc).isoformat()

    df = _download_csv(url)

    # 只保留有完整比分的行
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])

    rows, odds_rows, stats_rows = [], [], []
    odds_src  = [c for c in _ODDS_COLS if c in df.columns]
    stats_src = [c for c in _STATS_COLS if c in df.columns]
    for _, row in df.iterrows():
        home = _normalize(str(row["HomeTeam"]))
        away = _normalize(str(row["AwayTeam"]))
        match_date = _parse_date(row["Date"])
        if match_date is None:
            continue

        match_id = _make_match_id(league, season, match_date, home, away)
        rows.append((
            match_id, league, season, match_date,
            home, away,
            int(row["FTHG"]), int(row["FTAG"]),
            url, fetched_at, LAYER_VERSION,
        ))
        odds = {_ODDS_COLS[c]: _float_or_none(row[c]) for c in odds_src}
        if any(v is not None for v in odds.values()):
            odds_rows.append({"match_id": match_id, **odds})
        stats = {_STATS_COLS[c]: _float_or_none(row[c]) for c in stats_src}
        if stats and all(v is not None for v in stats.values()):
            stats_rows.append((match_id, *(int(stats[c]) for c in _STATS_COLS.values())))

    cur = conn.cursor()
    cur.executemany(
        """INSERT OR IGNORE INTO matches
           (match_id, league, season, match_date, home_team, away_team,
            home_goals, away_goals, source_url, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    inserted = cur.rowcount

    # 赛后赔率不再变化：已有则跳过（旧赛季重跑时会自动补齐赔率）
    cols = ["match_id"] + list(_ODDS_COLS.values())
    cur.executemany(
        f"""INSERT OR IGNORE INTO match_odds ({','.join(cols)}, fetched_at, layer_ver)
            VALUES ({','.join('?' * len(cols))}, ?, ?)""",
        [tuple(r.get(c) for c in cols) + (fetched_at, LAYER_VERSION)
         for r in odds_rows],
    )
    # 技术统计同理：只在四列齐全时写入，缺失场次由模型层回退到进球
    cur.executemany(
        f"""INSERT OR IGNORE INTO match_stats
            (match_id, {','.join(_STATS_COLS.values())}, fetched_at, layer_ver)
            VALUES (?,?,?,?,?,?,?)""",
        [r + (fetched_at, LAYER_VERSION) for r in stats_rows],
    )
    conn.commit()
    return inserted


def load_fixtures(conn: sqlite3.Connection, leagues: list[str]) -> int:
    """
    下载 football-data 的未开赛赛程（含当前赔率），整表刷新 fixtures。
    fixtures 只是赛程缓存，可覆盖；预测记录在 review 层，永不覆盖。
    match_id 与赛后 matches 同算法，赛后可直接关联评分。
    返回写入的场数。
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    df = _download_csv(_FIXTURES_URL)
    df = df[df["Div"].isin(leagues)].dropna(subset=["HomeTeam", "AwayTeam", "Date"])

    rows = []
    for _, row in df.iterrows():
        match_date = _parse_date(row["Date"])
        if match_date is None:
            continue
        home = _normalize(str(row["HomeTeam"]))
        away = _normalize(str(row["AwayTeam"]))
        league = str(row["Div"])
        season = season_of(match_date)

        kickoff_utc = None
        raw_time = str(row.get("Time", "")).strip()
        try:
            local = datetime.strptime(f"{match_date} {raw_time}", "%Y-%m-%d %H:%M")
            kickoff_utc = local.replace(tzinfo=_UK_TZ).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass

        rows.append((
            _make_match_id(league, season, match_date, home, away),
            league, season, match_date, kickoff_utc, home, away,
            _float_or_none(row.get("AvgH")), _float_or_none(row.get("AvgD")),
            _float_or_none(row.get("AvgA")),
            fetched_at, LAYER_VERSION,
        ))

    conn.execute("DELETE FROM fixtures")
    conn.executemany(
        """INSERT OR REPLACE INTO fixtures
           (match_id, league, season, match_date, kickoff_utc, home_team, away_team,
            avg_h, avg_d, avg_a, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def market_probs(conn: sqlite3.Connection, league: str,
                 seasons: list[str], closing: bool = True) -> pd.DataFrame:
    """
    市场隐含概率：1/赔率 按比例去除抽水（归一化）。
    closing=True 用收盘平均赔率（最强基准），False 用赛前平均赔率（下载时刻，接近实盘可得）。
    返回 match_id, p_home_win, p_draw, p_away_win。
    """
    pre = "avgc" if closing else "avg"
    df = pd.read_sql_query(
        f"""SELECT o.match_id, o.{pre}_h AS h, o.{pre}_d AS d, o.{pre}_a AS a
            FROM match_odds o JOIN matches m ON o.match_id = m.match_id
            WHERE m.league = ? AND m.season IN ({','.join('?' * len(seasons))})
              AND o.{pre}_h > 1 AND o.{pre}_d > 1 AND o.{pre}_a > 1""",
        conn, params=[league] + list(seasons),
    )
    inv = 1.0 / df[["h", "d", "a"]]
    inv = inv.div(inv.sum(axis=1), axis=0)
    return pd.DataFrame({
        "match_id":   df["match_id"],
        "p_home_win": inv["h"],
        "p_draw":     inv["d"],
        "p_away_win": inv["a"],
    })
