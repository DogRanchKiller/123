"""
data/oddsportal.py  v1.8.0
v1.6.0: 命令行默认联赛加意甲 I1、法甲 F1。
v1.7.0: 命令行 --leagues 默认取 LEAGUE_SLUGS 全部联赛（新增英冠 / 荷甲 / 葡超 / 苏超 / 比甲 / 土超）。
v1.8.0: book_odds.fetched_at 记每组抓回的时刻（now + 已过秒数），不再记整批开始时刻；
        抓回时已开球的场次不入库（一批可能抓二十多分钟，之前会把开球后的盘口记成开球前）。
多家公司赔率：用开源 OddsHarvester（Playwright 浏览器）抓 OddsPortal 未开赛比赛，
写入 book_odds 表（逐家、逐盘口，含开盘价；只追加，每次抓取一批）。
- 只抓未开赛比赛页；历史赛季页被 robots.txt 禁止，历史赔率继续用 football-data。
- 低并发、页间延时；OddsHarvester 装在独立环境 .venv-scrape（路径可用环境变量 ODDSHARVESTER 覆盖）。
- 能看到哪些公司取决于出口 IP 所在地区（2026-10-24 实测美国 IP 只有 5 家美国公司）。
- 与 fixtures 的配对：同联赛、开赛日期 ±1 天、队名相似度（OddsPortal 列表页的开球时间不可靠）。
- 队名配对与输出解析在 data/oddsportal_parse.py（纯函数），这里重新导出原名字。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from statistics import median

from football_prediction.data.oddsportal_parse import (  # noqa: F401  原导入路径保持可用
    LEAGUE_SLUGS, MATCH_MIN, NAME_ALIASES, link_teams, market_of, match_links, name_sim,
    norm_name, pair_score, parse_record, record_orientation)

LAYER_VERSION = "1.8.0"

AH_DEFAULT = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5)   # 不知道亚盘线时抓的范围

BOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS book_odds (
    match_id     TEXT NOT NULL,         -- 对应 fixtures / matches.match_id
    fetched_at   TEXT NOT NULL,         -- 本批抓取时刻（UTC）
    bookmaker    TEXT NOT NULL,
    market       TEXT NOT NULL,         -- 1x2 / ou / ah
    line         REAL NOT NULL,         -- 大小球线 / 主队让球线（负=主让）；1x2 为 0
    o1 REAL, o2 REAL, o3 REAL,          -- 1x2: 主/平/客；ou: 大/小；ah: 主/客
    open1 REAL, open2 REAL, open3 REAL, -- 开盘价（OddsPortal 的 opening odds）
    opened_at    TEXT,                  -- 开盘时刻（UTC）
    source       TEXT NOT NULL,         -- oddsportal
    layer_ver    TEXT NOT NULL,
    PRIMARY KEY (match_id, fetched_at, bookmaker, market, line)
);
"""


def init_book_odds(conn: sqlite3.Connection) -> None:
    conn.executescript(BOOK_SCHEMA)


