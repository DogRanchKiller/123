"""
data/fixtures.py  v1.8.0
未开赛赛程与赔率快照：football-data fixtures.csv → fixtures 表；每次刷新追加 odds_snapshots。
从 data/loader.py 拆出（行为不变）；表结构仍在 loader.DB_SCHEMA。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from football_prediction.data.loader import (
    LAYER_VERSION, _download_csv, _float_or_none, _make_match_id, _normalize, _parse_date,
    season_of)

_FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"
_UK_TZ = ZoneInfo("Europe/London")   # football-data 的开球时间为英国本地时间

# 赛程赔率列：CSV 列名 -> fixtures / odds_snapshots 列名（下载时刻的当前盘）
_FIX_ODDS_COLS = {
    "AvgH": "avg_h", "AvgD": "avg_d", "AvgA": "avg_a",
    "Avg>2.5": "avg_over25", "Avg<2.5": "avg_under25",
    "AHh": "ah_line", "AvgAHH": "avg_ahh", "AvgAHA": "avg_aha",
}


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
        odds = tuple(_float_or_none(row.get(c)) for c in _FIX_ODDS_COLS)

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
            *odds, fetched_at, LAYER_VERSION,
        ))

    odds_cols = list(_FIX_ODDS_COLS.values())
    conn.execute("DELETE FROM fixtures")
    conn.executemany(
        f"""INSERT OR REPLACE INTO fixtures
            (match_id, league, season, match_date, kickoff_utc, home_team, away_team,
             {','.join(odds_cols)}, fetched_at, layer_ver)
            VALUES ({','.join('?' * (9 + len(odds_cols)))})""",
        rows,
    )
    save_snapshots(conn, [(r[0], *r[7:7 + len(odds_cols)]) for r in rows], fetched_at)
    conn.commit()
    return len(rows)


def save_snapshots(conn: sqlite3.Connection, rows: list[tuple], fetched_at: str) -> int:
    """
    追加赔率快照：rows 每项为 (match_id, *_FIX_ODDS_COLS 对应值)。
    与该场上一条快照完全相同、或赔率全空时不写，返回写入条数。
    """
    cols = list(_FIX_ODDS_COLS.values())
    n = 0
    for mid, *vals in rows:
        if all(v is None for v in vals):
            continue
        last = conn.execute(
            f"SELECT {','.join(cols)} FROM odds_snapshots WHERE match_id = ? "
            "ORDER BY fetched_at DESC LIMIT 1", (mid,)).fetchone()
        if last is not None and tuple(last) == tuple(vals):
            continue
        conn.execute(
            f"""INSERT OR IGNORE INTO odds_snapshots (match_id, fetched_at, {','.join(cols)}, layer_ver)
                VALUES ({','.join('?' * (3 + len(cols)))})""",
            (mid, fetched_at, *vals, LAYER_VERSION))
        n += 1
    return n


def odds_movement(conn: sqlite3.Connection, match_id: str) -> tuple[dict, dict] | None:
    """返回该场 (首条快照, 最新快照)；不足两条时返回 None。"""
    cols = ["fetched_at"] + list(_FIX_ODDS_COLS.values())
    q = (f"SELECT {','.join(cols)} FROM odds_snapshots WHERE match_id = ? "
         "ORDER BY fetched_at {} LIMIT 1")
    first = conn.execute(q.format("ASC"), (match_id,)).fetchone()
    last = conn.execute(q.format("DESC"), (match_id,)).fetchone()
    if first is None or first[0] == last[0]:
        return None
    return dict(zip(cols, first)), dict(zip(cols, last))
