"""读 rows_*.csv：各变体对 base 的同场差（负 = 变体更好），选参段 2122–2425，检验段 2526–2627；
再看 base 亚盘赢盘概率的校准与 AH_TIERS 档位命中。
用法：PYTHONPATH=. python _diag/algo_sweep/analyze.py > _diag/algo_sweep/result.txt
"""
import glob

import numpy as np
import pandas as pd

from football_prediction.output.analysis import AH_TIERS

d = pd.concat([pd.read_csv(f, dtype={"season": str}) for f in sorted(glob.glob("_diag/algo_sweep/rows_*.csv"))])
SEL = d.season.isin(["2122", "2223", "2324", "2425"]).to_numpy()
VARS = ["shin", "power", "rho0", "rho10", "ah3", "only1x2", "pin1x2", "close"]
MET = [("ll1", "1X2 LL"), ("llah", "亚盘 LL"), ("llou", "大小 LL")]


def diff(a, b, mask):
    x = (d[a] - d[b]).to_numpy()[mask]
    x = x[~np.isnan(x)]
    return f"{x.mean():+.4f}±{x.std(ddof=1) / np.sqrt(len(x)):.4f}"


print(f"n={len(d)}（选参段 {SEL.sum()}，检验段 {(~SEL).sum()}）")
print("base 绝对值：" + "  ".join(f"{t} {d['base_' + m].mean():.4f}" for m, t in MET)
      + f"  1X2命中 {d.base_hit1.mean():.4f}  亚盘命中 {d.base_hitah.mean():.4f}")
print()
print("== 变体 − base：选参段 | 检验段 ==")
for v in VARS:
    parts = []
    for m, t in MET:
        parts.append(f"{t} {diff(f'{v}_{m}', f'base_{m}', SEL)} | {diff(f'{v}_{m}', f'base_{m}', ~SEL)}")
    h1 = d[f"{v}_hit1"].mean() - d.base_hit1.mean()
    hm = d[[f"{v}_hitah", "base_hitah"]].dropna()
    print(f"{v:8s} " + "；".join(parts) + f"；命中差 1X2 {h1:+.4f} 亚盘 {hm.iloc[:, 0].mean() - hm.iloc[:, 1].mean():+.4f}")
print()
print("== base 亚盘选边赢盘概率（不含走盘份额）分箱：预测 vs 实际 ==")
pc = d.base_cover / (d.base_cover + d.base_coverlose)
side = np.maximum(pc, 1 - pc)
hit = d.base_hitah
bins = [0.5, 0.52, 0.54, 0.56, 0.58, 0.62, 1.0]
for lo, hi in zip(bins[:-1], bins[1:]):
    m = (side >= lo) & (side < hi) & hit.notna()
    for name, seg in (("选参", SEL), ("检验", ~SEL)):
        mm = m & seg
        if mm.sum():
            print(f"[{lo:.2f},{hi:.2f}) {name} n={mm.sum():5d} 预测 {side[mm].mean():.3f} 实际 {hit[mm].mean():.3f}")
print()
print("== AH_TIERS 档位命中（现行阈值）==")
for i, (thr, tier, exp) in enumerate(AH_TIERS):
    upper = AH_TIERS[i - 1][0] if i else 1.01
    m = (side >= thr) & (side < upper) & hit.notna()
    for name, seg in (("选参", SEL), ("检验", ~SEL)):
        mm = m & seg
        print(f"{tier} 阈值 {thr} 标定 {exp} {name} n={mm.sum():5d} 实际 {hit[mm].mean():.3f}")
print()
print("== 按线型（整数 / 半球 / 四分之一）base 亚盘命中 ==")
frac = (d.ah_line.abs() * 4 % 4).astype(int)
for k, name in ((0, "整数"), (2, "半球"), (1, "四分之一"), (3, "四分之三")):
    m = (frac == k) & hit.notna()
    print(f"{name} n={m.sum():5d} 命中 {hit[m].mean():.3f}  平均选边概率 {side[m].mean():.3f}")
