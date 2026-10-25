"""
data/loader.py  v1.7.0
数据层：下载 football-data.co.uk CSV，写入 SQLite，标准化球队 ID。
v1.1.0: 保存赛前/收盘平均赔率（match_odds 表，作市场基准）；
        下载未开赛赛程 fixtures.csv（fixtures 表，供实盘预测）；CSV 按 utf-8-sig 解码。
v1.2.0: 保存射门/射正（match_stats 表），供射正版实力估计。
v1.3.0: 新增 match_xg 表结构（数据由 data/understat.py 下载对齐写入）。
v1.4.0: 赔率补全亚盘（盘口线 + 平均水位，赛前/收盘）与 Pinnacle 1X2；
        fixtures 增加大小 2.5 与亚盘；新增 odds_snapshots 赔率快照表（只追加，用于看盘口变动）；
        旧库 ALTER TABLE 自动迁移；match_odds 改为只补空值（已有值永不覆盖）；
        backfill_odds 从本地缓存 CSV 补旧赛季新列。
v1.5.0: 本文件未改；数据层新增 data/oddsportal.py（多家公司赔率 book_odds 表）。
        之后拆分（行为不变）：赛程与快照 load_fixtures / save_snapshots / odds_movement 移到 data/fixtures.py。
v1.6.0: 实盘库加入意甲 I1、法甲 F1 的 2122–2627（_diag/expand/add_live_leagues.py），
        OddsPortal / FotMob 补意甲法甲联赛与队名；CSV 只有部分射门列时（老赛季）不再 KeyError，跳过该场统计。
v1.7.0: 本文件未改；实盘库加入英冠 E1 / 荷甲 N1 / 葡超 P1 / 苏超 SC0 / 比甲 B1 / 土超 T1 的 2122–2627，
        OddsPortal 补联赛 slug 与队名，understat 导出 US_LEAGUES（新联赛没有 understat xG）。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import sqlite3, hashlib, requests, io, time, glob, os
import pandas as pd
from datetime import date, datetime, timezone

LAYER_VERSION = "1.7.0"
BUSY_TIMEOUT = 120     # 秒；SQLite 遇锁时的等待上限（init_db）

# football-data.co.uk 赛季 URL 模板（www 会 302 到裸域名，直接用裸域名少一次握手）
_CSV_URL      = "https://football-data.co.uk/mmz4281/{season}/{league}.csv"

# 赔率列：CSV 列名 -> match_odds 列名（Avg = 多家公司平均，C = 收盘）
_ODDS_COLS = {
    "AvgH": "avg_h",   "AvgD": "avg_d",   "AvgA": "avg_a",
    "AvgCH": "avgc_h", "AvgCD": "avgc_d", "AvgCA": "avgc_a",
    "B365H": "b365_h", "B365D": "b365_d", "B365A": "b365_a",
    "Avg>2.5": "avg_over25",   "Avg<2.5": "avg_under25",
    "AvgC>2.5": "avgc_over25", "AvgC<2.5": "avgc_under25",
    # v1.4.0：亚盘（AHh=主队让球线，负数=主让）与 Pinnacle
    "AHh": "ah_line",          "AvgAHH": "avg_ahh",   "AvgAHA": "avg_aha",
    "AHCh": "ahc_line",        "AvgCAHH": "avgc_ahh", "AvgCAHA": "avgc_aha",
    "PSH": "ps_h",   "PSD": "ps_d",   "PSA": "ps_a",
    "PSCH": "psc_h", "PSCD": "psc_d", "PSCA": "psc_a",
}

# v1.4.0 新增列（旧库迁移用）：表 -> [(列, 类型)]
_NEW_COLUMNS = {
    "match_odds": [(c, "REAL") for c in ("ah_line", "avg_ahh", "avg_aha", "ahc_line",
                                         "avgc_ahh", "avgc_aha", "ps_h", "ps_d", "ps_a",
                                         "psc_h", "psc_d", "psc_a")],
    "fixtures":   [(c, "REAL") for c in ("avg_over25", "avg_under25",
                                         "ah_line", "avg_ahh", "avg_aha")],
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
    ah_line REAL, avg_ahh REAL, avg_aha REAL,   -- 赛前亚盘：主队让球线 + 平均水位
    ahc_line REAL, avgc_ahh REAL, avgc_aha REAL,-- 收盘亚盘
    ps_h REAL, ps_d REAL, ps_a REAL,            -- Pinnacle 赛前
    psc_h REAL, psc_d REAL, psc_a REAL,         -- Pinnacle 收盘
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
    avg_over25 REAL, avg_under25 REAL,  -- 大小 2.5
    ah_line REAL, avg_ahh REAL, avg_aha REAL,   -- 亚盘：主队让球线 + 平均水位
    fetched_at   TEXT NOT NULL,
    layer_ver    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odds_snapshots (
    match_id     TEXT NOT NULL,         -- 对应 fixtures / matches.match_id
    fetched_at   TEXT NOT NULL,         -- 下载时刻（UTC）
    avg_h REAL, avg_d REAL, avg_a REAL,
    avg_over25 REAL, avg_under25 REAL,
    ah_line REAL, avg_ahh REAL, avg_aha REAL,
    layer_ver    TEXT NOT NULL,
    PRIMARY KEY (match_id, fetched_at)  -- 只追加；与上一条相同则不写
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
    """初始化数据库，返回连接。可多次调用，幂等。
    timeout=120：临场任务与每日任务同时写库时等对方提交，而不是立刻报 database is locked
    （各层都是逐批提交，单次持锁很短）。对挂上的 fotmob.db 同样生效。"""
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT)
    conn.executescript(DB_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库补 v1.4.0 新列（ALTER TABLE ADD COLUMN，已有则跳过，幂等）"""
    for table, cols in _NEW_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def _upsert_odds(cur: sqlite3.Cursor, odds_rows: list[dict], fetched_at: str) -> None:
    """写入 match_odds：新场次插入；已有场次只补空值，已有值永不覆盖。"""
    cols = ["match_id"] + list(_ODDS_COLS.values())
    fill = ", ".join(f"{c} = COALESCE({c}, excluded.{c})" for c in cols[1:])
    cur.executemany(
        f"""INSERT INTO match_odds ({','.join(cols)}, fetched_at, layer_ver)
            VALUES ({','.join('?' * len(cols))}, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET {fill}""",
        [tuple(r.get(c) for c in cols) + (fetched_at, LAYER_VERSION)
         for r in odds_rows],
    )


