"""探索用内存回测框架：一次读入全部数据，按配置拟合"信号混合版 DC"，逐场输出概率。
默认配置（wg=0.3, wx=0.7）与 model_xg v1.0.0 同算法，用于复现校验。
cfg 字段：
  wg/wx/ws  目标值中 进球 / k·xG / k·射正 的权重（缺信号的场次该部分取进球）
  xi, shrink  时间衰减与收缩，同 DC
  red_w     有红牌比赛的拟合权重乘数
  prev_w    非当前赛季比赛的额外权重乘数（赛季初先验强弱）
  prom_c    升级队收缩目标 = 联赛均值 − prom_c（攻、守各自）
  refit     "monthly" | "daily"（每个比赛日前重拟合，接近实盘）
  window    只用截止日前 window 天内的比赛（0 = 全部历史）
"""
import sqlite3
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

from football_prediction.model_dc.sot_dc import _rho_nll
from football_prediction.data.loader import market_probs

LEAGUES = ["E0", "D1", "SP1"]
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
TESTS = ["2324", "2425", "2526", "2627"]
BASE = dict(wg=0.3, wx=0.7, ws=0.0, xi=0.005, shrink=0.5,
            red_w=1.0, prev_w=1.0, prom_c=0.0, refit="monthly", window=0)
G = np.arange(9)


def load_all():
    conn = sqlite3.connect("football.db")
    df = pd.read_sql_query(
        """SELECT m.match_id, m.league, m.season, m.match_date, m.home_team, m.away_team,
                  m.home_goals AS hg, m.away_goals AS ag,
                  s.home_sot AS sot_h, s.away_sot AS sot_a,
                  x.home_xg AS xg_h, x.away_xg AS xg_a
           FROM matches m LEFT JOIN match_stats s USING(match_id)
                          LEFT JOIN match_xg x USING(match_id)
           WHERE m.home_goals IS NOT NULL ORDER BY m.match_date""", conn)
    cards = pd.read_csv("_diag/explore/cards.csv")[["match_id", "hr", "ar"]]
    df = df.merge(cards, on="match_id", how="left")
    df["red"] = (df["hr"].fillna(0) + df["ar"].fillna(0)) > 0
    df["day"] = (pd.to_datetime(df["match_date"]) - pd.Timestamp("2000-01-01")).dt.days
    df["actual"] = np.select([df.hg > df.ag, df.hg == df.ag], [0, 1], 2)
    # 休息天数（只含联赛，缺欧战/杯赛）
    long = pd.concat([df[["match_id", "league", "day", "home_team"]].rename(columns={"home_team": "t"}).assign(side="h"),
                      df[["match_id", "league", "day", "away_team"]].rename(columns={"away_team": "t"}).assign(side="a")])
    long = long.sort_values("day")
    long["rest"] = long.groupby(["league", "t"])["day"].diff().clip(upper=14).fillna(14)
    rest = long.pivot(index="match_id", columns="side", values="rest")
    df = df.merge(rest.rename(columns={"h": "rest_h", "a": "rest_a"}), on="match_id")
    mk = []
    for closing, tag in [(True, "c"), (False, "o")]:
        m = pd.concat([market_probs(conn, lg, SEASONS, closing=closing) for lg in LEAGUES])
        mk.append(m.rename(columns={"p_home_win": f"m{tag}_h", "p_draw": f"m{tag}_d",
                                    "p_away_win": f"m{tag}_a"}).set_index("match_id"))
    df = df.merge(pd.concat(mk, axis=1), left_on="match_id", right_index=True, how="left")
    return df.sort_values(["day", "match_id"]).reset_index(drop=True)


def rosters(df):
    """(league, season) -> 本赛季球队集合（赛程赛前即公开，不算泄漏）"""
    return {k: set(g.home_team) | set(g.away_team)
            for k, g in df.groupby(["league", "season"])}


def _nll(params, y_h, y_a, hidx, aidx, w, n, s, off):
    atk, dfc, ha = params[:n], params[n:2 * n], params[2 * n]
    lam_h = np.exp(atk[hidx] - dfc[aidx] + ha)
    lam_a = np.exp(atk[aidx] - dfc[hidx])
    ll = y_h * np.log(lam_h) - lam_h + y_a * np.log(lam_a) - lam_a
    m, md = atk.mean(), dfc.mean()
    ra, rd = atk - m - off, dfc - md - off
    f = -(w * ll).sum() + 1e3 * m ** 2 + s * ((ra ** 2).sum() + (rd ** 2).sum())
    r_h, r_a = w * (y_h - lam_h), w * (y_a - lam_a)
    g_atk = -(np.bincount(hidx, r_h, n) + np.bincount(aidx, r_a, n)) + 2e3 * m / n \
        + 2 * s * (ra - ra.mean())
    g_dfc = np.bincount(aidx, r_h, n) + np.bincount(hidx, r_a, n) + 2 * s * (rd - rd.mean())
    return f, np.concatenate([g_atk, g_dfc, [-r_h.sum()]])


