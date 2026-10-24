"""多模型集成：DC(进球) / DC(xG主模型) / DC(射正) / Elo，以及与市场融合
权重在 2324+2425 选，在 2526+2627 确认（配对 logloss）"""
import itertools
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from _diag.explore.harness import load_all, run, BASE

df = load_all()
CFG = {"dc_goals": dict(BASE, wg=1.0, wx=0.0, ws=0.0),
       "dc_xg": dict(BASE),
       "dc_sot": dict(BASE, wg=0.3, wx=0.0, ws=0.7)}
P = {}
for k, c in CFG.items():
    r = run(df, c).set_index("match_id")
    P[k] = r[["p_h", "p_d", "p_a"]]
    print(k, "done", len(r))
base = r[["league", "season", "actual"]]

# Elo：按时间顺序逐场更新（含进球差倍数），赛季间回归 1/3
R, rows = {}, []
for _, m in df.iterrows():
    key = m.league
    rh, ra = R.get((key, m.home_team), 1500.0), R.get((key, m.away_team), 1500.0)
    rows.append((m.match_id, rh + 60 - ra))
    e = 1 / (1 + 10 ** (-(rh + 60 - ra) / 400))
    s = 1.0 if m.hg > m.ag else 0.5 if m.hg == m.ag else 0.0
    k = 20 * np.log1p(abs(m.hg - m.ag)) if m.hg != m.ag else 20
    R[(key, m.home_team)], R[(key, m.away_team)] = rh + k * (s - e), ra - k * (s - e)
elo = pd.DataFrame(rows, columns=["match_id", "d"]).set_index("match_id")
elo = elo.join(df.set_index("match_id")[["season", "actual"]])


def ordlogit(d, a, b):
    """有序 logit：主胜/平/客胜"""
    c1 = 1 / (1 + np.exp(-(d * a - b)))      # P(主胜)
    c2 = 1 / (1 + np.exp(-(d * a + b)))      # P(主胜或平)
    return np.stack([c1, c2 - c1, 1 - c2], 1)


ep = []
for s in ["2324", "2425", "2526", "2627"]:          # 每季用之前所有赛季拟合，无泄漏
    tr = elo[elo.season < s]
    f = lambda x: -np.log(ordlogit(tr.d.values / 100, *x)[np.arange(len(tr)), tr.actual.values] + 1e-12).sum()
    a, b = minimize(f, [0.5, 0.3]).x
    te = elo[elo.season == s]
    ep.append(pd.DataFrame(ordlogit(te.d.values / 100, a, b), index=te.index, columns=["p_h", "p_d", "p_a"]))
P["elo"] = pd.concat(ep)
P["market"] = df.set_index("match_id")[["mc_h", "mc_d", "mc_a"]].set_axis(["p_h", "p_d", "p_a"], axis=1)

ids = base.index
for k in P:
    ids = ids.intersection(P[k].dropna().index)
base = base.loc[ids]
A = {k: P[k].loc[ids].to_numpy() for k in P}
y = base.actual.to_numpy()
sel = base.season.isin(["2324", "2425"]).to_numpy()
con = ~sel


def LL(p):
    return -np.log(np.clip(p[np.arange(len(p)), y], 1e-9, None))


def report(name, p, ref="dc_xg"):
    d = LL(p) - LL(A[ref])
    out = []
    for m in [sel, con]:
        out.append(f"{d[m].mean():+.4f}±{d[m].std(ddof=1)/np.sqrt(m.sum()):.4f}")
    hit = (p.argmax(1) == y)
    print(f"  {name:28} 选择期 {out[0]}  确认期 {out[1]}  确认期命中 {hit[con].mean():.1%}")


def logpool(ps, w):
    """对数线性融合（几何平均后归一化）"""
    z = sum(wi * np.log(np.clip(p, 1e-9, None)) for wi, p in zip(w, ps))
    z = np.exp(z - z.max(1, keepdims=True))
    return z / z.sum(1, keepdims=True)


print(f"\nn={len(y)}  选择期 {sel.sum()}  确认期 {con.sum()}")
print("[单模型] 相对 dc_xg 的 logloss 差（负=更好）")
for k in A:
    report(k, A[k])

print("\n[模型集成，不含市场]")
models = ["dc_goals", "dc_xg", "dc_sot", "elo"]
for r_ in range(2, 5):
    for combo in itertools.combinations(models, r_):
        report("平均:" + "+".join(combo), np.mean([A[k] for k in combo], 0))


def fitw(keys, mask, pool="lin"):
    def f(w):
        w = np.abs(w) / np.abs(w).sum()
        p = sum(wi * A[k] for wi, k in zip(w, keys)) if pool == "lin" else logpool([A[k] for k in keys], w)
        return LL(p)[mask].mean()
    w = minimize(f, np.ones(len(keys)) / len(keys), method="Nelder-Mead").x
    return np.abs(w) / np.abs(w).sum()


w = fitw(models, sel)
print(f"  选择期最优权重 {dict(zip(models, w.round(2)))}")
report("加权集成(选择期权重)", sum(wi * A[k] for wi, k in zip(w, models)))

print("\n[与市场比较] 相对 market（负=比市场好）")
report("market", A["market"], "market")
report("dc_xg", A["dc_xg"], "market")
report("平均:4模型", np.mean([A[k] for k in models], 0), "market")
for keys in [["market", "dc_xg"], ["market", "dc_xg", "elo"], ["market"] + models]:
    for pool in ["lin", "log"]:
        w = fitw(keys, sel, pool)
        p = sum(wi * A[k] for wi, k in zip(w, keys)) if pool == "lin" else logpool([A[k] for k in keys], w)
        report(f"{pool}:{'+'.join(keys)}", p, "market")
        print(f"      权重 {dict(zip(keys, w.round(2)))}")

# 模型间相关：为什么集成提升有限
print("\n[主胜概率相关系数]")
H = pd.DataFrame({k: A[k][:, 0] for k in A})
print(H.corr().round(3).to_string())
