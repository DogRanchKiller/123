"""强弱悬殊场次检查：按模型给热门方的胜率分桶，对比 模型 / 市场 / 实际。
回测 2324–2627（每月重拟合，均为样本外）。"""
import numpy as np
import pandas as pd
from _diag.explore.harness import load_all, run

df = load_all()
r = run(df, {}).merge(df[["match_id", "hg", "ag", "xg_h", "xg_a", "mc_h", "mc_d", "mc_a"]],
                      on="match_id").dropna(subset=["mc_h"])
fav_home = r.p_h >= r.p_a
r["p_fav"] = np.where(fav_home, r.p_h, r.p_a)
r["m_fav"] = np.where(fav_home, r.mc_h, r.mc_a)
r["win_fav"] = np.where(fav_home, r.actual == 0, r.actual == 2).astype(float)
r["draw"] = (r.actual == 1).astype(float)
for name, (h, a) in {"lam": ("lam_h", "lam_a"), "g": ("hg", "ag"), "xg": ("xg_h", "xg_a")}.items():
    r[f"{name}_fav"] = np.where(fav_home, r[h], r[a])
    r[f"{name}_dog"] = np.where(fav_home, r[a], r[h])
r["bin"] = pd.cut(r.p_fav, [0, 0.45, 0.55, 0.65, 0.75, 1.0])
t = r.groupby("bin", observed=True).agg(
    场数=("match_id", "size"), 模型热门胜率=("p_fav", "mean"), 市场热门胜率=("m_fav", "mean"),
    实际热门胜率=("win_fav", "mean"), 模型平局=("p_d", "mean"), 实际平局=("draw", "mean"),
    模型热门进球=("lam_fav", "mean"), 实际热门进球=("g_fav", "mean"), 热门xG=("xg_fav", "mean"),
    模型冷门进球=("lam_dog", "mean"), 实际冷门进球=("g_dog", "mean"), 冷门xG=("xg_dog", "mean"))
t["实际胜率SE"] = np.sqrt(t.实际热门胜率 * (1 - t.实际热门胜率) / t.场数)
pd.set_option("display.width", 250)
print(t.round(3).to_string())
# 按市场分桶（热门方由市场定）：市场认为悬殊的场次，模型给多少
mh = r.mc_h >= r.mc_a
q = pd.DataFrame({"m": np.where(mh, r.mc_h, r.mc_a), "p": np.where(mh, r.p_h, r.p_a),
                  "w": np.where(mh, r.actual == 0, r.actual == 2).astype(float)})
q["bin"] = pd.cut(q.m, [0, 0.45, 0.55, 0.65, 0.75, 1.0])
print(q.groupby("bin", observed=True).agg(场数=("m", "size"), 市场热门胜率=("m", "mean"),
      模型热门胜率=("p", "mean"), 实际热门胜率=("w", "mean")).round(3).to_string())