def fit(tr, cfg, season, roster, prev_roster, cut):
    """tr: 截止日 cut 前的本联赛已赛场次。返回参数字典。"""
    w = np.exp(-cfg["xi"] * (cut - tr["day"].to_numpy(float)))
    if cfg["prev_w"] != 1.0:
        w = w * np.where(tr["season"].to_numpy() == season, 1.0, cfg["prev_w"])
    if cfg["red_w"] != 1.0:
        w = w * np.where(tr["red"].to_numpy(), cfg["red_w"], 1.0)
    teams = sorted(set(tr.home_team) | set(tr.away_team) | roster)
    n = len(teams)
    ix = {t: i for i, t in enumerate(teams)}
    hidx = tr["home_team"].map(ix).to_numpy()
    aidx = tr["away_team"].map(ix).to_numpy()
    hg, ag = tr["hg"].to_numpy(float), tr["ag"].to_numpy(float)
    y_h, y_a = cfg["wg"] * hg, cfg["wg"] * ag
    for col, wt in [("xg", cfg["wx"]), ("sot", cfg["ws"])]:
        if wt == 0:
            continue
        sh, sa = tr[f"{col}_h"].to_numpy(float), tr[f"{col}_a"].to_numpy(float)
        has = ~np.isnan(sh)
        k = (w[has] * (hg[has] + ag[has])).sum() / max((w[has] * (sh[has] + sa[has])).sum(), 1e-9)
        y_h = y_h + wt * np.where(has, k * np.nan_to_num(sh), hg)
        y_a = y_a + wt * np.where(has, k * np.nan_to_num(sa), ag)
    off = np.zeros(n)
    if cfg["prom_c"] and prev_roster:
        for t in roster - prev_roster:
            off[ix[t]] = -cfg["prom_c"]
    x0 = np.array([0.3] * n + [0.1] * n + [0.3])
    res = minimize(_nll, x0, jac=True, args=(y_h, y_a, hidx, aidx, w, n, cfg["shrink"], off),
                   method="L-BFGS-B", options={"maxiter": 1000, "ftol": 1e-10})
    atk, dfc, ha = res.x[:n], res.x[n:2 * n], res.x[2 * n]
    lam_h = np.exp(atk[hidx] - dfc[aidx] + ha)
    lam_a = np.exp(atk[aidx] - dfc[hidx])
    rho = minimize_scalar(_rho_nll, bounds=(-0.3, 0.3), method="bounded",
                          args=(hg.astype(int), ag.astype(int), lam_h, lam_a, w)).x
    return dict(ix=ix, atk=atk, dfc=dfc, ha=ha, rho=float(rho),
                ma=float(atk.mean()), md=float(dfc.mean()))


def predict(p, home, away):
    """向量化 1x2 + 比分矩阵（与 DixonColesModel.score_matrix 同算法）"""
    ai = np.array([p["atk"][p["ix"][t]] if t in p["ix"] else p["ma"] for t in home])
    di = np.array([p["dfc"][p["ix"][t]] if t in p["ix"] else p["md"] for t in home])
    aj = np.array([p["atk"][p["ix"][t]] if t in p["ix"] else p["ma"] for t in away])
    dj = np.array([p["dfc"][p["ix"][t]] if t in p["ix"] else p["md"] for t in away])
    lh, la = np.exp(ai - dj + p["ha"]), np.exp(aj - di)
    M = poisson.pmf(G[None, :, None], lh[:, None, None]) * poisson.pmf(G[None, None, :], la[:, None, None])
    r = p["rho"]
    M[:, 0, 0] *= 1 - lh * la * r
    M[:, 0, 1] *= 1 + lh * r
    M[:, 1, 0] *= 1 + la * r
    M[:, 1, 1] *= 1 - r
    M /= M.sum(axis=(1, 2), keepdims=True)
    ph = np.tril(M, -1).sum(axis=(1, 2))
    pd_ = np.trace(M, axis1=1, axis2=2)
    return np.stack([ph, pd_, 1 - ph - pd_, lh, la], 1)


def run(df, cfg, tests=TESTS, leagues=LEAGUES):
    """返回 match_id, league, season, actual, p_h, p_d, p_a"""
    cfg = {**BASE, **cfg}
    ros = rosters(df)
    out = []
    for lg in leagues:
        L = df[df.league == lg]
        for s in tests:
            T = L[L.season == s]
            key = T["match_date"].str[:7] if cfg["refit"] == "monthly" else T["match_date"]
            prev = SEASONS[SEASONS.index(s) - 1]
            for _, g in T.groupby(key, sort=True):
                cut = g["day"].min()
                tr = L[(L["day"] < cut) & ((cfg["window"] == 0) | (L["day"] >= cut - cfg["window"]))]
                p = fit(tr, cfg, s, ros[(lg, s)], ros.get((lg, prev), set()), cut)
                P = predict(p, g.home_team.to_numpy(), g.away_team.to_numpy())
                out.append(pd.DataFrame({"match_id": g.match_id.to_numpy(), "league": lg,
                                         "season": s, "actual": g.actual.to_numpy(),
                                         "p_h": P[:, 0], "p_d": P[:, 1], "p_a": P[:, 2],
                                         "lam_h": P[:, 3], "lam_a": P[:, 4], "rho": p["rho"]}))
    return pd.concat(out, ignore_index=True)


def ll(r):
    P = r[["p_h", "p_d", "p_a"]].to_numpy()
    return -np.log(np.clip(P[np.arange(len(P)), r["actual"].to_numpy()], 1e-7, None))


def hit(r):
    return (r[["p_h", "p_d", "p_a"]].to_numpy().argmax(1) == r["actual"].to_numpy()).astype(float)


def paired(a, b, f=ll):
    m = a[["match_id"]].assign(x=f(a)).merge(b[["match_id"]].assign(y=f(b)), on="match_id")
    d = m.x - m.y
    return len(d), d.mean(), d.std(ddof=1) / np.sqrt(len(d))
