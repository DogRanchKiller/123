"""全部方向跑一遍：每个方向在 2324+2425 选参（相对当前主模型配置 BASE 配对比较），
再在 2526（已用于 xG 留出，半新）与 2627（完全未用过）确认。结果写 results.csv / log。"""
import itertools, json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from _diag.explore.harness import load_all, run, ll, hit, paired, BASE

SEL, CONF = ["2324", "2425"], ["2526", "2627"]
df = load_all()
cache = {}


def get(cfg):
    key = json.dumps({**BASE, **cfg}, sort_keys=True)
    if key not in cache:
        cache[key] = run(df, cfg)
    return cache[key]


base = get({})
rows = []


def record(idea, cfg, r, ref=base):
    out = {"idea": idea, "cfg": json.dumps(cfg, ensure_ascii=False)}
    for tag, ss in [("sel", SEL), ("2526", ["2526"]), ("2627", ["2627"])]:
        a, b = r[r.season.isin(ss)], ref[ref.season.isin(ss)]
        n, d, se = paired(a, b)
        out[f"{tag}_n"], out[f"{tag}_d"], out[f"{tag}_se"] = n, d, se
        out[f"{tag}_ll"], out[f"{tag}_hit"] = ll(a).mean(), hit(a).mean()
    rows.append(out)
    return out


def best(idea, cfgs):
    """在选参集上取 log loss 最小的配置，全部记录"""
    res = [(c, record(idea, c, get(c))) for c in cfgs]
    c, o = min(res, key=lambda x: x[1]["sel_ll"])
    print(f"[{idea}] best {c}  sel {o['sel_d']:+.4f}±{o['sel_se']:.4f}  "
          f"2526 {o['2526_d']:+.4f}±{o['2526_se']:.4f}  2627 {o['2627_d']:+.4f}±{o['2627_se']:.4f}",
          flush=True)
    return c


record("base", {}, base)
# E1 信号组合：进球 / xG / 射正
e1 = [dict(wg=g, ws=s, wx=round(1 - g - s, 2))
      for g in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5] for s in [0.0, 0.1, 0.2, 0.3, 0.4] if g + s <= 1.0]
b1 = best("E1_signal", e1)
# E2 时间衰减 × 收缩
b2 = best("E2_xi_shrink", [dict(xi=x, shrink=s) for x in [0.002, 0.003, 0.004, 0.005, 0.007, 0.01]
                           for s in [0.1, 0.25, 0.5, 1.0, 2.0]])
# E3 红牌场次降权
b3 = best("E3_red", [dict(red_w=w) for w in [1.0, 0.8, 0.6, 0.4, 0.2]])
# E4 赛季初：上赛季及更早比赛额外降权
b4 = best("E4_prev_season", [dict(prev_w=w) for w in [1.0, 0.8, 0.6, 0.4, 0.25]])
# E5 升级队先验
b5 = best("E5_promoted", [dict(prom_c=c) for c in [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]])
# E6 每个比赛日重拟合（接近实盘）
record("E6_daily_refit", dict(refit="daily"), get(dict(refit="daily")))

# E7/E8 赛后校准层：多项 logit，z_h = a·[1, log(ph/pd), log(pa/pd), 休息差]，z_a 同理，平局为 0。
# 只在选参季的模型预测上拟合，应用到确认季（选参季数值为样本内，仅供参考）。
RC = df.set_index("match_id")[["rest_h", "rest_a"]]


def _feats(r, rest):
    P = r[["p_h", "p_d", "p_a"]].to_numpy()
    cols = [np.ones(len(r)), np.log(P[:, 0] / P[:, 1]), np.log(P[:, 2] / P[:, 1])]
    if rest:
        rr = RC.loc[r.match_id]
        cols.append(np.clip((rr.rest_h.to_numpy() - rr.rest_a.to_numpy()) / 7, -1, 1))
    return np.stack(cols, 1)


