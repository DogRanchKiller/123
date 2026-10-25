"""把意甲 I1、法甲 F1 的 2122–2627 写入实盘库 football.db（与 E0/D1/SP1 相同的赛季范围）。
已结束赛季用 _cache/fd_research 的 CSV（复制到 _cache/fd_raw，与实盘缓存一致），当前赛季下载。
xG 在 matches 写入之后拉。只补不改，可重跑。
    PYTHONPATH=. python _diag/expand/add_live_leagues.py
"""
import os
import shutil
import sys

import pandas as pd

from football_prediction.data.loader import init_db, load_season
from football_prediction.data.understat import load_xg

DB = "football.db"
LEAGUES = ["I1", "F1"]
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
SRC, DST = os.path.join("_cache", "fd_research"), os.path.join("_cache", "fd_raw")


def main():
    conn = init_db(DB)
    for lg in LEAGUES:
        for s in SEASONS:
            src, dst = os.path.join(SRC, f"{lg}_{s}.csv"), os.path.join(DST, f"{lg}_{s}.csv")
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copyfile(src, dst)
            df = pd.read_csv(dst, encoding="utf-8-sig", on_bad_lines="skip") if os.path.exists(dst) else None
            n = load_season(lg, s, conn, DB, df=df)
            n_xg, miss = load_xg(conn, lg, s)
            print(f"{lg} {s}: 赛果 +{n}  xG +{n_xg}  未对齐 {miss}", flush=True)
    for r in conn.execute("""SELECT m.league, m.season, COUNT(*), COUNT(o.avg_h), COUNT(o.avg_over25),
                                    COUNT(o.ah_line), COUNT(x.home_xg), COUNT(st.home_sot)
                             FROM matches m LEFT JOIN match_odds o USING(match_id)
                             LEFT JOIN match_xg x USING(match_id) LEFT JOIN match_stats st USING(match_id)
                             WHERE m.league IN ('I1','F1') GROUP BY 1, 2"""):
        print("  {} {}  场 {}  1X2 {}  大小 {}  亚盘 {}  xG {}  射正 {}".format(*r))
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
