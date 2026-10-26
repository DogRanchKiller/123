"""读 rows_*.csv：自研（dc_sot / Elo）对市场的同场差值，老五联赛 vs 新六联赛；1X2 与亚盘（市场线）。
融合：1X2 用对数线性池 p ∝ 市场^(1−w)·模型^w；亚盘用 λ 几何融合 log λ = (1−w)·log λ市场 + w·log λ模型，
再套 dc_matrix(rho=−0.05)。w 只在 2324–2425 上选，2526（留出）和 2627（本季已赛）只作检验。
用法：PYTHONPATH=. python _diag/own_model/analyze.py > _diag/own_model/result.txt
"""
import glob

import numpy as np
import pandas as pd

from football_prediction.model_market.implied import DEFAULT_RHO, dc_matrix
from football_prediction.output.derive import AH_KEYS, ah_outcome, margin_pmf
from football_prediction.review.store import ah_scores

OLD = ["E0", "D1", "SP1", "I1", "F1"]
NEW = ["E1", "N1", "P1", "SC0", "B1", "T1"]
SEL, EVAL = ["2324", "2425"], ["2526", "2627"]
W1 = np.round(np.arange(0, 0.61, 0.05), 2)
W_AH = np.round(np.arange(0, 0.51, 0.1), 2)

d = pd.concat([pd.read_csv(f, dtype={"season": str}) for f in glob.glob("_diag/own_model/rows_*.csv")])
d["grp"] = np.where(d.league.isin(OLD), "老五", "新六")
y = np.select([d.home_goals > d.away_goals, d.home_goals == d.away_goals], [0, 1], 2)
P = {m: d[[f"{m}_h", f"{m}_d", f"{m}_a"]].to_numpy() for m in ("mk", "sot", "elo")}
idx = np.arange(len(d))


def ll(p):
    return -np.log(np.clip(p[idx, y], 1e-7, None))


def pool(pa, pb, w):
    q = np.clip(pa, 1e-9, None) ** (1 - w) * np.clip(pb, 1e-9, None) ** w
    return q / q.sum(1, keepdims=True)


def cmp(a, b, mask):
    x = (a - b)[mask & ~np.isnan(a - b)]
    return len(x), x.mean(), x.std(ddof=1) / np.sqrt(len(x))


def fmt(n, m, se):
    flag = "显著" if abs(m) > 2 * se else "不显著"
    return f"n={n:5d}  差={m:+.4f} ±{se:.4f}（{flag}）"


def ah_cols(prefix):
    cols = [f"ah_{prefix}_{k}" for k in AH_KEYS]
    return d[cols].to_numpy()


def ah_eval(probs):
    """probs: (n,5) 或 NaN 行 → (ll, hit) 数组"""
    out_ll, out_hit = np.full(len(d), np.nan), np.full(len(d), np.nan)
    for i, (p, hg, ag, line) in enumerate(zip(probs, d.home_goals, d.away_goals, d.ah_line)):
        if np.isnan(p).any():
            continue
        a, h = ah_scores({f"ah_{float(line) + 0.0:+.2f}": list(p)}, int(hg), int(ag), line)
        out_ll[i] = a
        out_hit[i] = np.nan if h is None else h
    return out_ll, out_hit


def ah_blend(w):
    lh = np.exp((1 - w) * np.log(d.lam_mk_h) + w * np.log(d.lam_sot_h)).to_numpy()
    la = np.exp((1 - w) * np.log(d.lam_mk_a) + w * np.log(d.lam_sot_a)).to_numpy()
    res = np.full((len(d), 5), np.nan)
    for i, (a, b, line) in enumerate(zip(lh, la, d.ah_line)):
        if np.isnan(a) or np.isnan(line):
            continue
        o = ah_outcome(margin_pmf(dc_matrix(a, b, DEFAULT_RHO)), float(line))
        res[i] = [o[k] for k in AH_KEYS]
    return res


L = {m: ll(P[m]) for m in P}
hit = {m: (P[m].argmax(1) == y).astype(float) for m in P}
mk_ah_ll, mk_ah_hit = ah_eval(ah_cols("mk"))
sot_ah_ll, sot_ah_hit = ah_eval(ah_cols("sot"))
season = d.season.to_numpy()
grp = d.grp.to_numpy()
lg = d.league.to_numpy()

