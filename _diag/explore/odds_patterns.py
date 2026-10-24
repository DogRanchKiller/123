"""盘口规律扫描（亚盘 / 大小球 / 胜平负），数据：_cache/fd_raw/*.csv
发现期 2324-2627，样本外 2122+2223。指标：按去水后公平赔率下注的平均回报
（市场无偏 => 期望 0；+3% 表示该方向比市场定价多赢 3% 本金），附 SE。"""
import glob
import numpy as np
import pandas as pd

fr = []
for p in glob.glob("_cache/fd_raw/*.csv"):
    d = pd.read_csv(p, encoding="latin-1")
    lg, s = p.replace("\\", "/").split("/")[-1][:-4].split("_")
    fr.append(d.assign(league=lg, season=s))
df = pd.concat(fr, ignore_index=True).dropna(subset=["FTHG", "FTAG", "AHCh", "AvgCAHH"])
df["m"] = df.FTHG - df.FTAG
df["tot"] = df.FTHG + df.FTAG
df["per"] = np.where(df.season.isin(["2122", "2223"]), "样本外", "发现期")
print(f"n={len(df)}  " + str(df.groupby('per').size().to_dict()))


def fair2(a, b):
    """两项赔率去水 -> (公平赔率a, 公平赔率b, 概率a)"""
    qa, qb = 1 / a, 1 / b
    pa = qa / (qa + qb)
    return 1 / pa, 1 / (1 - pa), pa


def settle(margin, line, odds):
    """亚盘结算：主队净胜 margin，主队让球线 line(-0.75 = 主让0.75)，按 odds 下 1 单位的盈亏"""
    out = np.zeros(len(margin))
    for half in (-0.25, 0.25):
        l2 = np.where(np.isclose((line * 4) % 2, 1), line + half, line)   # 四分之一盘拆两半
        x = margin + l2
        out += np.where(x > 0, (odds - 1) * 0.5, np.where(x < 0, -0.5, 0.0))
    return out


def show(lab, r, m=None):
    parts = []
    for per in ["发现期", "样本外"]:
        mm = (df.per == per).values if m is None else (m & (df.per == per).values)
        x = r[mm]
        x = x[~np.isnan(x)]
        parts.append(f"{per} n={len(x):4d} {x.mean()*100:+5.1f}%±{x.std(ddof=1)/np.sqrt(len(x))*100:3.1f}"
                     if len(x) > 20 else f"{per} n={len(x):4d}   --")
    print(f"  {lab:22} " + "   ".join(parts))


# ---------- A 哪家赔率最准（胜平负 / 大小球 logloss，越低越准）
print("\n[A] 赔率来源准确度  logloss（括号为相对 Pinnacle 收盘）")
y = np.select([df.m > 0, df.m == 0], [0, 1], 2)
srcs = {"平均-赛前": ("AvgH", "AvgD", "AvgA"), "平均-收盘": ("AvgCH", "AvgCD", "AvgCA"),
        "Pinnacle-赛前": ("PSH", "PSD", "PSA"), "Pinnacle-收盘": ("PSCH", "PSCD", "PSCA"),
        "Bet365-赛前": ("B365H", "B365D", "B365A"), "Bet365-收盘": ("B365CH", "B365CD", "B365CA")}
ok = df[[c for v in srcs.values() for c in v]].notna().all(1).values
LLs = {}
for k, cols in srcs.items():
    q = 1 / df[list(cols)].values
    q = q / q.sum(1, keepdims=True)
    LLs[k] = -np.log(q[np.arange(len(df)), y])
for k in srcs:
    d = LLs[k][ok] - LLs["Pinnacle-收盘"][ok]
    print(f"  {k:14} {LLs[k][ok].mean():.4f}  ({d.mean():+.4f}±{d.std(ddof=1)/np.sqrt(ok.sum()):.4f})")
ou = {"平均-收盘": ("AvgC>2.5", "AvgC<2.5"), "Pinnacle-收盘": ("PC>2.5", "PC<2.5"),
      "Bet365-收盘": ("B365C>2.5", "B365C<2.5"), "平均-赛前": ("Avg>2.5", "Avg<2.5")}
ok2 = df[[c for v in ou.values() for c in v]].notna().all(1).values
over = (df.tot > 2.5).values
print("  大小球2.5:")
L2 = {}
for k, (a, b) in ou.items():
    _, _, po = fair2(df[a].values, df[b].values)
    L2[k] = -np.log(np.where(over, po, 1 - po))
ok2 = ok2 & np.all([np.isfinite(v) for v in L2.values()], 0)
print(f"  (有效 n={ok2.sum()})")
for k in ou:
    d = L2[k][ok2] - L2["Pinnacle-收盘"][ok2]
    print(f"  {k:14} {L2[k][ok2].mean():.4f}  ({d.mean():+.4f}±{d.std(ddof=1)/np.sqrt(ok2.sum()):.4f})")

# ---------- B 亚盘收盘：按让球线分档，主队方向回报
print("\n[B] 亚盘收盘偏差：买主队的公平回报，按收盘让球线分档")
fh, fa, ph = fair2(df.AvgCAHH.values, df.AvgCAHA.values)
rh = settle(df.m.values, df.AHCh.values, fh)
L = df.AHCh.values
show("全部(主队方向)", rh)
for lab, mk in [("主让≥1.5", L <= -1.5), ("主让0.75~1.25", (L <= -0.75) & (L > -1.5)),
                ("主让0.25~0.5", (L <= -0.25) & (L > -0.75)), ("平手", L == 0),
                ("主受让0.25~0.5", (L >= 0.25) & (L < 0.75)), ("主受让≥0.75", L >= 0.75)]:
    show(lab, rh, mk)
