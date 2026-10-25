"""5 联赛 9394–2526 的规律梳理（research.db，只读）：分两层看。
第一层「规律存在吗」：主场优势与进球的年代变化、空场期、评级差 → 赛果。
第二层「赔率算进去了吗」：按各种条件分组看 实际 − 市场去水概率；前半段（0001–1617）发现、后半段（1718–2526）复核，
两段同向且各自超过 2 SE 才算赔率没算进去的规律。
特征（评级、近况、休息天数）复用 ratings_gbm.features，每行只用赛前信息。
用法：PYTHONPATH=. python -u _diag/explore/patterns.py  -> patterns.log
"""
import sqlite3

import numpy as np
import pandas as pd

from _diag.explore.ratings_gbm import features, load


def _order(df):
    return df.groupby("season")["match_date"].min().sort_values().index.tolist()


def prep() -> pd.DataFrame:
    df = load(sqlite3.connect("research.db"))
    f = df.merge(features(df), on="match_id")
    f["date"] = pd.to_datetime(f.match_date)
    f["hw"], f["dr"], f["aw"] = (f.hg > f.ag) * 1.0, (f.hg == f.ag) * 1.0, (f.hg < f.ag) * 1.0
    inv = 1 / f[["avg_h", "avg_d", "avg_a"]].to_numpy()
    f[["mk_h", "mk_d", "mk_a"]] = inv / inv.sum(1, keepdims=True)
    seasons = _order(f)
    f["s_idx"] = f.season.map({s: i for i, s in enumerate(seasons)})
    teams = f.groupby(["league", "s_idx"]).apply(
        lambda g: set(g.home_team) | set(g.away_team), include_groups=False).to_dict()
    for side in ("home", "away"):
        f[f"{side[0]}_promoted"] = [t not in teams.get((lg, i - 1), {t}) for lg, i, t in
                                    zip(f.league, f.s_idx, f[f"{side}_team"])]
    f["half"] = np.where(f.s_idx < seasons.index("1718"), "前段0001-1617", "后段1718-2526")
    return f


def resid(g, actual, prob):
    d = g[actual] - g[prob]
    return f"{d.mean() * 100:+5.1f}pp ±{d.std(ddof=1) / np.sqrt(len(d)) * 100:.1f}"


def table(f, by, actual, prob, title):
    """按 by 分组，前 / 后两段各给 实际 − 市场。"""
    print(f"\n-- {title}（实际 − 市场，{actual}）")
    o = f.dropna(subset=[prob])
    o = o[o.half.notna()]
    for k, g in o.groupby(by, observed=True):
        cells = [f"{h}: {resid(gh, actual, prob)} n={len(gh)}" for h, gh in g.groupby("half")]
        print(f"  {str(k):<18}" + "   ".join(cells))


