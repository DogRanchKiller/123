"""新联赛（E1 N1 P1 SC0 B1 T1）上核对市场信心档：赛前平均赔率 Shin 去水的最大概率分档，
看首选 / 前二命中是否与 analysis.MARKET_TIERS（5 联赛 1213–2425 标定）一致。
数据：_cache/fd_raw/{lg}_{2122..2526}.csv（已完赛赛季）。
    PYTHONPATH=. python _diag/explore/new_league_tiers.py
"""
import os

import numpy as np
import pandas as pd

from football_prediction.model_market.devig import shin
from football_prediction.output.analysis import MARKET_TIERS, confidence_tier

LEAGUES = ["E1", "N1", "P1", "SC0", "B1", "T1"]
SEASONS = ["2122", "2223", "2324", "2425", "2526"]


def rows():
    for lg in LEAGUES:
        for s in SEASONS:
            p = os.path.join("_cache", "fd_raw", f"{lg}_{s}.csv")
            df = pd.read_csv(p, encoding="utf-8-sig", on_bad_lines="skip")
            df = df.dropna(subset=["FTHG", "FTAG", "AvgH", "AvgD", "AvgA"])
            for _, r in df.iterrows():
                pr = shin([r["AvgH"], r["AvgD"], r["AvgA"]])
                res = 0 if r["FTHG"] > r["FTAG"] else (1 if r["FTHG"] == r["FTAG"] else 2)
                order = np.argsort(-pr)
                yield {"league": lg, "season": s, "pmax": pr.max(),
                       "tier": confidence_tier(pr.max())[0],
                       "hit1": order[0] == res, "hit2": res in order[:2]}


def main():
    d = pd.DataFrame(rows())
    print(f"n={len(d)}")
    ref = {name: (h1, h2) for _, name, h1, h2 in MARKET_TIERS}
    for name in ("高", "中", "低"):
        x = d[d.tier == name]
        se = np.sqrt(x.hit1.mean() * (1 - x.hit1.mean()) / len(x))
        print(f"{name}: n={len(x)} 首选 {x.hit1.mean():.3f}±{se:.3f}（标定 {ref[name][0]:.3f}）"
              f" 前二 {x.hit2.mean():.3f}（标定 {ref[name][1]:.3f}）")
    print("\n各联赛：档  n  首选  前二")
    for lg in LEAGUES:
        for name in ("高", "中", "低"):
            x = d[(d.league == lg) & (d.tier == name)]
            print(f"  {lg:4s} {name} {len(x):5d} {x.hit1.mean():.3f} {x.hit2.mean():.3f}")
    print("\n首选命中 - 平均最大概率（>0 表示市场在该档偏保守）")
    for name in ("高", "中", "低"):
        x = d[d.tier == name]
        print(f"  {name}: 命中 {x.hit1.mean():.3f}  平均 pmax {x.pmax.mean():.3f}")


if __name__ == "__main__":
    main()