print("== 1. 自研 vs 市场：1X2 log loss 同场差（负 = 自研更好），2324–2627 全部 ==")
for g in ("老五", "新六"):
    for m in ("sot", "elo"):
        n, mu, se = cmp(L[m], L["mk"], grp == g)
        print(f"{g} {m:4s} {fmt(n, mu, se)}  命中 {hit[m][grp == g].mean():.3f} vs 市场 {hit['mk'][grp == g].mean():.3f}")
print()
print("== 2. 按联赛（dc_sot − 市场，1X2 LL）==")
for x in OLD + NEW:
    n, mu, se = cmp(L["sot"], L["mk"], lg == x)
    n2, mu2, se2 = cmp(L["elo"], L["mk"], lg == x)
    print(f"{x:4s} sot {fmt(n, mu, se)} | elo 差={mu2:+.4f} ±{se2:.4f}")
print()
print("== 3. 亚盘（赛前市场线，五种结算 LL；命中不含走盘）dc_sot − 市场隐含 ==")
for g in ("老五", "新六"):
    mask = grp == g
    n, mu, se = cmp(sot_ah_ll, mk_ah_ll, mask)
    hm = ~np.isnan(mk_ah_hit) & ~np.isnan(sot_ah_hit) & mask
    print(f"{g} {fmt(n, mu, se)}  命中 sot {sot_ah_hit[hm].mean():.3f} vs 市场 {mk_ah_hit[hm].mean():.3f}（n={hm.sum()}）")
for x in OLD + NEW:
    n, mu, se = cmp(sot_ah_ll, mk_ah_ll, lg == x)
    print(f"  {x:4s} {fmt(n, mu, se)}")
print()
print("== 4. 亚盘方向分歧：自研和市场选边不同的场次，谁对 ==")
side_mk = (ah_cols("mk") @ np.array([1, .5, 0, -.5, -1])) >= 0
side_sot = (ah_cols("sot") @ np.array([1, .5, 0, -.5, -1])) >= 0
dec = ~np.isnan(mk_ah_hit)
for g in ("老五", "新六"):
    dis = (side_mk != side_sot) & dec & (grp == g)
    agr = (side_mk == side_sot) & dec & (grp == g)
    print(f"{g} 分歧 {dis.sum()} 场（{dis.sum() / (dec & (grp == g)).sum():.1%}）：市场对 {mk_ah_hit[dis].mean():.3f}，"
          f"自研对 {sot_ah_hit[dis].mean():.3f}；一致场命中 {mk_ah_hit[agr].mean():.3f}")
print()
print("== 5. 融合 1X2：w 在 2324–2425 选，2526 / 2627 检验（融合 − 市场）==")
for g in ("老五", "新六"):
    for m in ("sot", "elo"):
        sel = (grp == g) & np.isin(season, SEL)
        scores = [np.nanmean(ll(pool(P["mk"], P[m], w))[sel] - L["mk"][sel]) for w in W1]
        w = W1[int(np.argmin(scores))]
        b = ll(pool(P["mk"], P[m], w))
        line = f"{g} {m:4s} 选 w={w:.2f}（选参段 {min(scores):+.4f}）"
        for s in EVAL:
            n, mu, se = cmp(b, L["mk"], (grp == g) & (season == s))
            line += f" | {s} {mu:+.4f}±{se:.4f}"
        print(line)
print()
print("== 6. 融合亚盘（λ 几何融合 dc_sot）：w 在 2324–2425 选 ==")
blends = {w: ah_eval(ah_blend(w)) for w in W_AH}
for g in ("老五", "新六"):
    sel = (grp == g) & np.isin(season, SEL)
    scores = {w: np.nanmean(blends[w][0][sel] - mk_ah_ll[sel]) for w in W_AH}
    print(f"{g} 选参段各 w：" + "  ".join(f"{w:.1f}:{v:+.4f}" for w, v in scores.items()))
    w = min(scores, key=scores.get)
    bl, bh = blends[w]
    line = f"{g} 选 w={w:.1f}"
    for s in EVAL:
        mask = (grp == g) & (season == s)
        n, mu, se = cmp(bl, mk_ah_ll, mask)
        hm = mask & ~np.isnan(bh) & ~np.isnan(mk_ah_hit)
        line += f" | {s} LL {mu:+.4f}±{se:.4f} 命中 {bh[hm].mean():.3f} vs {mk_ah_hit[hm].mean():.3f}"
    print(line)