def calibrate(r, rest=False, lam=1.0):
    X, y = _feats(r, rest), r["actual"].to_numpy()
    k = X.shape[1]
    tr = r.season.isin(SEL).to_numpy()
    w0 = np.zeros(2 * k); w0[1] = 1; w0[k + 2] = 1   # 恒等映射起点

    def nll(w):
        Z = np.stack([X[tr] @ w[:k], np.zeros(tr.sum()), X[tr] @ w[k:]], 1)
        Z -= Z.max(1, keepdims=True)
        lp = Z - np.log(np.exp(Z).sum(1, keepdims=True))
        return -lp[np.arange(tr.sum()), y[tr]].sum() + lam * ((w - w0) ** 2).sum()

    w = minimize(nll, w0, method="BFGS").x
    Z = np.stack([X @ w[:k], np.zeros(len(X)), X @ w[k:]], 1)
    P = np.exp(Z - Z.max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
    return r.assign(p_h=P[:, 0], p_d=P[:, 1], p_a=P[:, 2]), w


cal, w7 = calibrate(base)
o = record("E7_calibration", {"w": np.round(w7, 3).tolist()}, cal)
print(f"[E7_calibration] w={np.round(w7, 3)}  2526 {o['2526_d']:+.4f}±{o['2526_se']:.4f}  "
      f"2627 {o['2627_d']:+.4f}±{o['2627_se']:.4f}", flush=True)
cal8, w8 = calibrate(base, rest=True)
o = record("E8_cal_rest", {"w": np.round(w8, 3).tolist()}, cal8)
print(f"[E8_cal_rest] w={np.round(w8, 3)}  2526 {o['2526_d']:+.4f}±{o['2526_se']:.4f}  "
      f"2627 {o['2627_d']:+.4f}±{o['2627_se']:.4f}  (对比E7: 休息差系数 h={w8[3]:.3f}, a={w8[7]:.3f})",
      flush=True)

# E9 组合：选参集上有改进的方向合并，再试每日重拟合与校准
R = pd.DataFrame(rows).set_index("idea")
comb = {}
for idea, b in [("E1_signal", b1), ("E2_xi_shrink", b2), ("E3_red", b3),
                ("E4_prev_season", b4), ("E5_promoted", b5)]:
    o = [x for x in rows if x["idea"] == idea and x["cfg"] == json.dumps(b, ensure_ascii=False)][0]
    if o["sel_d"] < 0:
        comb.update(b)
print("combined cfg:", comb, flush=True)
c9 = get(comb)
record("E9_combined", comb, c9)
c9d = get({**comb, "refit": "daily"})
record("E9_combined_daily", {**comb, "refit": "daily"}, c9d)
c9c, w9 = calibrate(c9d)
record("E9_combined_daily_cal", {**comb, "refit": "daily", "cal": np.round(w9, 3).tolist()}, c9c)

# 市场基准（同场）：收盘 & 赛前平均赔率
for tag in ["c", "o"]:
    m = df.dropna(subset=[f"m{tag}_h"])
    mr = pd.DataFrame({"match_id": m.match_id, "league": m.league, "season": m.season,
                       "actual": m.actual, "p_h": m[f"m{tag}_h"], "p_d": m[f"m{tag}_d"],
                       "p_a": m[f"m{tag}_a"]})
    mr = mr[mr.match_id.isin(base.match_id)]
    record(f"market_{'closing' if tag == 'c' else 'open'}", {}, mr)
    for name, r in [("base", base), ("E9_combined_daily_cal", c9c)]:
        o = record(f"{name}_vs_market_{tag}", {}, r, ref=mr)

out = pd.DataFrame(rows)
out.to_csv("_diag/explore/results.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
show = out.loc[out.groupby("idea", sort=False)["sel_ll"].idxmin()]   # 每个方向取选参集最优
print(show[["idea", "sel_d", "sel_se", "2526_d", "2526_se", "2627_d", "2627_se",
            "sel_ll", "2526_ll", "2627_ll", "sel_hit", "2526_hit", "2627_hit"]].round(4).to_string())
for name, r in [("base", base), ("final", c9c)]:
    c = r[r.season.isin(CONF)]
    print(name, "确认季 平局作为首选的比例:", (c[["p_h", "p_d", "p_a"]].to_numpy().argmax(1) == 1).mean().round(3),
          " 平均平局概率:", c.p_d.mean().round(3), " 实际平局率:", (c.actual == 1).mean().round(3))
c9c.to_csv("_diag/explore/final_preds.csv", index=False)
