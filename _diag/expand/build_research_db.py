"""Build research.db: 5 leagues (E0/D1/SP1/I1/F1) x seasons 9394..2526, results + odds + shots + xG.
Live football.db is NOT touched (Elo walks full history; extra seasons would change live models).
Odds by era (football-data CSV columns):
  - 1920+: Avg* (market average).  0506..1819: Betbrain averages BbAv* -> mapped to Avg*.
  - 0001..0405: only single bookmakers (B365/GB/IW/LB/SB/WH/...); Avg* = mean of the books present
    (fewer books than Betbrain, so slightly noisier). Asian handicap of that era is NOT used
    (line sign convention not verified).  Before 0001: results only, no odds.
  - Shots / shots on target from about 0506; understat xG only from 1415 (xG not requested earlier).
2026-10-25: extended from 1415 to 9394. Earlier research numbers (1415 start) can shift slightly on rerun
because Elo walks the full history; previous DB kept as research.db.bak_1415.
Season codes before 2000 ("9394".."9900") sort AFTER "2526" as strings: order by match_date, never by
the season string (e.g. `season < s`, ORDER BY season).
CSVs cached in _cache/fd_research/.
Usage: PYTHONPATH=. python -u _diag/expand/build_research_db.py
"""
import os, sys, time
import pandas as pd
import requests

from football_prediction.data.loader import init_db, load_season
from football_prediction.data.understat import load_xg

DB = "research.db"
CACHE = os.path.join("_cache", "fd_research")
LEAGUES = ["E0", "D1", "SP1", "I1", "F1"]
SEASONS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(93, 126)]   # 9394 .. 2526
XG_FROM = "1415"                                                           # understat starts here
URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
OLD_COLS = {"BbAvH": "AvgH", "BbAvD": "AvgD", "BbAvA": "AvgA",
            "BbAv>2.5": "Avg>2.5", "BbAv<2.5": "Avg<2.5",
            "BbAHh": "AHh", "BbAvAHH": "AvgAHH", "BbAvAHA": "AvgAHA"}
BOOKS = ["B365", "BW", "GB", "IW", "LB", "SB", "SO", "SY", "WH", "SJ", "VC", "BS"]   # pre-0506 single books


def season_start(season: str) -> int:
    y = int(season[:2])
    return 1900 + y if y >= 90 else 2000 + y


def _book_mean(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    return df[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)


def csv_for(league: str, season: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{league}_{season}.csv")
    if not os.path.exists(path):
        for i in range(4):   # server resets connections now and then
            try:
                r = requests.get(URL.format(season=season, league=league),
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
                r.raise_for_status()
                break
            except requests.exceptions.ConnectionError:
                if i == 3:
                    raise
                time.sleep(10 * (i + 1))
        with open(path, "wb") as f:
            f.write(r.content)
        time.sleep(1.5)
    # some 0203..0405 rows carry extra empty trailing fields; "skip" dropped up to half a season,
    # so cut them back to the header width instead (the extra fields are all empty)
    trim = lambda fields: fields[:width]
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                width = len(f.readline().split(","))
            df = pd.read_csv(path, encoding=enc, engine="python", on_bad_lines=trim)
            break
        except UnicodeDecodeError:
            continue
    for old, new in OLD_COLS.items():
        if new not in df.columns and old in df.columns:
            df[new] = df[old]
    # 0001..0405: no market average, build it from the single bookmakers present
    for side in "HDA":
        cols = [b + side for b in BOOKS if b + side in df.columns]
        if "Avg" + side not in df.columns and cols:
            df["Avg" + side] = _book_mean(df, cols)
    for side in (">2.5", "<2.5"):
        cols = [b + side for b in BOOKS + ["P"] if b + side in df.columns]
        if "Avg" + side not in df.columns and cols:
            df["Avg" + side] = _book_mean(df, cols)
    return df


def main() -> None:
    os.makedirs(CACHE, exist_ok=True)
    conn = init_db(DB)
    for lg in LEAGUES:
        for s in SEASONS:
            try:
                n = load_season(lg, s, conn, DB, df=csv_for(lg, s))
            except Exception as e:
                print(f"{lg} {s} results FAILED {type(e).__name__}: {e}")
                continue
            if season_start(s) < season_start(XG_FROM):
                print(f"{lg} {s}: matches +{n} (no xG before {XG_FROM})", flush=True)
                continue
            try:
                nx, miss = load_xg(conn, lg, s)
            except Exception as e:
                nx, miss = 0, f"FAILED {type(e).__name__}: {e}"
            print(f"{lg} {s}: matches +{n}, xG +{nx}, unmatched {miss}", flush=True)
    q = """SELECT m.league, COUNT(DISTINCT m.season), COUNT(*), SUM(x.match_id IS NOT NULL),
                  SUM(o.avg_h IS NOT NULL), SUM(o.avg_over25 IS NOT NULL), SUM(o.ah_line IS NOT NULL),
                  SUM(o.psc_h IS NOT NULL), SUM(st.match_id IS NOT NULL)
           FROM matches m LEFT JOIN match_xg x USING(match_id) LEFT JOIN match_odds o USING(match_id)
           LEFT JOIN match_stats st USING(match_id)
           GROUP BY m.league"""
    print("\nleague n_seasons matches xg avg1x2 avgOU ah pinnacle_close shots")
    for r in conn.execute(q):
        print(*r)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
