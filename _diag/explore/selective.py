"""只挑有把握的场次预测：按首选概率阈值，覆盖率 vs 命中率（市场赛前赔率 / 模型）。"""
import numpy as np
from _diag.explore.harness import load_all, run
df = load_all()
r = run(df, {}).merge(df[["match_id", "mo_h", "mo_d", "mo_a"]], on="match_id").dropna(subset=["mo_h"])
y = r.actual.to_numpy()
for name, cols in [("市场", ["mo_h", "mo_d", "mo_a"]), ("模型", ["p_h", "p_d", "p_a"])]:
    Q = r[cols].to_numpy(); top = Q.max(1); ok = Q.argmax(1) == y
    s = np.sort(Q, 1); ok2 = (Q.argsort(1)[:, -2:] == y[:, None]).any(1)
    print(name)
    for th in [0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]:
        k = top >= th
        print(f"  首选概率≥{th:.2f}: 覆盖 {k.mean():5.1%} ({k.sum():4d}场)  首选命中 {ok[k].mean():.1%}  双选命中 {ok2[k].mean():.1%}")
