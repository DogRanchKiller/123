"""可靠度层研究（research.db，只读）：市场最大概率 p_max 之外，联赛 / 赛季初 / 升班马 / 盘口不一致
是否改变「首选命中」的概率；并按 Shin 去水重算信心档命中率。
样本 1213–2425 标定，2526 留出复核。赛前档用 avg_*，临场档用收盘 avgc_*。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/explore/reliability.py > _diag/explore/reliability.log
"""
import sqlite3

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from football_prediction.model_market.devig import devig

DB = "research.db"
FROM = "2012-07-01"
HOLDOUT = "2526"
TIERS = (0.60, 0.45)
EARLY = 6                 # 两队中较少的一方本季已赛 < 6 场视为赛季初


def _start_year(season: str) -> int:
    y = int(season[:2])
    return 1900 + y if y >= 90 else 2000 + y


def load() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        """SELECT m.match_id, m.league, m.season, m.match_date, m.home_team, m.away_team,
                  m.home_goals hg, m.away_goals ag, o.avg_h, o.avg_d, o.avg_a,
                  o.avgc_h, o.avgc_d, o.avgc_a, o.avg_over25, o.avg_under25,
                  o.ah_line, o.avg_ahh, o.avg_aha
           FROM matches m JOIN match_odds o USING(match_id) ORDER BY m.match_date""", conn)
    teams = pd.read_sql_query("SELECT DISTINCT league, season, home_team team FROM matches", conn)
    conn.close()
    # 升班马：上一季同联赛没有这支队
    teams["y"] = teams.season.map(_start_year)
    have = set(zip(teams.league, teams.y, teams.team))
    df["y"] = df.season.map(_start_year)
    df["promoted"] = [int((lg, y - 1, h) not in have or (lg, y - 1, a) not in have)
                      for lg, y, h, a in zip(df.league, df.y, df.home_team, df.away_team)]
    # 本季已赛场数（按日期，同日不算）
    n_played = {}
    played_h, played_a = [], []
    for lg, s, h, a in zip(df.league, df.season, df.home_team, df.away_team):
        played_h.append(n_played.get((lg, s, h), 0))
        played_a.append(n_played.get((lg, s, a), 0))
        n_played[(lg, s, h)] = played_h[-1] + 1
        n_played[(lg, s, a)] = played_a[-1] + 1
    df["early"] = (np.minimum(played_h, played_a) < EARLY).astype(int)
    df = df[(df.match_date >= FROM) & df[["avg_h", "avg_d", "avg_a"]].notna().all(axis=1)]
    df = df.reset_index(drop=True)
    df["y_res"] = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
    for tag, cols in (("pre", ("avg_h", "avg_d", "avg_a")), ("close", ("avgc_h", "avgc_d", "avgc_a"))):
        O = df[list(cols)].to_numpy()
        ok = ~np.isnan(O).any(axis=1)
        for m in ("proportional", "shin"):
            P = np.full((len(df), 3), np.nan)
            P[ok] = np.array([devig(o, m) for o in O[ok]])
            k = f"{tag}_{m[:4]}"
            df[k + "_max"] = P.max(axis=1)
            order = np.argsort(-P, axis=1)
            df[k + "_hit1"] = (order[:, 0] == df.y_res).astype(float).where(ok)
            df[k + "_hit2"] = ((order[:, 0] == df.y_res) | (order[:, 1] == df.y_res)).astype(float).where(ok)
            df[k + "_top2"] = np.sort(P, axis=1)[:, 1:].sum(axis=1)
    return df


def calibration(df: pd.DataFrame, k: str) -> None:
    bins = [0, .40, .45, .50, .55, .60, .65, .70, .75, 1]
    d = df[[k + "_max", k + "_hit1"]].dropna()
    g = d.groupby(pd.cut(d[k + "_max"], bins))
    t = pd.DataFrame({"n": g.size(), "p_max": g[k + "_max"].mean(), "hit": g[k + "_hit1"].mean()})
    t["hit-p"] = t.hit - t.p_max
    t["se"] = np.sqrt(t.hit * (1 - t.hit) / t.n)
    print(t.round(3).to_string())


