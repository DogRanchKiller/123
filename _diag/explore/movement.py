"""盘口变动分析：赛前1-3天赔率(mo) -> 收盘赔率(mc)
问题：1) 收盘是否比初盘准  2) 变动方向是信息还是陷阱(跟/反/无)
      3) 热门大球队是否被高估(热度溢价)  4) 模型与变动同向/反向时谁对
"""
import numpy as np
import pandas as pd

from _diag.explore.harness import load_all

df = load_all()
df = df[df.season.isin(["2324", "2425", "2526", "2627"])].dropna(subset=["mo_h", "mc_h"]).copy()
Y = np.eye(3)[df.actual.values]
O = df[["mo_h", "mo_d", "mo_a"]].values
C = df[["mc_h", "mc_d", "mc_a"]].values
print(f"n={len(df)}")


def ll(P):
    return -np.log(np.clip((P * Y).sum(1), 1e-12, None))


def hit(P):
    return (P.argmax(1) == df.actual.values)


d = ll(C) - ll(O)
print(f"[1] 收盘-初盘 logloss diff={d.mean():+.4f} ± {d.std(ddof=1)/np.sqrt(len(d)):.4f}  "
      f"命中 初盘{hit(O).mean():.1%} 收盘{hit(C).mean():.1%}")

# [2] 变动幅度分桶：主胜概率变化 move = mc_h - mo_h
df["move"] = C[:, 0] - O[:, 0]
print(f"\n|move| 分布: 中位 {df.move.abs().median()*100:.1f}pp, >3pp 占 {(df.move.abs()>0.03).mean():.0%}, "
      f">5pp 占 {(df.move.abs()>0.05).mean():.0%}")
bins = [-1, -0.05, -0.03, -0.01, 0.01, 0.03, 0.05, 1]
labs = ["主降>5", "主降3-5", "主降1-3", "基本不动", "主升1-3", "主升3-5", "主升>5"]
df["mb"] = pd.cut(df.move, bins, labels=labs)
print("\n[2] 按主胜概率变动分桶：实际主胜率 vs 初盘/收盘隐含")
print(f"{'桶':8}{'n':>6}{'初盘':>8}{'收盘':>8}{'实际':>8}{'实际-收盘':>10}{'SE':>7}")
for b in labs:
    g = df[df.mb == b]
    if len(g) < 30:
        continue
    a = (g.actual == 0).mean()
    se = np.sqrt(a * (1 - a) / len(g))
    print(f"{b:8}{len(g):6d}{g.mo_h.mean():8.1%}{g.mc_h.mean():8.1%}{a:8.1%}"
          f"{(a-g.mc_h.mean())*100:+9.1f}pp{se*100:6.1f}")

# [2b] 以"变动前的热门"为主体：热门被加持(steam) vs 热门被抛(drift)
fav = O.argmax(1)
po, pc = O[np.arange(len(df)), fav], C[np.arange(len(df)), fav]
win = (df.actual.values == fav)
print("\n[2b] 初盘热门：收盘时被加持还是被抛弃")
for name, m in [("加持>3pp", pc - po > 0.03), ("小幅", np.abs(pc - po) <= 0.03), ("被抛>3pp", pc - po < -0.03)]:
    a = win[m].mean()
    print(f"  {name:8} n={m.sum():5d} 初盘{po[m].mean():.1%} 收盘{pc[m].mean():.1%} 实际{a:.1%} "
          f"(实际-收盘 {(a-pc[m].mean())*100:+.1f}pp ±{np.sqrt(a*(1-a)/m.sum())*100:.1f})")

# [2c] 平局概率变动
dmove = C[:, 1] - O[:, 1]
print("\n[2c] 平局概率变动")
for name, m in [("平升>2pp", dmove > 0.02), ("不动", np.abs(dmove) <= 0.02), ("平降>2pp", dmove < -0.02)]:
    a = (df.actual.values[m] == 1).mean()
    print(f"  {name:8} n={m.sum():5d} 收盘平{C[m,1].mean():.1%} 实际平{a:.1%} "
          f"({(a-C[m,1].mean())*100:+.1f}pp ±{np.sqrt(a*(1-a)/m.sum())*100:.1f})")

# [3] 热度溢价：大球队(公众热门)是否被高估
BIG = {"Man City", "Man United", "Liverpool", "Arsenal", "Chelsea", "Tottenham",
       "Bayern Munich", "Dortmund", "Barcelona", "Real Madrid", "Ath Madrid"}
print("\n[3] 大球队热度溢价：大球队一方的收盘隐含 vs 实际胜率")
rows = []
for side, col, k in [("主", "home_team", 0), ("客", "away_team", 2)]:
    m = df[col].isin(BIG).values & ~df[["home_team", "away_team"]].isin(BIG).all(1).values
    rows.append((side, m, k))
tot_n, tot_imp, tot_act = 0, 0.0, 0.0
for side, m, k in rows:
    a = (df.actual.values[m] == k).mean()
    print(f"  大球队作{side} n={m.sum():4d} 收盘{C[m,k].mean():.1%} 实际{a:.1%} "
          f"({(a-C[m,k].mean())*100:+.1f}pp ±{np.sqrt(a*(1-a)/m.sum())*100:.1f})")
    tot_n += m.sum(); tot_imp += C[m, k].sum(); tot_act += (df.actual.values[m] == k).sum()
a = tot_act / tot_n
print(f"  合计 n={tot_n} 收盘{tot_imp/tot_n:.1%} 实际{a:.1%} ({(a-tot_imp/tot_n)*100:+.1f}pp ±{np.sqrt(a*(1-a)/tot_n)*100:.1f})")
missing = BIG - set(df.home_team)
if missing:
    print("  (名称未匹配:", missing, ")")

# [4] 模型与变动方向的关系
try:
    fp = pd.read_csv("_diag/explore/final_preds.csv")
    j = df.merge(fp[["match_id", "p_h", "p_d", "p_a"]], on="match_id")
    Mo = j[["p_h", "p_d", "p_a"]].values
    Oj, Cj = j[["mo_h", "mo_d", "mo_a"]].values, j[["mc_h", "mc_d", "mc_a"]].values
    mv = Cj[:, 0] - Oj[:, 0]
    gap = Mo[:, 0] - Oj[:, 0]   # 模型相对初盘看高主胜
    print(f"\n[4] 模型 vs 初盘的分歧，能否预测盘口往哪走 (n={len(j)})")
    print(f"  corr(模型-初盘, 收盘-初盘) = {np.corrcoef(gap, mv)[0,1]:+.3f}")
    for name, m in [("模型看高主>5pp", gap > 0.05), ("模型看低主>5pp", gap < -0.05)]:
        print(f"  {name}: n={m.sum()} 盘口平均移动 {mv[m].mean()*100:+.2f}pp, 同向比例 {(np.sign(mv[m])==np.sign(gap[m])).mean():.0%}")
except FileNotFoundError:
    print("final_preds.csv 不存在，跳过[4]")
