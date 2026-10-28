"""
model_dc/dynamic_dc.py  v1.0.0
动态攻防 Dixon-Coles（dc_dyn / dc_dyn_shots）：按比赛日更新的攻防实力（扩展卡尔曼近似），由开发线 dev v0.2
（_diag/dev_model/dynamic.py）正式化。只并行存档、进成绩单，不进报告、不作主模型或兜底。
  λ主 = exp(a主 − d客 + H)，λ客 = exp(a客 − d主)；每个参数有均值与方差（不记协方差）。
  每个联赛一条滤波，从最早一季逐比赛日推进：同一天的比赛先出赛前 λ，再一起更新。
  观测 y = w·进球 + (1−w)·k·信号，k = 此前累计 进球 / 信号；缺信号的场次 y 取进球。
  每个进球观测：S = Σ 相关参数方差，θᵢ += Pᵢ·hᵢ·(y − λ)/(S·λ + 1)，Pᵢ −= Pᵢ²·λ/(S·λ + 1)，hᵢ = +1（a、H）/ −1（d）。
  两场之间方差加 q × 间隔天数；换季时各队向联赛均值收缩到 c 倍并加方差 V_SEASON；
  上季不在本联赛的球队取上季离开那些球队的均值，方差 P_NEW。cutoff 落在新赛季开踢前时，按 fixtures 里
  该季球队先做换季；仍不认识的球队用最近一次换季的新来球队均值。
  rho：攻防由滤波给出后，用赛前 λ 与真实进球、时间衰减权重（XI）单独拟合。
  两个版本（选参 2324–2425，2526 + 2627 留出，11 联赛 n=4590，对 dc_market 胜平负 LL）：
    dc_dyn        信号 = 历史赔率反推 λ，w=0、q=0.016、c=1.0：−0.0069±0.0016（显著）
    dc_dyn_shots  信号 = 射门，不用任何赔率，w=0.7、q=3e-5、c=1.0：+0.0015±0.0013（不显著）
修改此文件后请同步更新 version.py 中 "model_dc_dyn" 的版本号。
"""
import math
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from football_prediction.model_dc.dixon_coles import XI, DixonColesModel
from football_prediction.model_dc.market_dc import lambdas_from_odds
from football_prediction.model_dc.sot_dc import _rho_nll

LAYER_VERSION = "1.0.0"
P0, P_NEW, V_SEASON = 0.10, 0.10, 0.02     # 首季初始方差、新来球队方差、换季加的方差
H0, P_H, Q_H = 0.25, 0.01, 1e-6            # 主场优势初值、初始方差、每场加的方差