def logit_fit(X: np.ndarray, y: np.ndarray, off: np.ndarray):
    """带偏移的 logistic：logit P(hit) = off + X·b；返回 (b, se)。"""
    def nll(b):
        z = off + X @ b
        p = 1 / (1 + np.exp(-z))
        return -(y * np.log(p) + (1 - y) * np.log(1 - p)).sum(), X.T @ (p - y)
    b = minimize(nll, np.zeros(X.shape[1]), jac=True, method="BFGS").x
    p = 1 / (1 + np.exp(-(off + X @ b)))
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))))
    return b, se


def context_test(df: pd.DataFrame, k: str) -> None:
    """以 logit(p_max) 为偏移，看联赛 / 赛季初 / 升班马能否改变首选命中（系数为 logit 单位）。"""
    leagues = sorted(df.league.unique())
    for lab, part in (("标定 1213–2425", df[df.season != HOLDOUT]), ("留出 2526", df[df.season == HOLDOUT])):
        d = part.dropna(subset=[k + "_max", k + "_hit1"])
        p = d[k + "_max"].clip(1e-6, 1 - 1e-6).to_numpy()
        off = np.log(p / (1 - p))
        cols = {"截距": np.ones(len(d)), "logit p 斜率-1": off,
                "赛季初": d.early.to_numpy(), "升班马": d.promoted.to_numpy()}
        for lg in leagues[1:]:
            cols[lg] = (d.league == lg).to_numpy().astype(float)
        X = np.column_stack(list(cols.values()))
        b, se = logit_fit(X, d[k + "_hit1"].to_numpy(), off)
        print(f"  {lab} n={len(d)}  （联赛以 {leagues[0]} 为基准）")
        print("   " + "  ".join(f"{n} {v:+.3f}±{s:.3f}" for n, v, s in zip(cols, b, se)))


def tier_table(df: pd.DataFrame, k: str, by: str | None = None) -> pd.DataFrame:
    d = df.dropna(subset=[k + "_max"]).copy()
    d["tier"] = np.where(d[k + "_max"] >= TIERS[0], "高", np.where(d[k + "_max"] >= TIERS[1], "中", "低"))
    keys = ["tier"] + ([by] if by else [])
    g = d.groupby(keys)
    return pd.DataFrame({"n": g.size(), "p_max": g[k + "_max"].mean(), "hit1": g[k + "_hit1"].mean(),
                         "hit2": g[k + "_hit2"].mean(), "top2": g[k + "_top2"].mean()}).round(3)


def main():
    df = load()
    sel, hold = df[df.season != HOLDOUT], df[df.season == HOLDOUT]
    print(f"共 {len(df)} 场（{FROM} 起），标定 {len(sel)}，留出 {HOLDOUT} {len(hold)}")
    print(f"赛季初（较少一方已赛 < {EARLY} 场）占 {df.early.mean():.1%}，升班马参赛占 {df.promoted.mean():.1%}")

    print("\n== 一、校准：p_max 分箱的实际首选命中（标定期）")
    for k in ("pre_prop", "pre_shin", "close_shin"):
        print(f"\n-- {k}")
        calibration(sel, k)

    print("\n== 二、p_max 之外的因素（logit 偏移回归；系数显著才说明需要单独标定）")
    for k in ("pre_shin", "close_shin"):
        print(f"\n-- {k}")
        context_test(df, k)

    print("\n== 三、信心档命中率（Shin 去水，阈值 0.60 / 0.45）")
    for k in ("pre_shin", "close_shin"):
        for lab, part in (("标定", sel), ("留出", hold)):
            print(f"\n-- {k} {lab}")
            print(tier_table(part, k).to_string())
    print("\n-- pre_shin 标定，按联赛")
    print(tier_table(sel, "pre_shin", "league").to_string())
    print("\n-- pre_shin 标定，赛季初 vs 其余")
    print(tier_table(sel, "pre_shin", "early").to_string())
    print("\n-- 对照：pre_prop 标定（现行 MARKET_TIERS 的去水方法）")
    print(tier_table(sel, "pre_prop").to_string())


if __name__ == "__main__":
    main()
