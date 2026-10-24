"""方向 D 评估：主模型概率 + 首发特征，对称 logit 修正，只拟合少量系数防过拟合。
  z_h = log(ph/pd) + c_h + b1·Δatt + b2·Δcont
  z_a = log(pa/pd) + c_a − b1·Δatt − b2·Δcont      （Δ = 主 − 客）
对照组只拟合 c_h, c_a（同样的训练/测试场次），差值即首发信息的贡献。
训练：2324（10 月起，球员历史已积累）+ 2425；测试：2526 + 2627。仅 E0。"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from _diag.explore.harness import load_all, run, paired, ll, hit
from _diag.explore.lineup import build

df = load_all()
base = run(df, {}, leagues=["E0"])
f = build("E0")
r = base.merge(f, on="match_id").merge(df[["match_id", "match_date", "mc_h", "mc_d", "mc_a",
                                          "mo_h", "mo_d", "mo_a"]], on="match_id")
r["datt"], r["dcont"] = r.att_h - r.att_a, r.cont_h - r.cont_a
tr = (r.season.isin(["2324", "2425"]) & (r.match_date >= "2023-10-01")).to_numpy()
te = r.season.isin(["2526", "2627"]).to_numpy()
P = r[["p_h", "p_d", "p_a"]].to_numpy()
L1, L2 = np.log(P[:, 0] / P[:, 1]), np.log(P[:, 2] / P[:, 1])
X = r[["datt", "dcont"]].to_numpy()
y = r.actual.to_numpy()


def probs(w, use):
    s = X @ w[2:] if use else 0.0
    Z = np.stack([L1 + w[0] + s, np.zeros(len(r)), L2 + w[1] - s], 1)
    Z = np.exp(Z - Z.max(1, keepdims=True))
    return Z / Z.sum(1, keepdims=True)


def fit(use):
    def nll(w):
        Q = probs(w, use)[tr]
        return -np.log(Q[np.arange(tr.sum()), y[tr]]).sum()
    return minimize(nll, np.zeros(4 if use else 2), method="BFGS").x


print("训练场数", tr.sum(), "测试场数", te.sum())
print(r.loc[te, ["datt", "dcont"]].describe().round(3).to_string())
res = {}
for name, use in [("intercept_only", False), ("lineup", True)]:
    w = fit(use)
    Q = probs(w, use)
    res[name] = r.assign(p_h=Q[:, 0], p_d=Q[:, 1], p_a=Q[:, 2])
    print(name, "系数", np.round(w, 3))
T = lambda x: x[te]
for name, ref in [("lineup vs intercept_only", "intercept_only"), ("lineup vs base", None)]:
    a = T(res["lineup"]); b = T(res[ref]) if ref else T(r)
    n, d, se = paired(a, b); _, dh, seh = paired(a, b, f=hit)
    print(f"{name}: n={n} LL {d:+.4f}±{se:.4f}  hit {dh:+.3f}±{seh:.3f}")
for tag in ["c", "o"]:
    m = r.assign(p_h=r[f"m{tag}_h"], p_d=r[f"m{tag}_d"], p_a=r[f"m{tag}_a"])
    for name, a in [("base", r), ("lineup", res["lineup"])]:
        n, d, se = paired(T(a), T(m))
        print(f"{name} vs market_{tag}: LL {d:+.4f}±{se:.4f}  模型命中 {hit(T(a)).mean():.3f} 市场命中 {hit(T(m)).mean():.3f}")