def run_filter(df: pd.DataFrame, w: float, q: float, c: float, next_teams: set | None = None):
    """
    df：按日期排序的完赛场次（season, day, home_team, away_team, hg, ag, sig_h, sig_a）。
    next_teams：cutoff 所在的新赛季尚无完赛场次时，该季的球队（来自 fixtures），用于先做换季。
    返回 (state, lams)：state 含 attack / defence / H / new_a / new_d；lams 为每场赛前 (λ主, λ客)，与 df 行序一致。
    """
    mu, var, last = {}, {}, {}           # 键 ("a"|"d", 队)；last[队] = 上次比赛的 day
    st = {"H": H0, "PH": P_H, "season": None, "prev": set(), "new_a": 0.0, "new_d": 0.0}

    def new_season(teams: set) -> None:
        prev = st["prev"]
        if st["season"] is None:
            for t in teams:
                for p in "ad":
                    mu[p, t], var[p, t] = 0.0, P0
        else:
            gone = prev - teams
            m_a = np.mean([mu["a", t] for t in prev])
            m_d = np.mean([mu["d", t] for t in prev])
            st["new_a"] = float(np.mean([mu["a", t] for t in gone])) if gone else float(m_a)
            st["new_d"] = float(np.mean([mu["d", t] for t in gone])) if gone else float(m_d)
            for t in teams:
                if t in prev:
                    mu["a", t] = m_a + c * (mu["a", t] - m_a)
                    mu["d", t] = m_d + c * (mu["d", t] - m_d)
                    var["a", t] += V_SEASON
                    var["d", t] += V_SEASON
                else:
                    mu["a", t], mu["d", t] = st["new_a"], st["new_d"]
                    var["a", t] = var["d", t] = P_NEW
                last.pop(t, None)
        st["prev"] = teams

    order, lams = [], []
    k_num = k_den = 0.0
    for (s, day), g in df.groupby(["season", "day"], sort=True):
        if s != st["season"]:
            new_season(set(df.home_team[df.season == s]) | set(df.away_team[df.season == s]))
            st["season"] = s
        for t in set(g.home_team) | set(g.away_team):     # 过程噪声
            if t in last:
                for p in "ad":
                    var[p, t] += q * (day - last[t])
            last[t] = day
        st["PH"] += Q_H * len(g)
        rows = list(g.itertuples())
        H = st["H"]
        lam = [(math.exp(mu["a", r.home_team] - mu["d", r.away_team] + H),
                math.exp(mu["a", r.away_team] - mu["d", r.home_team])) for r in rows]
        order += list(g.index)
        lams += lam
        k = k_num / k_den if k_den > 0 else 1.0
        for r, (lh, la) in zip(rows, lam):
            for lm, goals, sig, keys in (
                    (lh, r.hg, r.sig_h, (("a", r.home_team, 1), ("d", r.away_team, -1), ("H", None, 1))),
                    (la, r.ag, r.sig_a, (("a", r.away_team, 1), ("d", r.home_team, -1)))):
                y = goals if sig != sig else w * goals + (1 - w) * k * sig
                S = sum(st["PH"] if p == "H" else var[p, t] for p, t, _ in keys)
                den = S * lm + 1.0
                for p, t, h in keys:
                    P = st["PH"] if p == "H" else var[p, t]
                    step, newP = P * h * (y - lm) / den, P - P * P * lm / den
                    if p == "H":
                        st["H"], st["PH"] = st["H"] + step, newP
                    else:
                        mu[p, t], var[p, t] = mu[p, t] + step, newP
        ok = g.sig_h.notna()
        k_num += float((g.hg[ok] + g.ag[ok]).sum())
        k_den += float((g.sig_h[ok] + g.sig_a[ok]).sum())
    if next_teams and st["season"] is not None:
        new_season(set(next_teams))
    lam_arr = np.full((len(df), 2), np.nan)
    if order:
        lam_arr[df.index.get_indexer(order)] = lams
    state = {"attack": {t: v for (p, t), v in mu.items() if p == "a"},
             "defence": {t: v for (p, t), v in mu.items() if p == "d"},
             "H": st["H"], "new_a": st["new_a"], "new_d": st["new_d"]}
    return state, lam_arr


