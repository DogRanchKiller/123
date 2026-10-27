"""自研模型单独开发线 · dev v0.2-nm：完全不用市场信息的动态攻防。
滤波与 dynamic.run_league 相同，只把观测里的「赔率反推 λ」换成比赛内数据：
  y = w·进球 + (1−w)·k·信号，信号为 射正 / 射门 / xG（k = 本联赛此前累计 进球 / 信号）；缺信号的场次 y 取进球。
  xG 只有老五联赛 2122 起与全部联赛 2627 有（新六联赛 2122–2526 退回进球）。
另跑纯进球（w=1）。每种信号在 2324–2425 上按胜平负 LL 选 w、q、c，2526 + 2627 留出。
对照：dc_market（用历史赔率）、v0.2（只用历史赔率）、赛前市场。不写库，football.db 只读备份到内存。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/dev_model/no_market.py > _diag/dev_model/result_nomarket.txt
"""
import itertools
import sqlite3

import pandas as pd

from dynamic import HERE, HOLD, SEL, load, run_league   # 同目录脚本
from evaluate import LEAGUES, OLD, cmp, report, score_all, score_market

V02 = {"w": 0.0, "q": 0.016, "c": 1.0}      # dynamic.py 选参结果
# 首版网格 q 3e-4…1e-2、c 0.5/0.75/1.0：纯进球选中 q=3e-4（下边界）、c=1.0；再扩到 1e-5 仍落在下边界，
# 故加 q=0（季内不漂移，只靠换季 V_SEASON），去掉 c=0.5。只看选参期
Q, C = (0.0, 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3), (0.75, 1.0)
# xg 选中 w=0.3 在下边界，另测 w=0.2/0.1 × q=1e-5/3e-5（选参期 0.98003…0.98027）都不如 0.97995，不再扩
SIGNALS = {"goals": (1.0,), "sot": (0.3, 0.5, 0.7), "shots": (0.5, 0.7, 0.9), "xg": (0.3, 0.5, 0.7)}


def load_stats(conn: sqlite3.Connection, lg: str) -> pd.DataFrame:
    base = load(conn, lg).drop(columns=["sig_h", "sig_a"])
    st = pd.read_sql_query(
        """SELECT m.match_id, s.home_sot, s.away_sot, s.home_shots, s.away_shots, x.home_xg, x.away_xg
           FROM matches m LEFT JOIN match_stats s ON s.match_id = m.match_id
           LEFT JOIN match_xg x ON x.match_id = m.match_id WHERE m.league = ?""", conn, params=(lg,))
    return base.merge(st, on="match_id", how="left")


def with_signal(df: pd.DataFrame, sig: str) -> pd.DataFrame:
    col = {"goals": None, "sot": "sot", "shots": "shots", "xg": "xg"}[sig]
    out = df.copy()
    out["sig_h"] = out[f"home_{col}"] if col else float("nan")
    out["sig_a"] = out[f"away_{col}"] if col else float("nan")
    return out


def lambdas(raw: dict, sig: str, w: float, q: float, c: float) -> pd.DataFrame:
    return pd.concat([run_league(with_signal(raw[lg], sig), w, q, c) for lg in LEAGUES], ignore_index=True)


def main() -> None:
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    stats = {lg: load_stats(conn, lg) for lg in LEAGUES}
    odds = {lg: load(conn, lg) for lg in LEAGUES}
    src.close()
    rows = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in LEAGUES],
                     ignore_index=True)
    sel, hold = rows[rows.season.isin(SEL)], rows[rows.season.isin(HOLD)]
    print(f"选参 {len(sel)} 场、留出 {len(hold)} 场")
    print("差值 = 前者 − 后者。LL 负 = 前者更好；命中正 = 前者更好。|差| > 2SE 记显著。")

    print("\n==== 一、各信号选参（2324–2425，胜平负 LL）====")
    best = {}
    for sig, ws in SIGNALS.items():
        for w, q, c in itertools.product(ws, Q, C):
            lam = lambdas(stats, sig, w, q, c)
            d = sel.merge(lam, on="match_id")
            ll = score_all(d, d.v2_lh, d.v2_la, d.dc_rho).log_loss.mean()
            if sig not in best or ll < best[sig][0]:
                best[sig] = (ll, w, q, c, lam)
        ll, w, q, c, _ = best[sig]
        print(f"  {sig:<6} 选中 w={w} q={q:g} c={c}  胜平负 LL {ll:.5f}", flush=True)

    d = hold.merge(pd.concat([run_league(odds[lg], **V02) for lg in LEAGUES], ignore_index=True), on="match_id")
    v02 = score_all(d, d.v2_lh, d.v2_la, d.dc_rho)
    dc = score_all(hold, hold.dc_lh, hold.dc_la, hold.dc_rho)
    mk = score_market(hold)
    scored = {}
    for sig, (_, w, q, c, lam) in best.items():
        d = hold.merge(lam, on="match_id")
        scored[sig] = score_all(d, d.v2_lh, d.v2_la, d.dc_rho)

    print("\n==== 二、留出 2526 + 2627：各信号的胜平负 / 亚盘 LL ====")
    print(f"  {'模型':<14}{'胜平负 LL':>10}{'亚盘 LL':>10}{'大小 LL':>10}{'比分 LL':>10}{'胜平负命中':>10}{'亚盘命中':>9}")
    for name, sc in [*((f"无市场·{k}", v) for k, v in scored.items()),
                     ("dc_market", dc), ("v0.2(历史赔率)", v02), ("赛前市场", mk)]:
        sc = sc[sc.match_id.isin(mk.match_id)]
        print(f"  {name:<14}{sc.log_loss.mean():>10.4f}{sc.ah_ll.mean():>10.4f}{sc.ou_ll.mean():>10.4f}"
              f"{sc.cs_ll.mean():>10.4f}{sc.hit.mean():>10.4f}{sc.ah_hit.mean():>9.4f}")

    top = min(scored, key=lambda k: best[k][0])
    nm = scored[top]
    print(f"\n==== 三、选参期最好的无市场信号：{top} ====")
    report("留出：无市场（前者）对 纯进球（后者）", nm, scored["goals"], hold.match_id)
    report("留出：无市场（前者）对 dc_market（后者，用历史赔率）", nm, dc, hold.match_id)
    report("留出：无市场（前者）对 v0.2（后者，只用历史赔率）", nm, v02, hold.match_id)
    report("留出：无市场（前者）对 赛前市场（后者）", nm, mk, hold.match_id)
    for name, ids in (("老五联赛", hold.match_id[hold.league.isin(OLD)]),
                      ("新六联赛", hold.match_id[~hold.league.isin(OLD)])):
        a = nm[nm.match_id.isin(ids)]
        print(f"  {name}：对 dc_market 胜平负 {cmp(a, dc[dc.match_id.isin(ids)], 'log_loss')}"
              f"   对市场 {cmp(a, mk[mk.match_id.isin(ids)], 'log_loss')}")


if __name__ == "__main__":
    main()