def main():
    f = prep()
    print(f"共 {len(f)} 场；有赔率 {f.mk_h.notna().sum()} 场（0001 起）")

    print("\n== 一、主场优势与进球的年代变化")
    f["era"] = pd.cut(f.date.dt.year, [1992, 2000, 2005, 2010, 2015, 2020, 2027],
                      labels=["93-00", "00-05", "05-10", "10-15", "15-20", "20-26"])
    t = f.groupby("era", observed=True).agg(n=("hw", "size"), 主胜=("hw", "mean"), 平=("dr", "mean"),
                                            客胜=("aw", "mean"), 场均进球=("hg", lambda s: (s + f.loc[s.index, "ag"]).mean()),
                                            主净胜=("hg", lambda s: (s - f.loc[s.index, "ag"]).mean()))
    print(t.round(3).to_string())
    empty = (f.date >= "2020-06-01") & (f.date < "2021-06-01")
    near = ((f.date >= "2018-08-01") & (f.date < "2020-03-01")) | ((f.date >= "2021-08-01") & (f.date < "2023-06-01"))
    for lab, m in (("空场期 2020-06~2021-05", empty), ("前后有观众 1819-1920上 / 2122-2223", near)):
        g = f[m]
        print(f"  {lab:<34} 主胜 {g.hw.mean():.3f}  客胜 {g.aw.mean():.3f}  主净胜 {(g.hg - g.ag).mean():+.3f}  "
              f"市场主胜 {g.mk_h.mean():.3f}  n={len(g)}")
    print("  空场期分月（看市场多久跟上）：")
    for mth, g in f[empty].groupby(f[empty].date.dt.to_period("Q")):
        print(f"    {mth}  主胜 {g.hw.mean():.3f}  市场 {g.mk_h.mean():.3f}  n={len(g)}")

    print("\n== 二、赛前评级差 → 赛果（pi-rating 预期净胜球，十分位）")
    f["pi_bin"] = pd.qcut(f.pi_gd, 10)
    print(f.groupby("pi_bin", observed=True)[["hw", "dr", "aw"]].mean().round(3).to_string())
    print("  平局率最高的分位：", f.groupby("pi_bin", observed=True).dr.mean().idxmax())

    print("\n== 三、市场校准（热门方胜率；热门-冷门偏差）")
    P = f[["mk_h", "mk_d", "mk_a"]].to_numpy()
    ok = ~np.isnan(P).any(1)
    fo = f[ok].copy()
    win = fo[["hw", "dr", "aw"]].to_numpy()
    side = np.where(P[ok][:, 0] >= P[ok][:, 2], 0, 2)
    fo["fav_p"] = P[ok][np.arange(ok.sum()), side]
    fo["fav_w"] = win[np.arange(ok.sum()), side]
    fo["fav_bin"] = pd.cut(fo.fav_p, [0, .4, .5, .6, .7, .8, 1])
    table(fo, "fav_bin", "fav_w", "fav_p", "热门方胜率按市场概率分组")
    fo["dr_bin"] = pd.cut(fo.mk_d, [0, .2, .25, .28, .31, 1])
    table(fo, "dr_bin", "dr", "mk_d", "平局按市场平局概率分组")

    print("\n== 四、赔率之外的候选规律（主胜 实际 − 市场）")
    fo["form_d"] = pd.cut(fo.h_f5_pts - fo.a_f5_pts, [-3.1, -1, -0.4, 0.4, 1, 3.1])
    table(fo, "form_d", "hw", "mk_h", "近 5 场场均积分差（主 − 客）")
    fo["rest_d"] = pd.cut(fo.h_rest - fo.a_rest, [-31, -3, -1, 1, 3, 31])
    table(fo, "rest_d", "hw", "mk_h", "休息天数差（主 − 客）")
    fo["promo"] = np.select([fo.h_promoted & ~fo.a_promoted, fo.a_promoted & ~fo.h_promoted],
                            ["主队升班马", "客队升班马"], "都不是/都是")
    table(fo, "promo", "hw", "mk_h", "升班马")
    fo["phase"] = pd.cut(fo.h_n, [-1, 4, 18, 30, 60], labels=["前5轮", "6-19轮", "20-31轮", "32轮后"])
    table(fo, "phase", "hw", "mk_h", "赛季阶段（主队本季已赛场次）")
    mk_gd = np.log(fo.mk_h / fo.mk_a)
    fo["pi_vs_mk"] = pd.qcut(fo.pi_gd - np.poly1d(np.polyfit(mk_gd, fo.pi_gd, 1))(mk_gd), 5)
    table(fo, "pi_vs_mk", "hw", "mk_h", "评级比市场更看好主队的程度（五分位）")
    table(fo, "league", "hw", "mk_h", "联赛")
    table(fo, "league", "dr", "mk_d", "联赛")

    print("\n== 五、可预测性：市场 1X2 log loss 与命中率")
    fo["ll"] = -np.log(np.clip(P[ok][np.arange(ok.sum()), np.argmax(win, 1)], 1e-7, None))
    fo["hit"] = (P[ok].argmax(1) == win.argmax(1)) * 1.0
    for by in ("league", "phase", "era"):
        print(fo.groupby(by, observed=True).agg(n=("ll", "size"), log_loss=("ll", "mean"),
                                                命中率=("hit", "mean")).round(3).to_string(), "\n")


if __name__ == "__main__":
    main()