def load_season(
    league: str,
    season: str,
    conn: sqlite3.Connection,
    db_path: str = "football.db",
    df: pd.DataFrame | None = None,
) -> int:
    """
    下载一个赛季数据并写入数据库。
    league: 联赛代码，如 "E0"（英超）、"E1"（英冠）
    season: 格式 "2324"（2023-24 赛季）
    df: 已有的 CSV 内容（如本地缓存）；为 None 时下载。
    返回新写入的行数。
    """
    url = _CSV_URL.format(season=season, league=league)
    fetched_at = datetime.now(timezone.utc).isoformat()

    if df is None:
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
        # 老 CSV 可能只有射门没有射正（如 D1 0304–0506）：四列不齐不写
        if len(stats) == len(_STATS_COLS) and all(v is not None for v in stats.values()):
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

    # 赛后赔率不再变化：已有值不覆盖，只补空列（旧赛季重跑时会自动补齐新列）
    _upsert_odds(cur, odds_rows, fetched_at)
    # 技术统计同理：只在四列齐全时写入，缺失场次由模型层回退到进球
    cur.executemany(
        f"""INSERT OR IGNORE INTO match_stats
            (match_id, {','.join(_STATS_COLS.values())}, fetched_at, layer_ver)
            VALUES (?,?,?,?,?,?,?)""",
        [r + (fetched_at, LAYER_VERSION) for r in stats_rows],
    )
    conn.commit()
    return inserted



def backfill_odds(conn: sqlite3.Connection, cache_dir: str = "_cache/fd_raw") -> int:
    """用本地缓存的赛季 CSV（{联赛}_{赛季}.csv）补 match_odds 新列：只填空值，不改已有值。
    返回处理的文件数。"""
    n = 0
    for path in sorted(glob.glob(os.path.join(cache_dir, "*_*.csv"))):
        league, season = os.path.splitext(os.path.basename(path))[0].split("_", 1)
        df = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
        load_season(league, season, conn, df=df)
        n += 1
    return n


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
