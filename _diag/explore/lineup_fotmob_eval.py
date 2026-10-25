"""阵容模型（model_lineup，FotMob 球员数据）的样本外检验：football.db + fotmob.db。
每个比赛日重拟合 LineupModel（只用此前完赛场次），算两队阵容特征；λ 由赛前平均赔率反推（独立泊松）。
系数在 2324–2425 上拟合，2526 起留出：比较 调整后 vs 未调整 的 1X2 log loss，并列出收盘价作参照。
分别以赛前赔率（首发公布前）和收盘赔率（首发公布后）为偏移各拟合一套，对应 adjust.COEF_PRE / COEF_POST。
（与 lineup_eval.py 的"方向 D"代理特征不同，那份用的是 football-data 字段。）
用法：PYTHONPATH=. python -u _diag/explore/lineup_fotmob_eval.py  -> lineup_fotmob_features.csv
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson

from football_prediction.data import fotmob
from football_prediction.data.loader import init_db
from football_prediction.model_dc.market_dc import lambdas_from_odds
from football_prediction.model_lineup.adjust import FEATURES, design, fit_coef
from football_prediction.model_lineup.ratings import LineupModel, load_history

LEAGUES = ("E0", "D1", "SP1")
TRAIN = ("2324", "2425")
OUT = "_diag/explore/lineup_fotmob_features.csv"
ODDS = ("avg_h", "avg_d", "avg_a", "avg_over25", "avg_under25",
        "avgc_h", "avgc_d", "avgc_a", "avgc_over25", "avgc_under25")


def build(conn, lg: str) -> pd.DataFrame:
    hist = load_history(conn, lg, "2100-01-01")
    if hist.empty:
        return pd.DataFrame()
    ms = pd.read_sql_query(
        f"""SELECT m.match_id, m.season, m.match_date, m.home_team, m.away_team,
                   m.home_goals AS hg, m.away_goals AS ag, {", ".join("o." + c for c in ODDS)}
            FROM matches m JOIN match_odds o ON o.match_id = m.match_id
            WHERE m.league = ? AND o.avg_h IS NOT NULL ORDER BY m.match_date""",
        conn, params=(lg,))
    ms = ms[ms["match_id"].isin(set(hist["match_id"]))]
    starters = {k: list(zip(g["player_id"], g["position_id"]))
                for k, g in hist[hist["role"] == "starter"].groupby(["match_id", "team"])}
    model, rows = LineupModel(), []
    for d, g in ms.groupby("match_date"):
        model.fit_history(hist[hist["match_date"] < d], d)
        for r in g.itertuples():
            f = {s: model.team_features(t, starters.get((r.match_id, t), []))
                 for s, t in (("h", r.home_team), ("a", r.away_team))}
            if f["h"] is None or f["a"] is None:
                continue
            rows.append({"match_id": r.match_id, "league": lg, "season": r.season,
                         "hg": r.hg, "ag": r.ag,
                         **{f"{s}_{k}": v for s in "ha" for k, v in f[s].items()},
                         **{c: getattr(r, c) for c in ODDS}})
    print(f"{lg}: {len(ms)} 场有阵容和赔率，{len(rows)} 场两队都有 5 场以上首发历史", flush=True)
    return pd.DataFrame(rows)


def p1x2(lh, la, maxg=16):
    k = np.arange(maxg)
    j = poisson.pmf(k, lh[:, None])[:, :, None] * poisson.pmf(k, la[:, None])[:, None, :]
    low = np.tril(np.ones((maxg, maxg)), -1).astype(bool)
    return np.stack([j[:, low].sum(1), j[:, np.eye(maxg, dtype=bool)].sum(1), j[:, low.T].sum(1)], 1)


def ll(p, hg, ag):
    idx = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
    return -np.log(p[np.arange(len(p)), idx])


def feats(df, me):
    op = "a" if me == "h" else "h"
    keys = ("d_att", "rot", "rot_def")
    return np.array([design({k: r[f"{me}_{k}"] for k in keys}, {k: r[f"{op}_{k}"] for k in keys})
                     for _, r in df.iterrows()]).reshape(-1, len(FEATURES))


def pm(x):
    return f"{x.mean():+.5f} ± {x.std(ddof=1) / np.sqrt(len(x)):.5f}"


def _fit(tr: pd.DataFrame, pre: str) -> tuple[np.ndarray, np.ndarray]:
    """以 {pre}_h/{pre}_a 为偏移拟合系数，返回 (b, se)。"""
    X = np.vstack([feats(tr, "h"), feats(tr, "a")])
    off = np.log(np.concatenate([tr[pre + "_h"], tr[pre + "_a"]]))
    y = np.concatenate([tr.hg, tr.ag]).astype(float)
    coef = fit_coef(X, off, y)
    b = np.array([coef[k] for k in FEATURES])
    mu = np.exp(off + X @ b)
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ (X * mu[:, None]) + 2 * np.eye(len(b)))))
    return b, se


def evaluate(df: pd.DataFrame) -> None:
    """两套系数：COEF_PRE 叠在阵容公布前的赛前赔率上（avg_*），COEF_POST 叠在收盘赔率上（avgc_*，
    收盘在正式首发公布之后，相当于实盘「赔率晚于首发」的情形）。收盘缺失的场次不进 POST。"""
    df = df.copy()
    df["lam_h"], df["lam_a"] = lambdas_from_odds(*(df[c] for c in ODDS[:5]))
    df = df[df[["avgc_h", "avgc_d", "avgc_a", "avgc_over25", "avgc_under25"]].notna().all(axis=1)]
    df["lamc_h"], df["lamc_a"] = lambdas_from_odds(*(df[c] for c in ODDS[5:]))
    tr, te = df[df.season.isin(TRAIN)], df[~df.season.isin(TRAIN)]
    print("  主队特征 均值/标准差：" + "  ".join(
        f"{k}={tr[f'h_{k}'].mean():+.3f}/{tr[f'h_{k}'].std():.3f}" for k in ("d_att", "rot", "rot_def")))
    for name, pre in (("COEF_PRE（叠在赛前赔率上）", "lam"), ("COEF_POST（叠在收盘赔率上）", "lamc")):
        b, se = _fit(tr, pre)
        print(f"\n{name}  训练 {sorted(tr.season.unique())} n={len(tr)} 场；系数（±SE）：")
        for k, v, s in zip(FEATURES, b, se):
            print(f"  {k:<12}{v:+.4f} ± {s:.4f}")
        for label, part in (("训练（样本内）", tr), ("留出 2526+", te)):
            if part.empty:
                print(f"  == {label}：无数据")
                continue
            hg, ag = part.hg.to_numpy(), part.ag.to_numpy()
            lh, la = part[pre + "_h"].to_numpy(), part[pre + "_a"].to_numpy()
            base = ll(p1x2(lh, la), hg, ag)
            adj = ll(p1x2(lh * np.exp(feats(part, "h") @ b), la * np.exp(feats(part, "a") @ b)), hg, ag)
            print(f"  == {label} n={len(part)}  基准 {base.mean():.5f}  阵容调整 {adj.mean():.5f}"
                  f"  差 {pm(adj - base)}")
            for lg, g in part.assign(d=adj - base).groupby("league"):
                print(f"     {lg} {pm(g.d)}  n={len(g)}")
    for label, part in (("训练", tr), ("留出 2526+", te)):
        if len(part):
            hg, ag = part.hg.to_numpy(), part.ag.to_numpy()
            d = ll(p1x2(part.lamc_h.to_numpy(), part.lamc_a.to_numpy()), hg, ag) - \
                ll(p1x2(part.lam_h.to_numpy(), part.lam_a.to_numpy()), hg, ag)
            print(f"\n参照 {label}：收盘 − 赛前 {pm(d)}（收盘含阵容等临场信息）")


if __name__ == "__main__":
    import sys
    if "--cached" in sys.argv:              # 只重跑评估，特征用上次的 CSV
        df = pd.read_csv(OUT, dtype={"season": str})
    else:
        conn = fotmob.attach(init_db("football.db"))
        df = pd.concat([build(conn, lg) for lg in LEAGUES], ignore_index=True)
        df.to_csv(OUT, index=False)
    evaluate(df)
