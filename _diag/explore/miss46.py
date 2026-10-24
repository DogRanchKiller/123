"""市场首选猜错的那 46%：是什么、能不能被我们的模型挑出来。
样本外回测 2324–2627，主模型（xG DC，每月重拟合）vs 市场赛前平均赔率 / 收盘赔率。"""
import numpy as np
import pandas as pd
from _diag.explore.harness import load_all, run

df = load_all()
r = run(df, {}).merge(df[["match_id", "mo_h", "mo_d", "mo_a", "mc_h", "mc_d", "mc_a"]],
                      on="match_id").dropna(subset=["mo_h", "mc_h"])
y = r.actual.to_numpy()
P = r[["p_h", "p_d", "p_a"]].to_numpy()
LAB = np.array(["主胜", "平", "客胜"])
print(f"样本 {len(r)} 场；实际 主胜 {np.mean(y == 0):.1%} 平 {np.mean(y == 1):.1%} 客胜 {np.mean(y == 2):.1%}\n")

for tag, name in [("mo", "赛前平均赔率"), ("mc", "收盘赔率")]:
    Q = r[[f"{tag}_h", f"{tag}_d", f"{tag}_a"]].to_numpy()
    qm, pm = Q.argmax(1), P.argmax(1)
    print(f"===== 市场 = {name} =====")
    print(f"命中率  市场 {np.mean(qm == y):.1%}   模型 {np.mean(pm == y):.1%}")
    print(f"如果市场概率就是真实概率，理论命中率 = 平均最大概率 = {Q.max(1).mean():.1%}"
          f"（模型自评 {P.max(1).mean():.1%}）")
    miss = qm != y
    print(f"\n[1] 市场猜错 {miss.sum()} 场（{miss.mean():.1%}），实际结果：")
    print(f"    平局 {np.mean(y[miss] == 1):.1%}   冷门一方赢 {np.mean(y[miss] != 1):.1%}")
    print(f"    市场首选为平局的场次：{np.sum(qm == 1)}  模型首选为平局：{np.sum(pm == 1)}")

    dis = qm != pm
    print(f"\n[2] 模型与市场首选不同 {dis.sum()} 场（{dis.mean():.1%}）")
    print(f"    这些场次：市场对 {np.mean(qm[dis] == y[dis]):.1%}  模型对 {np.mean(pm[dis] == y[dis]):.1%}"
          f"  都错 {np.mean((qm[dis] != y[dis]) & (pm[dis] != y[dis])):.1%}")
    print(f"    在市场猜错的 {miss.sum()} 场里，模型救回 {np.sum(miss & (pm == y))} 场"
          f"；在市场猜对的场次里，模型弄错 {np.sum(~miss & (pm != y))} 场")

    # [3] 模型比市场更看好某结果时，这个结果真的更常发生吗？
    D = (P - Q).ravel()
    A = (y[:, None] == np.arange(3)).ravel().astype(float)
    QQ, PP = Q.ravel(), P.ravel()
    b = pd.cut(D, [-1, -0.08, -0.04, -0.015, 0.015, 0.04, 0.08, 1])
    t = pd.DataFrame({"b": b, "q": QQ, "p": PP, "a": A}).groupby("b", observed=True).agg(
        n=("a", "size"), 市场概率=("q", "mean"), 模型概率=("p", "mean"), 实际发生=("a", "mean"))
    t["SE"] = np.sqrt(t.实际发生 * (1 - t.实际发生) / t.n)
    print("\n[3] 按 模型−市场 的分歧分组（每场 3 个结果各算一行）：实际发生率更接近谁？")
    print(t.round(3).to_string())

    # [4] 平局能不能挑出来
    print("\n[4] 平局：按概率分组的实际平局率")
    for src, pdraw in [("模型", P[:, 1]), ("市场", Q[:, 1])]:
        g = pd.DataFrame({"p": pdraw, "a": y == 1}).groupby(
            pd.cut(pdraw, [0, 0.2, 0.24, 0.27, 0.30, 0.33, 1]), observed=True).agg(
            n=("a", "size"), 预测平局=("p", "mean"), 实际平局=("a", "mean"))
        print(f"  {src}\n" + g.round(3).to_string())
    print()
