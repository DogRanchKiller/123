"""兜底模型核对：dc_market（MarketDixonColesModel，goal_weight=0.3）对现行兜底的同场 1X2 log loss 差值（负 = 前者更好）。
现行无赔率时：比分矩阵用 dc_xg，胜平负用 blend = 0.77·dc_xg + 0.23·Elo（W_ELO 在 research.db 选定，不在这里重选）。
另看 dc_market + Elo（同样 0.23，未重选，只作参考）。
读 compute.py 生成的 rows_{lg}.csv，按联赛、新老联赛与赛季汇总，结果写 result.txt。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_blend.blend import W_ELO

HERE = Path(__file__).parent
OLD = ["E0", "D1", "SP1", "I1", "F1"]
NEW = ["E1", "N1", "P1", "SC0", "B1", "T1"]
IDX = {"home_win": 0, "draw": 1, "away_win": 2}


def probs(df, k):
    return df[[f"h_{k}", f"d_{k}", f"a_{k}"]].to_numpy()


def ll(P, y):
    P = P / P.sum(axis=1, keepdims=True)
    return -np.log(np.clip(P[np.arange(len(P)), y], 1e-12, None))


def line(label, d):
    d = np.asarray(d, float)
    se = d.std(ddof=1) / np.sqrt(len(d))
    flag = "显著" if abs(d.mean()) > 2 * se else "不显著"
    return f"{label:<10} n={len(d):>5}  {d.mean():+.5f} ± {se:.5f}  {flag}"


def main():
    df = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in OLD + NEW])
    y = df["actual"].map(IDX).to_numpy()
    xg, mk, elo = probs(df, "xg"), probs(df, "mk"), probs(df, "elo")
    L = {"dc_xg": ll(xg, y), "dc_market": ll(mk, y), "elo": ll(elo, y),
         "blend": ll((1 - W_ELO) * xg + W_ELO * elo, y),
         "dc_market+Elo": ll((1 - W_ELO) * mk + W_ELO * elo, y)}
    pairs = [("dc_market", "dc_xg"), ("dc_market", "blend"), ("dc_market+Elo", "dc_market"), ("blend", "dc_xg")]
    out = [f"1X2 log loss 同场差值（负 = 前者更好），月度重拟合，训练 2122 起，测试 2324–2627；W_ELO={W_ELO}", ""]
    out.append("各模型平均：" + "  ".join(f"{k}={v.mean():.4f}" for k, v in L.items()))
    groups = [(lg, (df.league == lg).to_numpy()) for lg in OLD + NEW]
    groups += [("老五联赛", df.league.isin(OLD).to_numpy()), ("新六联赛", df.league.isin(NEW).to_numpy()),
               ("全部", np.ones(len(df), bool))]
    groups += [(f"赛季{s}", (df.season == s).to_numpy()) for s in sorted(df.season.unique())]
    for a, b in pairs:
        out += ["", f"{a} − {b}："]
        out += ["  " + line(g, (L[a] - L[b])[m]) for g, m in groups]
    text = "\n".join(out)
    (HERE / "result.txt").write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
