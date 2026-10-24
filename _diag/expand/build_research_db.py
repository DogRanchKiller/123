"""Build research.db: 5 leagues (E0/D1/SP1/I1/F1) x seasons 1415..2526, results + odds + shots + xG.
Live football.db is NOT touched (Elo walks full history; extra seasons would change live models).
Old CSVs (before ~1920) have Betbrain averages (BbAv*) instead of Avg*; mapped to the same columns
(both are pre-match averages at collection time). CSVs cached in _cache/fd_research/.
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
SEASONS = [f"{y:02d}{y + 1:02d}" for y in range(14, 26)]   # 1415 .. 2526
URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
OLD_COLS = {"BbAvH": "AvgH", "BbAvD": "AvgD", "BbAvA": "AvgA",
            "BbAv>2.5": "Avg>2.5", "BbAv<2.5": "Avg<2.5",
            "BbAHh": "AHh", "BbAvAHH": "AvgAHH", "BbAvAHA": "AvgAHA"}


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
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    for old, new in OLD_COLS.items():
        if new not in df.columns and old in df.columns:
            df[new] = df[old]
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
            try:
                nx, miss = load_xg(conn, lg, s)
            except Exception as e:
                nx, miss = 0, f"FAILED {type(e).__name__}: {e}"
            print(f"{lg} {s}: matches +{n}, xG +{nx}, unmatched {miss}", flush=True)
    q = """SELECT m.league, COUNT(*), SUM(x.match_id IS NOT NULL), SUM(o.avg_h IS NOT NULL),
                  SUM(o.avg_over25 IS NOT NULL), SUM(o.ah_line IS NOT NULL), SUM(o.psc_h IS NOT NULL)
           FROM matches m LEFT JOIN match_xg x USING(match_id) LEFT JOIN match_odds o USING(match_id)
           GROUP BY m.league"""
    print("\nleague matches xg avg1x2 avgOU ah pinnacle_close")
    for r in conn.execute(q):
        print(*r)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