def save_book_odds(conn: sqlite3.Connection, match_id: str, rows: list[tuple],
                   fetched_at: str) -> int:
    conn.executemany(
        """INSERT OR IGNORE INTO book_odds
           (match_id, fetched_at, bookmaker, market, line, o1, o2, o3,
            open1, open2, open3, opened_at, source, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(match_id, fetched_at, *r, "oddsportal", LAYER_VERSION) for r in rows])
    return len(rows)


# ---------- 调用 OddsHarvester ----------
def harvester_path() -> str:
    default = os.path.join(".venv-scrape", "Scripts" if os.name == "nt" else "bin", "oddsharvester")
    return os.environ.get("ODDSHARVESTER", default)


def run_harvester(args: list[str], timeout: int) -> list[dict]:
    """以参数列表调用 OddsHarvester（不经 shell），读回 JSON 输出。失败抛 RuntimeError。"""
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = [harvester_path(), "upcoming", "-s", "football", *args,
               "--timezone", "UTC", "--headless", "-f", "json", "-o", out]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        except OSError as e:          # 可执行文件不存在 / 无权限
            raise RuntimeError(f"无法启动 OddsHarvester（{cmd[0]}）：{e}") from e
        if p.returncode != 0:
            raise RuntimeError(f"OddsHarvester 退出码 {p.returncode}: {p.stderr[-500:]}")
        with open(out, encoding="utf-8") as f:
            try:
                return json.load(f) if os.path.getsize(out) else []
            except json.JSONDecodeError as e:
                raise RuntimeError(f"OddsHarvester 输出不是合法 JSON：{e}") from e
    finally:
        os.remove(out)


def _with_retry(runner, args: list[str], timeout: int, log, tries: int = 2,
                pause: float = 30.0) -> list[dict]:
    """失败（含超时）时停 pause 秒重试一次；仍失败记日志并返回空列表，不中断整批。"""
    for i in range(tries):
        try:
            return runner(args, timeout=timeout)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            log(f"  [oddsportal] 第 {i + 1} 次失败：{str(e)[-200:]}")
            if i + 1 < tries and pause:
                time.sleep(pause)
    return []


def ah_lines_for(line: float | None) -> tuple[float, ...]:
    """已知 football-data 亚盘线时只抓它和相邻两条，否则抓默认范围。"""
    if line is None:
        return AH_DEFAULT
    return tuple(round(line + d, 2) for d in (-0.25, 0.0, 0.25))


def _ah_key(line: float) -> str:
    """-0.25 -> asian_handicap_-0_25；0.5 -> asian_handicap_+0_5；0 -> asian_handicap_0"""
    if abs(line) < 1e-9:
        return "asian_handicap_0"
    num = f"{abs(line):.2f}".rstrip("0").rstrip(".").replace(".", "_")
    return f"asian_handicap_{'-' if line < 0 else '+'}{num}"


def collect(conn: sqlite3.Connection, leagues: list[str], now: datetime,
            hours: float = 48.0, concurrency: int = 2, delay: float = 2.0,
            runner=run_harvester, log=print, pause: float = 30.0, timer=time.monotonic) -> int:
    """
    抓 now 起 hours 小时内开赛的 fixtures（需先 load_fixtures）的多家赔率，写入 book_odds。
    返回写入的赔率行数。runner、timer 可替换（测试用）；pause 为失败重试前的等待秒数。
    fetched_at = now + 本组抓回时已过的秒数（timer 计）；抓回时已开球的场次不入库。
    """
    init_book_odds(conn)
    t0 = timer()

    def elapsed_now() -> datetime:
        """now 加上本次调用已过去的秒数：一组比赛抓回来的时刻（宁晚不早）。"""
        return now.astimezone(timezone.utc) + timedelta(seconds=timer() - t0)

    lo, hi = now.isoformat(), (now + timedelta(hours=hours)).isoformat()
    cols = ["match_id", "league", "match_date", "kickoff_utc", "home_team", "away_team", "ah_line"]
    fixtures = [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {','.join(cols)} FROM fixtures WHERE kickoff_utc >= ? AND kickoff_utc <= ?",
        (lo, hi))]
    fixtures = [f for f in fixtures if f["league"] in leagues and f["league"] in LEAGUE_SLUGS]
    if not fixtures:
        log("  [oddsportal] 时间窗内没有比赛")
        return 0

    links = []
    for slug in sorted({LEAGUE_SLUGS[f["league"]] for f in fixtures}):
        links += _with_retry(runner, ["-l", slug, "--links-only", "-c", "1"], 300, log, pause=pause)
    paired = match_links(links, fixtures)
    log(f"  [oddsportal] 时间窗内 {len(fixtures)} 场，配对到 {len(paired)} 场")
    for fx in fixtures:
        if fx["match_id"] not in {v["match_id"] for v in paired.values()}:
            log(f"    未配对：{fx['league']} {fx['home_team']} vs {fx['away_team']}")

    groups: dict[tuple, list[str]] = {}       # 同一组亚盘线的比赛合并成一次调用
    for link, fx in paired.items():
        groups.setdefault(ah_lines_for(fx["ah_line"]), []).append(link)

    n = 0

    def scrape(lines: tuple, glinks: list[str]) -> set[str]:
        """抓一组比赛并入库，返回已处理（含主客不一致跳过）的链接。"""
        nonlocal n
        markets = ",".join(["1x2", "over_under_2_5", *(_ah_key(l) for l in lines)])
        args = ["-m", markets, "--odds-history", "-c", str(concurrency),
                "--request-delay", str(delay)]
        for ln in glinks:
            args += ["--match-link", ln]
        done = set()
        recs = _with_retry(runner, args, 240 * len(glinks) + 120, log, pause=pause)
        got_at = elapsed_now()                # 本组抓回的时刻：各场实际抓取时刻的上限
        fetched_at = got_at.isoformat()
        for rec in recs:
            fx = paired.get(rec.get("match_link"))
            if fx is None:
                continue
            done.add(rec["match_link"])
            if not record_orientation(rec, fx):
                log(f"    主客与赛程不一致，跳过：{rec.get('home_team')} vs {rec.get('away_team')}")
                continue
            if fx["kickoff_utc"] and datetime.fromisoformat(fx["kickoff_utc"]) <= got_at:
                log(f"    抓回时已开球，不入库：{fx['home_team']} vs {fx['away_team']}")
                continue
            n += save_book_odds(conn, fx["match_id"], parse_record(rec), fetched_at)
        conn.commit()
        return done

    missed = []
    for lines, glinks in groups.items():
        done = scrape(lines, glinks)
        if len(glinks) > 1:       # 整组只回来一部分：缺的场次之后单独补抓
            missed += [(lines, ln) for ln in glinks if ln not in done]
    for lines, ln in missed:
        fx = paired[ln]
        log(f"    单独补抓：{fx['home_team']} vs {fx['away_team']}")
        if not scrape(lines, [ln]):
            log(f"    补抓失败：{fx['home_team']} vs {fx['away_team']}")
    return n


# ---------- 多家共识 ----------
def _med(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(median(vals), 3) if vals else None


def book_consensus(conn: sqlite3.Connection, match_id: str,
                   opening: bool = False) -> dict | None:
    """
    该场最新一批抓取的多家中位数赔率，键名与 fixtures 赔率列一致（可直接给 analysis.odds_dict）。
    opening=True 取各家开盘价的中位数。亚盘取主客中位水位最接近的一条线（主盘口）。
    另附 n_books（1X2 公司数）、fetched_at。没有数据返回 None。
    """
    last = conn.execute("SELECT MAX(fetched_at) FROM book_odds WHERE match_id = ?",
                        (match_id,)).fetchone()[0]
    if last is None:
        return None
    a, b, c = ("open1", "open2", "open3") if opening else ("o1", "o2", "o3")
    rows = conn.execute(
        f"SELECT bookmaker, market, line, {a}, {b}, {c} FROM book_odds "
        "WHERE match_id = ? AND fetched_at = ?", (match_id, last)).fetchall()
    x12 = [r for r in rows if r[1] == "1x2"]
    ou = [r for r in rows if r[1] == "ou" and abs(r[2] - 2.5) < 1e-9]
    out = {"fetched_at": last, "n_books": len({r[0] for r in x12}),
           "avg_h": _med(r[3] for r in x12), "avg_d": _med(r[4] for r in x12),
           "avg_a": _med(r[5] for r in x12),
           "avg_over25": _med(r[3] for r in ou), "avg_under25": _med(r[4] for r in ou),
           "ah_line": None, "avg_ahh": None, "avg_aha": None}
    best = None
    for line in sorted({r[2] for r in rows if r[1] == "ah"}):
        h = _med(r[3] for r in rows if r[1] == "ah" and r[2] == line)
        w = _med(r[4] for r in rows if r[1] == "ah" and r[2] == line)
        if h and w and (best is None or abs(h - w) < best[0]):
            best = (abs(h - w), line, h, w)
    if best:
        out.update(ah_line=best[1], avg_ahh=best[2], avg_aha=best[3])
    return out


def main(argv: list[str] | None = None) -> None:
    """python -m football_prediction.data.oddsportal [--hours 48] [--leagues E0,D1,...]
    刷新赛程 → 抓时间窗内多家赔率 → 打印与 football-data 平均赔率的对照。"""
    import argparse
    from football_prediction.data.fixtures import load_fixtures
    from football_prediction.data.loader import init_db
    from football_prediction.output.analysis import devig

    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--leagues", default=",".join(LEAGUE_SLUGS))
    ap.add_argument("--db", default="football.db")
    ap.add_argument("--no-scrape", action="store_true", help="只打印已有数据，不抓取")
    ns = ap.parse_args(argv)
    leagues = ns.leagues.split(",")

    conn = init_db(ns.db)
    init_book_odds(conn)
    now = datetime.now(timezone.utc)
    if not ns.no_scrape and shutil.which(harvester_path()) is None:
        print(f"[oddsportal] 找不到 OddsHarvester（{harvester_path()}），跳过抓取；"
              "请安装到 .venv-scrape 或设置环境变量 ODDSHARVESTER")
        ns.no_scrape = True
    if not ns.no_scrape:
        print(f"[1] 刷新赛程：{load_fixtures(conn, leagues)} 场")
        print(f"[2] 抓多家赔率：写入 {collect(conn, leagues, now, ns.hours)} 行")
    hi = (now + timedelta(hours=ns.hours)).isoformat()
    fx = conn.execute(
        "SELECT match_id, league, kickoff_utc, home_team, away_team, avg_h, avg_d, avg_a "
        "FROM fixtures WHERE kickoff_utc >= ? AND kickoff_utc <= ? ORDER BY kickoff_utc",
        (now.isoformat(), hi)).fetchall()
    print("\n联赛 开球(UTC)   主队 vs 客队 | 公司数 | 多家中位 主/平/客 | 开盘中位 | fd平均 | 主胜概率 开盘→现在 | 亚盘 | 大2.5")
    for mid, lg, ko, h, a, fh, fd, fa in fx:
        cur, op = book_consensus(conn, mid), book_consensus(conn, mid, opening=True)
        if cur is None:
            continue
        p1 = devig(cur["avg_h"], cur["avg_d"], cur["avg_a"])
        p0 = devig(op["avg_h"], op["avg_d"], op["avg_a"]) if op else None
        fmt = lambda d: f"{d['avg_h']}/{d['avg_d']}/{d['avg_a']}" if d and d["avg_h"] else "-"
        mv = f"{p0[0]:.0%}→{p1[0]:.0%}" if p0 and p1 else "-"
        ah = f"{cur['ah_line']:+g} {cur['avg_ahh']}/{cur['avg_aha']}" if cur["ah_line"] is not None else "-"
        print(f"{lg} {ko[5:16]} {h} vs {a} | {cur['n_books']} | {fmt(cur)} | {fmt(op)} | "
              f"{fh}/{fd}/{fa} | {mv} | {ah} | {cur['avg_over25']}/{cur['avg_under25']}")


if __name__ == "__main__":
    main()
