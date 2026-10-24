"""
model_dc/dixon_coles.py  v1.3.0
Dixon-Coles 双泊松模型 — v1.3.0 变更：
  单队攻防参数向联赛均值做 L2 收缩（shrink=0.5）。修复升级队样本极少时
  MLE 发散的问题（德甲 2425 St Pauli 赛季初 attack=-12.2，月度回测 9 月 Log Loss 1.38）。
  rho 低比分修正向量化，拟合提速约 45%，shrink=0 时结果与 v1.2.0 完全一致。
v1.2.0：xi=0.005 + 月度重拟合验证为最优配置。
修改此文件后请同步更新 version.py 中 "model_dc" 的版本号。
"""
import sqlite3
import numpy as np
import pandas as pd
from datetime import date
from scipy.optimize import minimize
from scipy.stats import poisson

LAYER_VERSION = "1.3.0"
MAX_GOALS = 8
XI = 0.005   # 时间衰减系数，约 139 天半衰期
SHRINK = 0.5  # 单队参数收缩强度，2324 选参、2425 确认（三联赛月度均值 1.0137→0.9989）


def _rho_correction(home_g: int, away_g: int,
                    lam_h: float, lam_a: float, rho: float) -> float:
    """低比分修正项（Dixon-Coles 论文 Eq.5）"""
    if home_g == 0 and away_g == 0:
        return 1 - lam_h * lam_a * rho
    if home_g == 0 and away_g == 1:
        return 1 + lam_h * rho
    if home_g == 1 and away_g == 0:
        return 1 + lam_a * rho
    if home_g == 1 and away_g == 1:
        return 1 - rho
    return 1.0


def _neg_log_likelihood(params: np.ndarray, teams: list[str],
                        hg_arr: np.ndarray, ag_arr: np.ndarray,
                        hidx: np.ndarray, aidx: np.ndarray,
                        weights: np.ndarray, shrink: float = 0.0) -> float:
    """加权负对数似然，含 L2 正则"""
    n = len(teams)
    atk = params[:n]
    dfc = params[n:2*n]
    home_adv = params[2 * n]
    rho      = params[2 * n + 1]

    lam_h = np.exp(atk[hidx] - dfc[aidx] + home_adv)
    lam_a = np.exp(atk[aidx] - dfc[hidx])

    ll = poisson.logpmf(hg_arr, lam_h) + poisson.logpmf(ag_arr, lam_a)

    # 低比分修正（向量化，与 _rho_correction 逐场结果一致）
    tau = np.ones_like(lam_h)
    m00 = (hg_arr == 0) & (ag_arr == 0)
    m01 = (hg_arr == 0) & (ag_arr == 1)
    m10 = (hg_arr == 1) & (ag_arr == 0)
    m11 = (hg_arr == 1) & (ag_arr == 1)
    tau[m00] = 1 - lam_h[m00] * lam_a[m00] * rho
    tau[m01] = 1 + lam_h[m01] * rho
    tau[m10] = 1 + lam_a[m10] * rho
    tau[m11] = 1 - rho
    ll += np.where(tau > 0, np.log(np.clip(tau, 1e-12, None)), -10.0)

    # 加权求和（时间衰减）
    penalty = 1e3 * (atk.mean() ** 2)
    # v1.3.0：单队攻防参数向联赛均值收缩，防止样本极少的球队参数发散
    if shrink > 0:
        penalty += shrink * (((atk - atk.mean()) ** 2).sum()
                             + ((dfc - dfc.mean()) ** 2).sum())
    return -(weights * ll).sum() + penalty


class DixonColesModel:
    def __init__(self, xi: float = XI, shrink: float = SHRINK):
        self.xi = xi
        self.shrink = shrink
        self.attack:      dict[str, float] = {}
        self.defence:     dict[str, float] = {}
        self.home_adv:    float = 0.0
        self.rho:         float = 0.0
        self.teams:       list[str] = []
        # 冷启动：联赛均值参数（fit 后填入）
        self._mean_attack:  float = 0.0
        self._mean_defence: float = 0.0

    def fit(self, conn: sqlite3.Connection, league: str,
            cutoff_date: str) -> None:
        """
        拟合参数。
        - 时间衰减：每场权重 = exp(-xi * days_to_cutoff)
        - 冷启动：缓存训练集均值攻防参数
        """
        df = pd.read_sql_query(
            """SELECT match_date, home_team, away_team, home_goals, away_goals
               FROM matches
               WHERE league = ? AND match_date < ? AND home_goals IS NOT NULL
               ORDER BY match_date""",
            conn, params=(league, cutoff_date),
        )

        # 时间衰减权重
        cutoff = date.fromisoformat(cutoff_date)
        days_ago = df["match_date"].apply(
            lambda d: (cutoff - date.fromisoformat(d)).days
        ).to_numpy(dtype=float)
        weights = np.exp(-self.xi * days_ago)

        teams = sorted(set(df["home_team"]) | set(df["away_team"]))
        self.teams = teams
        n = len(teams)

        team_idx = {t: i for i, t in enumerate(teams)}
        hidx = np.array([team_idx[t] for t in df["home_team"]])
        aidx = np.array([team_idx[t] for t in df["away_team"]])
        hg   = df["home_goals"].to_numpy(dtype=int)
        ag   = df["away_goals"].to_numpy(dtype=int)

        x0 = np.array([0.3] * n + [0.1] * n + [0.3, -0.1])

        result = minimize(
            _neg_log_likelihood, x0,
            args=(teams, hg, ag, hidx, aidx, weights, self.shrink),
            method="L-BFGS-B",
            options={"maxiter": 500, "ftol": 1e-9},
        )

        for i, t in enumerate(teams):
            self.attack[t]  = result.x[i]
            self.defence[t] = result.x[n + i]
        self.home_adv = result.x[2 * n]
        self.rho      = result.x[2 * n + 1]

        # 缓存均值用于冷启动
        self._mean_attack  = float(np.mean([self.attack[t]  for t in teams]))
        self._mean_defence = float(np.mean([self.defence[t] for t in teams]))

    def _get_params(self, team: str) -> tuple[float, float]:
        """取球队参数，未见过的球队用联赛均值兜底"""
        return (
            self.attack.get(team,  self._mean_attack),
            self.defence.get(team, self._mean_defence),
        )

    def _lambda(self, home: str, away: str) -> tuple[float, float]:
        atk_h, dfc_h = self._get_params(home)
        atk_a, dfc_a = self._get_params(away)
        lam_h = np.exp(atk_h - dfc_a + self.home_adv)
        lam_a = np.exp(atk_a - dfc_h)
        return lam_h, lam_a

    def score_matrix(self, home: str, away: str,
                     max_goals: int = MAX_GOALS) -> np.ndarray:
        lam_h, lam_a = self._lambda(home, away)
        m = np.outer(
            [poisson.pmf(i, lam_h) for i in range(max_goals + 1)],
            [poisson.pmf(j, lam_a) for j in range(max_goals + 1)],
        )
        for i in range(min(2, max_goals + 1)):
            for j in range(min(2, max_goals + 1)):
                m[i, j] *= _rho_correction(i, j, lam_h, lam_a, self.rho)
        m /= m.sum()
        return m

    def predict_1x2(self, home: str, away: str) -> dict:
        m = self.score_matrix(home, away)
        home_win = float(np.tril(m, -1).sum())
        draw     = float(np.trace(m))
        away_win = float(np.triu(m, 1).sum())
        return {
            "home_win":  round(home_win, 4),
            "draw":      round(draw, 4),
            "away_win":  round(away_win, 4),
            "model_ver": LAYER_VERSION,
        }
