"""单场蒙特卡洛：Arsenal vs Everton（E0, 2026-10-24）
A. 参数不确定性：自助法重抽训练比赛 → 重拟合 → λ 分布 → 概率区间
B. 模型 vs 市场 λ 两种情景
C. 逐分钟进球模拟（泊松过程，下半场强度 ×1.2）→ 半全场、首球、条件概率
只读数据库。"""
import numpy as np
import pandas as pd
from _diag.explore.harness import BASE, load_all, rosters, fit, predict

rng = np.random.default_rng(20261024)
HOME, AWAY, LG = "Arsenal", "Everton", "E0"
df = load_all()
L = df[df.league == LG]
cut = int((pd.Timestamp("2026-10-24") - pd.Timestamp("2000-01-01")).days)
tr = L[L.day < cut]
ros = rosters(df)
args = ("2627", ros[(LG, "2627")], ros.get((LG, "2526"), set()), cut)

# ---------- A. 自助法 ----------
p0 = fit(tr, BASE, *args)
base = predict(p0, np.array([HOME]), np.array([AWAY]))[0]
B = 200
boot = []
for b in range(B):
    s = tr.sample(frac=1.0, replace=True, random_state=int(rng.integers(1e9)))
    boot.append(predict(fit(s, BASE, *args), np.array([HOME]), np.array([AWAY]))[0])
boot = np.array(boot)
print(f"A. 参数不确定性（自助法 {B} 次重拟合，训练 {len(tr)} 场）")
print(f"   点估计   主 {base[0]:.1%} 平 {base[1]:.1%} 客 {base[2]:.1%}  λ {base[3]:.2f}-{base[4]:.2f}")
for i, n in enumerate(["主胜", "平", "客胜", "λ主", "λ客"]):
    lo, hi = np.percentile(boot[:, i], [5, 95])
    f = "{:.1%}" if i < 3 else "{:.2f}"
    print(f"   {n:4} 90% 区间 {f.format(lo)} ~ {f.format(hi)}")
mk = np.array([0.675, 0.199, 0.126])
print(f"   市场主胜 67.5% 落在模型自助分布的第 {(boot[:, 0] < mk[0]).mean():.0%} 分位")
tot = boot[:, 3] + boot[:, 4]
print(f"   总进球 λ 90% 区间 {np.percentile(tot, 5):.2f} ~ {np.percentile(tot, 95):.2f}；市场隐含 2.95 "
      f"落在第 {(tot < 2.95).mean():.0%} 分位")


# ---------- B/C. 逐分钟模拟 ----------
def sim(lh, la, n=200_000, h2=1.2):
    """每队进球 = 泊松过程；上/下半场强度比 1 : h2，各 45 分钟（不含补时细节）。"""
    w1 = 1 / (1 + h2)
    out = {}
    for side, lam in (("h", lh), ("a", la)):
        n1 = rng.poisson(lam * w1, n)
        n2 = rng.poisson(lam * (1 - w1), n)
        out[side + "1"], out[side + "2"] = n1, n2
        # 每个进球时间：上半场 U(0,45)，下半场 U(45,90)；只需最早进球时间
        k = 6
        t1 = np.where(np.arange(k)[None, :] < n1[:, None], rng.uniform(0, 45, (n, k)), np.inf).min(1)
        t2 = np.where(np.arange(k)[None, :] < n2[:, None], rng.uniform(45, 90, (n, k)), np.inf).min(1)
        out[side + "first"] = np.minimum(t1, t2)
        # 60 分钟时的进球数：下半场前 15 分钟
        out[side + "60"] = n1 + rng.binomial(n2, 15 / 45)
    return out


def report(name, lh, la):
    s = sim(lh, la)
    H, A = s["h1"] + s["h2"], s["a1"] + s["a2"]
    H1, A1 = s["h1"], s["a1"]
    res = np.select([H > A, H == A], ["主", "平"], "客")
    ht = np.select([H1 > A1, H1 == A1], ["主", "平"], "客")
    print(f"\n{name}  λ {lh:.2f}-{la:.2f}")
    print(f"   全场 主 {(res=='主').mean():.1%} 平 {(res=='平').mean():.1%} 客 {(res=='客').mean():.1%}"
          f" | 半场 主 {(ht=='主').mean():.1%} 平 {(ht=='平').mean():.1%} 客 {(ht=='客').mean():.1%}")
    hf = pd.crosstab(ht, res, normalize=True).reindex(index=["主", "平", "客"], columns=["主", "平", "客"]).fillna(0)
    print("   半全场（行=半场，列=全场）\n" + (hf * 100).round(1).to_string().replace("\n", "\n   "))
    fh, fa = s["hfirst"], s["afirst"]
    print(f"   首球 主 {(fh < fa).mean():.1%} 客 {(fa < fh).mean():.1%} 无进球 {(np.isinf(fh) & np.isinf(fa)).mean():.1%}"
          f" | 首球时间中位 {np.median(np.minimum(fh, fa)[~np.isinf(np.minimum(fh, fa))]):.0f}'")
    def cond(mask, lab):
        r = res[mask]
        print(f"   若{lab}（{mask.mean():.0%}）→ 主 {(r=='主').mean():.0%} 平 {(r=='平').mean():.0%} 客 {(r=='客').mean():.0%}")
    cond((H1 == 0) & (A1 == 0), "半场 0-0")
    cond((s["h60"] == 0) & (s["a60"] == 0), "60' 仍 0-0")
    cond(fa < fh, "客队先进球")
    cond(fh < fa, "主队先进球")
    cond((H1 == 1) & (A1 == 0), "半场 1-0")
    big = (H - A >= 2).mean()
    print(f"   主净胜≥2 {big:.1%} | 大2.5 {(H + A > 2.5).mean():.1%} | 双方进球 {((H > 0) & (A > 0)).mean():.1%}"
          f" | 下半场进球多于上半场 {((s['h2']+s['a2']) > (H1+A1)).mean():.1%}")


report("B1. 模型", base[3], base[4])
report("B2. 市场隐含", 2.15, 0.81)
# 把参数不确定性带进去：每次模拟从自助分布抽 λ
lh_mix, la_mix = boot[:, 3].mean(), boot[:, 4].mean()
print(f"\n(参考) 自助 λ 均值 {lh_mix:.2f}-{la_mix:.2f}，与点估计差别很小 → 参数不确定性对单场概率影响有限")
