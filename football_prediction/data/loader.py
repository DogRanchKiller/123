"""
data/loader.py  v1.0.0
数据层：下载 football-data.co.uk CSV，写入 SQLite，标准化球队 ID。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import sqlite3, hashlib, requests, io
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone

LAYER_VERSION = "1.0.0"

# football-data.co.uk 赛季 URL 模板
_CSV_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

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

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text), on_bad_lines="skip")

    # 只保留有完整比分的行
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])

    rows, inserted = [], 0
    for _, row in df.iterrows():
        home = _normalize(str(row["HomeTeam"]))
        away = _normalize(str(row["AwayTeam"]))
        # 日期格式可能是 DD/MM/YY 或 DD/MM/YYYY
        raw_date = str(row["Date"]).strip()
        try:
            fmt = "%d/%m/%y" if len(raw_date.split("/")[-1]) == 2 else "%d/%m/%Y"
            match_date = datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

        match_id = _make_match_id(league, season, match_date, home, away)
        rows.append((
            match_id, league, season, match_date,
            home, away,
            int(row["FTHG"]), int(row["FTAG"]),
            url, fetched_at, LAYER_VERSION,
        ))

    cur = conn.cursor()
    cur.executemany(
        """INSERT OR IGNORE INTO matches
           (match_id, league, season, match_date, home_team, away_team,
            home_goals, away_goals, source_url, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    inserted = cur.rowcount
    conn.commit()
    return inserted