class DynamicDixonColesModel(DixonColesModel):
    """赔率版 dc_dyn：信号为历史赔率反推 λ（收盘价齐全用收盘价，否则赛前平均，同 market_dc）。"""
    MODEL_NAME = "dc_dyn"
    MODEL_VER = LAYER_VERSION
    W, Q, C = 0.0, 0.016, 1.0

    def __init__(self, xi: float = XI):
        super().__init__(xi=xi, shrink=0.0)

    def _load(self, conn: sqlite3.Connection, league: str, cutoff_date: str) -> pd.DataFrame:
        df = pd.read_sql_query(
            """SELECT m.season, m.match_date, m.home_team, m.away_team,
                      m.home_goals AS hg, m.away_goals AS ag,
                      o.avg_h, o.avg_d, o.avg_a, o.avgc_h, o.avgc_d, o.avgc_a,
                      o.avg_over25, o.avg_under25, o.avgc_over25, o.avgc_under25
               FROM matches m LEFT JOIN match_odds o ON m.match_id = o.match_id
               WHERE m.league = ? AND m.match_date < ? AND m.home_goals IS NOT NULL
               ORDER BY m.match_date""",
            conn, params=(league, cutoff_date))
        c1 = df[["avgc_h", "avgc_d", "avgc_a"]].notna().all(axis=1)
        c2 = df[["avgc_over25", "avgc_under25"]].notna().all(axis=1)
        pick = lambda cond, a, b: np.where(cond, df[a], df[b])
        df["sig_h"], df["sig_a"] = lambdas_from_odds(
            pick(c1, "avgc_h", "avg_h"), pick(c1, "avgc_d", "avg_d"), pick(c1, "avgc_a", "avg_a"),
            pick(c2, "avgc_over25", "avg_over25"), pick(c2, "avgc_under25", "avg_under25"))
        return df[["season", "match_date", "home_team", "away_team", "hg", "ag", "sig_h", "sig_a"]]

    @staticmethod
    def _next_teams(conn: sqlite3.Connection, league: str, cutoff_date: str,
                    last_season: str | None) -> set:
        """cutoff 之后最早一场赛程所在赛季若不同于最后一个完赛赛季，返回该季球队（新赛季开踢前先换季）。
        库里已有 cutoff 之后的完赛场次（回测）时不用实时赛程。"""
        later = conn.execute("SELECT 1 FROM matches WHERE league = ? AND match_date >= ? LIMIT 1",
                             (league, cutoff_date)).fetchone()
        if later or last_season is None:
            return set()
        row = conn.execute("""SELECT season FROM fixtures WHERE league = ? AND match_date >= ?
                              ORDER BY match_date LIMIT 1""", (league, cutoff_date)).fetchone()
        if row is None or row[0] == last_season:
            return set()
        teams = conn.execute("SELECT home_team, away_team FROM fixtures WHERE league = ? AND season = ?",
                             (league, row[0])).fetchall()
        return {t for pair in teams for t in pair}

    def fit(self, conn: sqlite3.Connection, league: str, cutoff_date: str) -> None:
        df = self._load(conn, league, cutoff_date).reset_index(drop=True)
        df["day"] = (pd.to_datetime(df.match_date) - pd.Timestamp("2000-01-01")).dt.days
        last_season = df.season.iloc[-1] if len(df) else None
        state, lams = run_filter(df, self.W, self.Q, self.C,
                                 self._next_teams(conn, league, cutoff_date, last_season))
        self.attack, self.defence, self.home_adv = state["attack"], state["defence"], state["H"]
        self.teams = sorted(self.attack)
        self._mean_attack, self._mean_defence = state["new_a"], state["new_d"]
        if not len(df):
            return
        cutoff = date.fromisoformat(cutoff_date)
        days_ago = df.match_date.map(lambda d: (cutoff - date.fromisoformat(d)).days).to_numpy(float)
        self.rho = float(minimize_scalar(
            _rho_nll, bounds=(-0.3, 0.3), method="bounded",
            args=(df.hg.to_numpy(int), df.ag.to_numpy(int), lams[:, 0], lams[:, 1],
                  np.exp(-self.xi * days_ago))).x)

    def predict_1x2(self, home: str, away: str) -> dict:
        out = super().predict_1x2(home, away)
        out["model_ver"] = self.MODEL_VER
        return out


class DynamicShotsDixonColesModel(DynamicDixonColesModel):
    """射门版 dc_dyn_shots：信号为射门（match_stats），不用任何赔率。"""
    MODEL_NAME = "dc_dyn_shots"
    W, Q, C = 0.7, 3e-5, 1.0

    def _load(self, conn: sqlite3.Connection, league: str, cutoff_date: str) -> pd.DataFrame:
        return pd.read_sql_query(
            """SELECT m.season, m.match_date, m.home_team, m.away_team,
                      m.home_goals AS hg, m.away_goals AS ag,
                      s.home_shots AS sig_h, s.away_shots AS sig_a
               FROM matches m LEFT JOIN match_stats s ON m.match_id = s.match_id
               WHERE m.league = ? AND m.match_date < ? AND m.home_goals IS NOT NULL
               ORDER BY m.match_date""",
            conn, params=(league, cutoff_date))
