"""补抓 FotMob 历史阵容 / 球员分钟（研究用，扩大阵容研究样本）。
写进单独的 fotmob_hist.db（gitignore；表结构同 fotmob.db）与 _cache/fotmob/，不写 football.db 和实盘 fotmob.db：
football.db 以只读备份到内存，只用来配对场次。实盘 fotmob.db 不放这些赛季，是因为每日任务的 backfill_xg 会把
fotmob.db 里所有场次的全队 xG 补进 football.db 的 match_xg，改变六个无 understat 联赛的 xg_dc 输入。
研究时把 fotmob_hist.db 与 fotmob.db 一起挂上读。
走 data.fotmob.collect_history：只抓比赛页 HTML、间隔 ≥ DELAY、已缓存的不重抓，可中断后重跑续抓。
顺序：先 2526 / 2425 / 2324 里缺的 8 个联赛（留出与选参期），再 2223 / 2122 全部 11 个联赛（球员评分预热）。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/lineup_research/scrape_history.py > _diag/lineup_research/log_scrape.txt 2>&1
     加 --limit N 每个联赛赛季只抓 N 场（试跑）。
"""
import argparse
import sqlite3
import time

from football_prediction.data.fotmob import collect_history, init_fotmob

ALL = ["E0", "D1", "SP1", "I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
MISSING = ["I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
PLAN = [(s, lg) for s in ("2526", "2425", "2324") for lg in MISSING] + \
       [(s, lg) for s in ("2223", "2122") for lg in ALL]
HIST_DB = "fotmob_hist.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default="", help="只跑这些 赛季:联赛，如 2526:E1,2526:T1")
    args = ap.parse_args()
    plan = [tuple(x.split(":")) for x in args.only.split(",") if x] or PLAN
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    conn.execute("ATTACH DATABASE ? AS fm", (HIST_DB,))
    conn.execute("PRAGMA busy_timeout = 120000")   # 临场档同时写 fotmob.db 时等锁
    init_fotmob(conn, "fm")
    t0 = time.monotonic()
    for s, lg in plan:
        try:
            new, miss = collect_history(conn, lg, s, args.limit)
        except Exception as e:  # noqa: BLE001  一个联赛赛季失败（如赛程页抓不到）不影响后面
            print(f"{lg} {s}：失败 {e}", flush=True)
            continue
        print(f"{lg} {s}：新写入 {new} 场，未配对 {miss} 场  累计 {(time.monotonic() - t0) / 3600:.2f} 小时",
              flush=True)
    conn.close()


if __name__ == "__main__":
    main()
