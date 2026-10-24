"""更早数据有没有用：限制训练窗口长度，对比全部历史（2122 起）。测试季 2425–2627（保证全窗口有 3 年以上历史）。"""
import numpy as np
from _diag.explore.harness import load_all, run, paired, ll, hit
df = load_all(); T = ["2425", "2526", "2627"]
full = run(df, {}, tests=T)
print("全部历史", "LL %.4f hit %.3f" % (ll(full).mean(), hit(full).mean()))
for days in [270, 365, 545, 730, 1095]:
    r = run(df, dict(window=days), tests=T)
    n, d, se = paired(r, full)
    print(f"只用近 {days} 天: LL {ll(r).mean():.4f} 与全部历史差 {d:+.4f}±{se:.4f}  hit {hit(r).mean():.3f}")
for xi in [0.002, 0.001]:
    r = run(df, dict(xi=xi), tests=T)
    n, d, se = paired(r, full)
    print(f"衰减变慢 xi={xi}（老数据权重更大）: 差 {d:+.4f}±{se:.4f}")
print("各年龄数据的相对权重 exp(-0.005·天):", {y: round(float(np.exp(-0.005 * 365 * y)), 3) for y in [1, 2, 3, 4]})
