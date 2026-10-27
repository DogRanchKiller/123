"""自研模型单独开发线 · v0.2 与同一时点市场合并：比分矩阵线性混合 (1−a)·市场 + a·v0.2。
市场矩阵与 evaluate.score_market 相同（赛前平均胜平负 + 大小 2.5 喂 implied_matrix）；v0.2 用 dynamic.py 选中的参数。
a 只在 2324–2425 上按胜平负 LL 选，2526 + 2627 留出。不写库，football.db 只读备份到内存。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/dev_model/combine.py > _diag/dev_model/result_combine.txt
"""
import sqlite3

import numpy as np
import pandas as pd

from dynamic import HERE, HOLD, SEL, load, run_league   # 同目录脚本
from evaluate import LEAGUES, OLD, cmp, report, score
from football_prediction.model_market.implied import dc_matrix, implied_matrix

BEST = {"w": 0.0, "q": 0.016, "c": 1.0}      # dynamic.py 选参结果（result_v02.txt）
ALPHAS = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5)


def matrices(df: pd.DataFrame) -> list[tuple]:
    out = []
    for r in df.itertuples():
        got = implied_matrix({"h": r.avg_h, "d": r.avg_d, "a": r.avg_a,
                              "over": r.avg_over25, "under": r.avg_under25})
        if got is not None:
            out.append((r, got[0], dc_matrix(r.v2_lh, r.v2_la, r.dc_rho)))
    return out


def score_mix(mats: list[tuple], a: float) -> pd.DataFrame:
    return pd.DataFrame([{**score((1 - a) * mk + a * v2, int(r.hg), int(r.ag), r.ah_line),
                          "match_id": r.match_id} for r, mk, v2 in mats])


def main() -> None:
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    lam = pd.concat([run_league(load(conn, lg), **BEST) for lg in LEAGUES], ignore_index=True)
    rows = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in LEAGUES],
                     ignore_index=True).merge(lam, on="match_id")
    sel, hold = rows[rows.season.isin(SEL)], rows[rows.season.isin(HOLD)]
    ms, mh = matrices(sel), matrices(hold)
    print(f"选参 {len(ms)} 场、留出 {len(mh)} 场（都有赛前胜平负赔率）")
    print("差值 = 前者 − 后者。LL 负 = 前者更好；命中正 = 前者更好。|差| > 2SE 记显著。")
    print("\n== 选 a（2324–2425）==")
    best = None
    for a in ALPHAS:
        sc = score_mix(ms, a)
        print(f"  a={a:<4} 胜平负 LL {sc.log_loss.mean():.5f}  亚盘 LL {sc.ah_ll.mean():.5f}"
              f"  比分 LL {sc.cs_ll.mean():.5f}", flush=True)
        if best is None or sc.log_loss.mean() < best[0]:
            best = (sc.log_loss.mean(), a)
    a = best[1]
    print(f"  选中 a={a}")
    mix, mk = score_mix(mh, a), score_mix(mh, 0.0)
    ids = pd.Series([r.match_id for r, _, _ in mh])
    lg = {r.match_id: r.league for r, _, _ in mh}
    report(f"留出 2526 + 2627：混合 a={a}（前者）对 赛前市场（后者）", mix, mk, ids)
    report("留出 老五联赛", mix, mk, ids[ids.map(lg).isin(OLD)])
    report("留出 新六联赛", mix, mk, ids[~ids.map(lg).isin(OLD)])
    for s in HOLD:
        report(f"留出 {s}", mix, mk, ids[ids.isin(hold.match_id[hold.season == s])])
    print("\n== 留出期各 a 对 赛前市场（只作参照，不用来选 a）==")
    for x in ALPHAS[1:]:
        sc = score_mix(mh, x)
        print(f"  a={x:<4} 胜平负 LL {cmp(sc, mk, 'log_loss')}   亚盘 LL {cmp(sc, mk, 'ah_ll')}", flush=True)


if __name__ == "__main__":
    main()
