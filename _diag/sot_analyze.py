"""射正版回测（分析）。
1) 各 w 的 Log Loss：在 2324+2425 选 w，2526 确认。
2) 同场配对：射正版 vs DC、vs 市场。
3) 市场+模型 对数线性混合 p ∝ m^a · x^b：2324+2425 拟合 (a,b)，2526 检验。
   b 显著 > 0 说明模型含市场没有的信息。
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

df = pd.read_csv("_diag/sot_matches.csv", dtype={"season": str})
P = ["p_home_win", "p_draw", "p_away_win"]
SEL, HOLD = ["2324", "2425"], ["2526"]

wide = df.pivot_table(index=["match_id", "league", "season"], columns="model",
                      values="log_loss").dropna().reset_index()
models = [c for c in wide.columns if c not in ("match_id", "league", "season")]


def paired(a, b, mask):
    d = wide.loc[mask, a] - wide.loc[mask, b]
    return f"{d.mean():+.4f}±{d.std(ddof=1) / np.sqrt(len(d)):.4f}"


print("--- 各模型 Log Loss（同场，联赛×赛季） ---")
print(wide.groupby(["season", "league"])[models].mean().round(4).to_string())
for name, ss in [("选参 2324+2425", SEL), ("留出 2526", HOLD)]:
    m = wide.season.isin(ss)
    print(f"\n[{name}] 场数 {m.sum()}")
    print(wide.loc[m, models].mean().round(4).to_string())

sot = [c for c in models if c.startswith("sot")]
best = min(sot, key=lambda c: wide.loc[wide.season.isin(SEL), c].mean())
print(f"\n选参结果（仅 2324+2425）：{best}")

print("\n--- 同场配对 差值±SE（负=前者更好） ---")
for ss_name, ss in [("选参", SEL), ("留出2526", HOLD)]:
    for lg in ["E0", "D1", "SP1", None]:
        m = wide.season.isin(ss) & ((wide.league == lg) if lg else True)
        print(f"{ss_name:6s} {lg or '合计':4s} n={m.sum():4d}  "
              f"{best}−dc {paired(best, 'dc', m)}   "
              f"{best}−市场 {paired(best, 'market', m)}   "
              f"dc−市场 {paired('dc', 'market', m)}")

# ---- 对数线性混合 ----
probs = df.pivot_table(index=["match_id", "league", "season", "actual"],
                       columns="model", values=P).dropna().reset_index()
y = probs["actual"].map({"home_win": 0, "draw": 1, "away_win": 2}).to_numpy()


def stack(model):
    return np.log(np.clip(np.column_stack([probs[(p, model)] for p in P]), 1e-9, 1))


def blend_ll(params, lm, lx, idx):
    a, b = params
    z = a * lm[idx] + b * lx[idx]
    z -= z.max(axis=1, keepdims=True)
    logp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
    return -logp[np.arange(idx.sum()), y[idx]]


lm = stack("market")
tr = probs["season"].isin(SEL).to_numpy()
te = probs["season"].isin(HOLD).to_numpy()
print("\n--- 市场 + 模型 对数线性混合（2324+2425 拟合，2526 检验） ---")
base = blend_ll((1, 0), lm, lm, te)
for model in ["dc", best]:
    lx = stack(model)
    res = minimize(lambda p: blend_ll(p, lm, lx, tr).mean(), [1.0, 0.0])
    a, b = res.x
    # b 的 SE：数值 Hessian（按场数缩放）
    H = res.hess_inv * 1 / tr.sum()
    d = blend_ll(res.x, lm, lx, te) - base
    print(f"{model:9s} a={a:.3f} b={b:+.3f}(SE≈{np.sqrt(H[1, 1]):.3f})  "
          f"2526 混合−市场 {d.mean():+.4f}±{d.std(ddof=1) / np.sqrt(len(d)):.4f}")
    for lg in ["E0", "D1", "SP1"]:
        mlg = probs.loc[te, "league"].to_numpy() == lg
        print(f"           {lg:4s} {d[mlg].mean():+.4f}±{d[mlg].std(ddof=1) / np.sqrt(mlg.sum()):.4f}")
