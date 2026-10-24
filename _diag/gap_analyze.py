"""诊断第 1 步（分析）：把 DC − 市场 的同场 Log Loss 差拆到各维度。差值正=DC 更差。"""
import numpy as np
import pandas as pd
from football_prediction.data.loader import init_db

df = pd.read_csv("_diag/gap_matches.csv", dtype={"season": str})
df["diff"] = df["log_loss_dc"] - df["log_loss_mk"]

# 升级队：本赛季出现、上赛季同联赛未出现
conn = init_db("football.db")
teams = pd.read_sql_query(
    "SELECT DISTINCT league, season, home_team AS team FROM matches", conn)
prev = {"2425": "2324", "2526": "2425"}
promoted = set()
for (lg, s), g in teams.groupby(["league", "season"]):
    if s in prev:
        before = set(teams[(teams.league == lg) & (teams.season == prev[s])].team)
        promoted |= {(lg, s, t) for t in set(g.team) - before}
df["promoted"] = [
    (lg, s, h) in promoted or (lg, s, a) in promoted
    for lg, s, h, a in zip(df.league, df.season, df.home_team, df.away_team)]

# 赛季阶段：按月份
mon = pd.to_datetime(df.match_date).dt.month
df["phase"] = np.select([mon.isin([8, 9, 10]), mon.isin([11, 12, 1, 2])],
                        ["1 前段(8-10月)", "2 中段(11-2月)"], "3 后段(3-5月)")


def summ(g):
    n = len(g)
    return pd.Series({"场数": n, "差值": g["diff"].mean(),
                      "SE": g["diff"].std(ddof=1) / np.sqrt(n),
                      "占总差距": g["diff"].sum()})


def show(title, by):
    r = df.groupby(by).apply(summ, include_groups=False)
    for keys in r.index:
        grp = keys[:-1] if isinstance(keys, tuple) and len(keys) > 1 else ()
        mask = np.ones(len(df), bool)
        for col, v in zip(by[:-1], grp):
            mask &= df[col] == v
        r.loc[keys, "占总差距"] /= df.loc[mask, "diff"].sum()
    print(f"\n--- {title} ---")
    print(r.to_string(float_format=lambda x: f"{x:+.4f}"))


pd.set_option("display.width", 200)
show("总体（联赛×赛季）", ["league", "season"])
show("是否涉及升级队（按赛季）", ["season", "promoted"])
show("赛季阶段（按赛季）", ["season", "phase"])
show("升级队 × 阶段（两季合并）", ["promoted", "phase"])

# 结果频率：平均预测概率 vs 实际
print("\n--- 平均预测概率 vs 实际频率（两季合并） ---")
act = pd.get_dummies(df.actual)
rows = []
for o in ["home_win", "draw", "away_win"]:
    rows.append({"结果": o, "实际": act[o].mean(),
                 "DC": df[f"p_{o}_dc"].mean(), "市场": df[f"p_{o}_mk"].mean()})
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

# 平局校准分箱
print("\n--- 平局校准：按 DC 平局概率分箱 ---")
df["is_draw"] = (df.actual == "draw").astype(float)
df["bin"] = pd.cut(df.p_draw_dc, [0, .20, .24, .28, .32, 1])
print(df.groupby("bin", observed=True).agg(
    场数=("is_draw", "size"), DC平局=("p_draw_dc", "mean"),
    市场平局=("p_draw_mk", "mean"), 实际平局=("is_draw", "mean"),
    差值=("diff", "mean")).to_string(float_format=lambda x: f"{x:.4f}"))

# 分歧：DC 与市场主胜概率差得越多，谁更准？
print("\n--- 分歧程度：|DC主胜 − 市场主胜| 分箱 ---")
gap = (df.p_home_win_dc - df.p_home_win_mk).abs()
df["dis"] = pd.cut(gap, [0, .03, .06, .10, .15, 1], include_lowest=True)
print(df.groupby("dis", observed=True).apply(summ, include_groups=False)
      .drop(columns="占总差距").to_string(float_format=lambda x: f"{x:+.4f}"))

# 分歧时 DC 的方向有没有信息：DC 比市场更看好主队的场次，主胜实际频率
print("\n--- 分歧方向（|差|>0.06）：DC 偏向的一方实际表现 ---")
big = df[gap > .06]
for name, m in [("DC 更看好主队", big.p_home_win_dc > big.p_home_win_mk),
                ("DC 更看好客队", big.p_home_win_dc < big.p_home_win_mk)]:
    g = big[m]
    print(f"{name}: 场数 {len(g)}  DC主胜 {g.p_home_win_dc.mean():.3f}  "
          f"市场主胜 {g.p_home_win_mk.mean():.3f}  实际主胜 "
          f"{(g.actual == 'home_win').mean():.3f}  差值 {g['diff'].mean():+.4f}")
