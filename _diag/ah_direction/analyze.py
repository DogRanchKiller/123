"""亚盘选择方向有没有系统偏向（只读 research.db / football.db）。
按实盘判断流程（analysis.asian）的做法：市场隐含比分矩阵在赛前市场亚盘线上的主队赢盘概率 ≥ 0.5 选主，否则选客。
样本：research.db 老五联赛 2012-07 ～ 2021-06 + football.db 11 联赛 2122 起（不重叠）；剔除隐含概率之和 < 1 的坏行。
分段：开球日 < 2025-07-01 为标定期，之后为留出期（2526、2627）。走盘不计，赢半 / 输半按赢 / 输算（与 ah_baseline 相同）。
看：选择方是热门还是冷门、主还是客、与胜平负倾向是否同向；各自命中率；对照「永远选热门 / 冷门 / 主 / 客」和
「只看亚盘去水水位选边」；按盘口深浅分组。结果写 result.txt。
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/ah_direction/analyze.py
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.data.loader import bad_market
from football_prediction.model_market.implied import fair_probs, implied_matrix
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf

HERE = Path(__file__).parent
SPLIT = "2025-07-01"
SQL = """SELECT m.match_id, m.league, m.season, m.match_date, m.home_goals hg, m.away_goals ag,
                o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25, o.ah_line, o.avg_ahh, o.avg_aha
         FROM matches m JOIN match_odds o USING(match_id)
         WHERE m.match_date >= ? AND m.match_date < ? AND o.ah_line IS NOT NULL AND o.avg_ahh > 1
           AND o.avg_aha > 1 AND o.avg_h > 1 AND o.avg_over25 > 1 AND m.home_goals IS NOT NULL"""


def load() -> pd.DataFrame:
    parts = []
    for db, lo, hi in (("research.db", "2012-07-01", "2021-07-01"), ("football.db", "2021-07-01", "2100-01-01")):
        with sqlite3.connect(db) as c:
            parts.append(pd.read_sql_query(SQL, c, params=(lo, hi)).assign(src=db))
    df = pd.concat(parts, ignore_index=True)
    bad = df.apply(lambda r: bad_market(r.avg_h, r.avg_d, r.avg_a) or bad_market(r.avg_ahh, r.avg_aha)
                   or bad_market(r.avg_over25, r.avg_under25), axis=1)
    return df[~bad].sort_values("match_date").reset_index(drop=True)


def rows(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for r in df.itertuples():
        od = {"h": r.avg_h, "d": r.avg_d, "a": r.avg_a, "over": r.avg_over25, "under": r.avg_under25,
              "ah_line": r.ah_line, "ah_h": r.avg_ahh, "ah_a": r.avg_aha}
        got = implied_matrix(od, -0.05)
        if got is None:
            continue
        fair = ah_fair_prob(ah_outcome(margin_pmf(got[0]), r.ah_line))
        res = ah_outcome({int(r.hg - r.ag): 1.0}, r.ah_line)
        k = max(res, key=res.get)
        home_cover = None if k == "push" else k in ("win", "half_win")
        units = res.get("win", 0) + res.get("half_win", 0) / 2 - res.get("half_lose", 0) / 2 - res.get("lose", 0)
        fp = fair_probs(od)
        out.append({"league": r.league, "date": r.match_date, "line": r.ah_line, "fair": fair,
                    "mkt": fp["ah"][1], "p1x2_h": fp["1x2"][0], "p1x2_a": fp["1x2"][2],
                    "home_cover": home_cover, "units_h": units})
    return pd.DataFrame(out).dropna(subset=["home_cover"])


def rows_post(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["home_cover"] = d.home_cover.astype(bool)
    d["pick_home"] = d.fair >= 0.5
    d["fav_home"] = d.p1x2_h >= d.p1x2_a                      # 胜平负热门（主胜概率 ≥ 客胜概率）
    d["pick_fav"] = d.pick_home == d.fav_home
    d["hit"] = d.pick_home == d.home_cover
    d["mkt_hit"] = (d.mkt >= 0.5) == d.home_cover
    d["fav_cover"] = d.fav_home == d.home_cover
    # 半赢半输按半场计：主队方向收益 units_h（赢 1 / 赢半 0.5 / 输半 −0.5 / 输 −1，等赔率）
    d["u_model"] = np.where(d.pick_home, d.units_h, -d.units_h)
    d["u_dog"] = np.where(d.fav_home, -d.units_h, d.units_h)
    d["u_mkt"] = np.where(d.mkt >= 0.5, d.units_h, -d.units_h)
    d["p_pick"] = np.where(d.pick_home, d.fair, 1 - d.fair)
    d["depth"] = pd.cut(d.line.abs(), [-0.01, 0.25, 0.75, 1.25, 9], labels=["0–0.25", "0.5–0.75", "1–1.25", "≥1.5"])
    return d


def pct(s) -> str:
    s = np.asarray(s, float)
    m, se = s.mean(), s.std(ddof=1) / np.sqrt(len(s))
    return f"{m:.3f}±{se:.3f}"


def whit(u) -> float:
    """半赢半输按半场计的命中率：赢的份额 / (赢 + 输的份额)。"""
    u = np.asarray(u, float)
    return (np.abs(u).sum() + u.sum()) / 2 / np.abs(u).sum()


def paired(a, b) -> str:
    x = np.asarray(a, float) - np.asarray(b, float)
    return f"{x.mean():+.4f}±{x.std(ddof=1) / np.sqrt(len(x)):.4f}"


def block(d: pd.DataFrame, name: str) -> list[str]:
    o = [f"== {name}  n={len(d)}（不含走盘）"]
    o.append(f"  模型选择方命中 {pct(d.hit)}   平均给出概率 {d.p_pick.mean():.3f}   只看亚盘水位选边命中 {pct(d.mkt_hit)}"
             f"   两者选边相同 {(d.pick_home == (d.mkt >= 0.5)).mean():.3f}")
    o.append(f"  选择方：选热门 {d.pick_fav.mean():.3f}  选主队 {d.pick_home.mean():.3f}")
    o.append(f"  永远选：热门 {pct(d.fav_cover)}  冷门 {pct(~d.fav_cover)}  主队 {pct(d.home_cover)}  客队 {pct(~d.home_cover)}")
    for lab, g in (("选热门", d[d.pick_fav]), ("选冷门", d[~d.pick_fav]),
                   ("选主", d[d.pick_home]), ("选客", d[~d.pick_home])):
        o.append(f"    {lab}  n={len(g):>6}  命中 {pct(g.hit)}  平均给出概率 {g.p_pick.mean():.3f}")
    o.append("  按盘口深浅：")
    for dep, g in d.groupby("depth", observed=True):
        o.append(f"    |线| {dep:<9} n={len(g):>6}  选热门 {g.pick_fav.mean():.3f}  命中 {pct(g.hit)}  "
                 f"热门赢盘 {pct(g.fav_cover)}  给出概率 {g.p_pick.mean():.3f}")
    o.append(f"  半赢半输按半场计：模型 {whit(d.u_model):.3f}  水位选边 {whit(d.u_mkt):.3f}  永远冷门 {whit(d.u_dog):.3f}")
    o.append(f"  同场每场收益差（等赔率单位）：模型 − 永远冷门 {paired(d.u_model, d.u_dog)}   模型 − 水位选边 {paired(d.u_model, d.u_mkt)}")
    for dep, g in d.groupby("depth", observed=True):
        o.append(f"    |线| {dep:<9} 半场计 模型 {whit(g.u_model):.3f}  永远冷门 {whit(g.u_dog):.3f}  "
                 f"模型 − 永远冷门 {paired(g.u_model, g.u_dog)}")
    strong = d[np.maximum(d.p1x2_h, d.p1x2_a) >= 0.60]
    o.append(f"  胜平负热门 ≥60% 的场次 n={len(strong)}：亚盘选冷门 {(~strong.pick_fav).mean():.3f}，"
             f"选冷门时命中 {pct(strong[~strong.pick_fav].hit)}，选热门时命中 {pct(strong[strong.pick_fav].hit)}")
    return o


def main():
    cache = HERE / "rows.csv"                                   # 逐场结果，gitignore；改统计口径时免重算
    if cache.exists():
        d = rows_post(pd.read_csv(cache))
    else:
        raw = rows(load())
        raw.to_csv(cache, index=False)
        d = rows_post(raw)
    out = [f"亚盘选择方向（市场隐含在赛前市场线上）；样本 {len(d)} 场，{d.date.min()} ～ {d.date.max()}", ""]
    out += block(d[d.date < SPLIT], "标定期") + [""] + block(d[d.date >= SPLIT], "留出期（2526 起）")
    out += ["", "按联赛（全时段）：选热门比例 / 命中 / 永远选热门赢盘"]
    for lg, g in d.groupby("league"):
        out.append(f"  {lg:<4} n={len(g):>5}  {g.pick_fav.mean():.3f}  {pct(g.hit)}  {pct(g.fav_cover)}")
    text = "\n".join(out)
    (HERE / "result.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
