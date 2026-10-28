"""实盘体检：每日 live 结束时打印的几条提示，只读库，不改预测、不写快照、不上网站。
- 已开球超过 STALE_DAYS 天仍没有赛果的存档（评分卡住：football-data 与 FotMob 都没到）；
- 未来 UPCOMING_HOURS 小时内的赛程：缺赛程表赔率的场数、没有主模型开球前存档的场数；
- 各联赛 football-data 最近一场赛果的日期（只作信息）；
- 多家赔率 book_odds 最近一次抓取离现在多久（超过 BOOK_STALE_HOURS 提示）；
- 最近 ROLLING_DAYS 天开球的已评分场次上，主模型对各对照（market_avg、MARKET_MODEL）的同场差，
  主模型显著更差（差值 − 2×SE > 0）时提示。
"""
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from football_prediction import version
from football_prediction.review.scorecard import _paired, _scored_first

STALE_DAYS = 3
UPCOMING_HOURS = 48
BOOK_STALE_HOURS = 36
ROLLING_DAYS = 30
REFERENCES = ("market_avg", version.MARKET_MODEL[0])


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _stale(conn: sqlite3.Connection, now: datetime) -> list[tuple[str, str]]:
    """基准 market_avg 每场都存，用它找开球超过 STALE_DAYS 天仍未评分的场次：[(match_id, kickoff_utc)]。"""
    cut = (now - timedelta(days=STALE_DAYS)).isoformat()
    return conn.execute(
        "SELECT match_id, MIN(json_extract(extra_markets, '$.kickoff_utc')) AS ko FROM predictions "
        "WHERE model_name = 'market_avg' AND actual_outcome IS NULL "
        "GROUP BY match_id HAVING ko IS NOT NULL AND ko < ? ORDER BY ko", (cut,)).fetchall()


def _upcoming(conn: sqlite3.Connection, now: datetime) -> dict:
    hi = (now + timedelta(hours=UPCOMING_HOURS)).isoformat()
    rows = conn.execute(
        "SELECT match_id, avg_h IS NOT NULL AND avg_d IS NOT NULL AND avg_a IS NOT NULL FROM fixtures "
        "WHERE kickoff_utc > ? AND kickoff_utc <= ?", (now.isoformat(), hi)).fetchall()
    ids = [r[0] for r in rows]
    archived = set()
    if ids:
        q = ",".join("?" * len(ids))
        archived = {r[0] for r in conn.execute(
            f"SELECT DISTINCT match_id FROM predictions WHERE model_name = ? AND match_id IN ({q}) "
            "AND NOT (json_extract(extra_markets, '$.kickoff_utc') IS NOT NULL "
            "AND generated_at >= json_extract(extra_markets, '$.kickoff_utc'))",
            (version.PRIMARY_MODEL[0], *ids))}
    return {"n": len(rows), "no_odds": sum(1 for r in rows if not r[1]),
            "no_primary": len(set(ids) - archived)}


def _rolling(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """最近 ROLLING_DAYS 天开球的已评分场次，主模型对各对照的同场差（正 = 主模型更差）。"""
    df = _scored_first(conn)
    if df.empty:
        return []
    ko = pd.to_datetime(df["kickoff_utc"], utc=True, format="ISO8601")
    df = df[ko >= pd.Timestamp(now - timedelta(days=ROLLING_DAYS))]
    prim = df[df["model_name"] == version.PRIMARY_MODEL[0]]
    out = []
    for ref in REFERENCES:
        n, diff, se = _paired(prim, df[df["model_name"] == ref].drop_duplicates("match_id"))
        out.append({"ref": ref, "n": n, "diff": diff, "se": se,
                    "worse": bool(n > 1 and diff - 2 * se > 0)})
    return out


def _league_last(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """各联赛 football-data 最近一场有比分的日期：[(league, match_date)]。只作信息（FotMob 先评分时它会落后）。"""
    return conn.execute(
        "SELECT league, MAX(match_date) FROM matches WHERE home_goals IS NOT NULL "
        "GROUP BY league ORDER BY league").fetchall()


def health_check(conn: sqlite3.Connection, now: datetime) -> dict:
    """体检结果（都是只读查询）。now 为带时区的 UTC 时刻。"""
    has_book = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'book_odds'").fetchone()
    last = conn.execute("SELECT MAX(fetched_at) FROM book_odds").fetchone()[0] if has_book else None
    book_age = (now - _ts(last)).total_seconds() / 3600 if last else None
    return {"stale": _stale(conn, now), "upcoming": _upcoming(conn, now), "leagues": _league_last(conn),
            "book_last": last, "book_age_h": book_age, "rolling": _rolling(conn, now)}


def health_lines(h: dict) -> list[str]:
    """把体检结果写成提示行；有问题的行以「⚠」开头。"""
    lines = []
    s = h["stale"]
    lines.append(f"⚠ 开球超过 {STALE_DAYS} 天仍未评分 {len(s)} 场（最早 {s[0][1][:16]}，{s[0][0]}）"
                 if s else f"开球超过 {STALE_DAYS} 天仍未评分：0 场")
    u = h["upcoming"]
    mark = "⚠ " if u["no_odds"] or u["no_primary"] else ""
    lines.append(f"{mark}未来 {UPCOMING_HOURS} 小时赛程 {u['n']} 场：缺赛程表赔率 {u['no_odds']} 场，"
                 f"没有主模型 {version.PRIMARY_MODEL[0]} 存档 {u['no_primary']} 场")
    if h["leagues"]:
        lines.append("football-data 最近赛果：" + " · ".join(f"{lg} {d[5:10]}" for lg, d in h["leagues"]))
    if h["book_last"] is None:
        lines.append("⚠ 多家赔率 book_odds 还没有抓取记录")
    else:
        mark = "⚠ " if h["book_age_h"] > BOOK_STALE_HOURS else ""
        lines.append(f"{mark}多家赔率最近一次抓取 {h['book_last'][:16]}（{h['book_age_h']:.1f} 小时前）")
    for r in h["rolling"]:
        if r["n"] < 2:
            lines.append(f"近 {ROLLING_DAYS} 天主模型对 {r['ref']}：同场已评分 {r['n']} 场，样本不足")
            continue
        mark = "⚠ " if r["worse"] else ""
        tail = "，主模型显著更差" if r["worse"] else ""
        lines.append(f"{mark}近 {ROLLING_DAYS} 天主模型对 {r['ref']}：{r['n']} 场 "
                     f"{r['diff']:+.4f}±{r['se']:.4f}（正 = 主模型更差）{tail}")
    return lines
