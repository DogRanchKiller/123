"""无赔率信心档（analysis.MODEL_TIERS）对 dc_market 重标定：首选概率 ≥0.60 高 / ≥0.45 中 / 其余低，
各档首选命中与前二命中。标定 2324–2526，留出 2627；对照 dc_xg 与 blend。读 compute.py 的 rows_{lg}.csv。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_blend.blend import W_ELO

HERE = Path(__file__).parent
LGS = ["E0", "D1", "SP1", "I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
IDX = {"home_win": 0, "draw": 1, "away_win": 2}
CUTS = [(0.60, "高"), (0.45, "中"), (0.00, "低")]


def table(P, y, label):
    P = P / P.sum(axis=1, keepdims=True)
    order = np.argsort(-P, axis=1)
    pmax = P.max(axis=1)
    hit1 = order[:, 0] == y
    hit2 = hit1 | (order[:, 1] == y)
    out, hi = [f"  {label}"], np.inf
    for lo, name in CUTS:
        m = (pmax >= lo) & (pmax < hi)
        if m.sum():
            out.append(f"    {name} n={m.sum():>5} ({m.mean():.0%})  均概率 {pmax[m].mean():.3f}  "
                       f"首选 {hit1[m].mean():.3f}  前二 {hit2[m].mean():.3f}")
        hi = lo
    return out


def main():
    df = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in LGS])
    y = df["actual"].map(IDX).to_numpy()
    P = {k: df[[f"h_{k}", f"d_{k}", f"a_{k}"]].to_numpy() for k in ("xg", "mk", "elo")}
    P["blend"] = (1 - W_ELO) * P["xg"] + W_ELO * P["elo"]
    out = []
    for name, m in (("标定 2324–2526", (df.season != "2627").to_numpy()), ("留出 2627", (df.season == "2627").to_numpy())):
        out.append(f"{name}（n={m.sum()}）")
        for k, lab in (("mk", "dc_market"), ("blend", "blend"), ("xg", "dc_xg")):
            out += table(P[k][m], y[m], lab)
    text = "\n".join(out)
    (HERE / "tiers.txt").write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