print("  四分之一盘 vs 半球/整球盘:")
q = np.isclose((L * 4) % 2, 1)
show("四分之一盘(.25/.75)", rh, q)
show("半球盘(.5)", rh, np.isclose(L % 1, 0.5))
show("整球盘(0/1/2)", rh, np.isclose(L % 1, 0))
for lg in ["E0", "D1", "SP1"]:
    show(f"联赛 {lg}", rh, (df.league == lg).values)

# ---------- C 亚盘变动：赛前 -> 收盘
print("\n[C] 亚盘变动：盘口线变化（负=主队被加持）")
dl = (df.AHCh - df.AHh).values
fho, _, pho = fair2(df.AvgAHH.values, df.AvgAHA.values)
rho_ = settle(df.m.values, df.AHh.values, fho)        # 赛前按赛前盘买主
for lab, mk in [("主被加持(线升)", dl < 0), ("线不变", dl == 0), ("主被削弱(线降)", dl > 0)]:
    show(lab + "·赛前买主", rho_, mk)
    show(lab + "·收盘买主", rh, mk)
# 线不变时看水位变化
same = dl == 0
dp = ph - pho
print("  线不变，仅水位变化（主队公平概率变化）:")
for lab, mk in [("主水降>3pp(被加持)", same & (dp > 0.03)), ("水位基本不动", same & (abs(dp) <= 0.03)),
                ("主水升>3pp(被抛)", same & (dp < -0.03))]:
    show(lab + "·赛前买主", rho_, mk)
    show(lab + "·收盘买主", rh, mk)

# ---------- D 大小球 2.5
print("\n[D] 大小球2.5：买大球的公float回报".replace("float", "平"))
fo, fu, po = fair2(df["AvgC>2.5"].values, df["AvgC<2.5"].values)
ro = np.where(over, fo - 1, -1.0)
show("全部(大球方向)", ro)
for lab, mk in [("收盘大球<45%", po < 0.45), ("45~55%", (po >= 0.45) & (po < 0.55)),
                ("55~65%", (po >= 0.55) & (po < 0.65)), ("≥65%", po >= 0.65)]:
    show(lab, ro, mk)
for lg in ["E0", "D1", "SP1"]:
    show(f"联赛 {lg}", ro, (df.league == lg).values)
foo, _, poo = fair2(df["Avg>2.5"].values, df["Avg<2.5"].values)
roo = np.where(over, foo - 1, -1.0)
dpo = po - poo
print("  大小球变动:")
for lab, mk in [("大球被加持>3pp", dpo > 0.03), ("基本不动", abs(dpo) <= 0.03), ("大球被抛>3pp", dpo < -0.03)]:
    show(lab + "·赛前买大", roo, mk)
    show(lab + "·收盘买大", ro, mk)

# ---------- E Bet365 与 Pinnacle 分歧时听谁的
print("\n[E] Bet365 与 Pinnacle 收盘分歧（主胜概率差>2pp）时，实际更接近谁")
qb = 1 / df[["B365CH", "B365CD", "B365CA"]].values
qb = qb / qb.sum(1, keepdims=True)
qp = 1 / df[["PSCH", "PSCD", "PSCA"]].values
qp = qp / qp.sum(1, keepdims=True)
gap = qb[:, 0] - qp[:, 0]
hw = (df.m > 0).values.astype(float)
for lab, mk in [("Bet365 更看好主 >2pp", gap > 0.02), ("Pinnacle 更看好主 >2pp", gap < -0.02)]:
    for per in ["发现期", "样本外"]:
        mm = ok & mk & (df.per == per).values
        a = hw[mm].mean()
        print(f"  {lab:20} {per} n={mm.sum():4d} B365 {qb[mm,0].mean():.1%} Pinnacle {qp[mm,0].mean():.1%} 实际 {a:.1%} ±{np.sqrt(a*(1-a)/max(mm.sum(),1)):.1%}")

# ---------- F 盘口之间是否一致：亚盘线 vs 胜平负隐含
print("\n[F] 亚盘与胜平负的一致性：同一胜平负概率下，亚盘开得更深/更浅的比赛")
pc = 1 / df[["AvgCH", "AvgCD", "AvgCA"]].values
pc = pc / pc.sum(1, keepdims=True)
sup = pc[:, 0] - pc[:, 2]
coef = np.polyfit(sup, L + 0.5 * (ph - 0.5) * 0, 1)   # 用胜平负预测亚盘线
resid = L - np.polyval(coef, sup)
for lab, mk in [("亚盘比胜平负更看好主", resid < -0.15), ("一致", abs(resid) <= 0.15), ("亚盘比胜平负更看淡主", resid > 0.15)]:
    show(lab, rh, mk)

# ---------- G 深盘合并检验（两期合计）+ 同场胜平负对照
print("\n[G] 主让≥1.5 合并两期")
mk = L <= -1.5
for lab, r in [("亚盘买主(收盘)", rh), ("亚盘买客(收盘)", settle(-df.m.values, -L, fa))]:
    x = r[mk]
    print(f"  {lab} n={len(x)} {x.mean()*100:+.1f}%±{x.std(ddof=1)/np.sqrt(len(x))*100:.1f}")
a = (df.m.values[mk] > 0).mean()
print(f"  同批比赛 胜平负: 收盘主胜 {pc[mk,0].mean():.1%} 实际 {a:.1%}; 平均净胜 {df.m.values[mk].mean():.2f} 球, 收盘让 {-L[mk].mean():.2f}")
