"""
model_dc/sot_dc.py  v1.0.0
射正版 Dixon-Coles：用"进球与射正的混合"估计攻防实力。
  目标值 y = w·进球 + (1−w)·k·射正，k = 训练窗口内 进球总数/射正总数（把射正折算到进球尺度）。
  w=1 等价于只用进球；w 越小越依赖射正（噪声更小，但忽略终结能力差异）。
  攻防参数用加权准泊松似然拟合（y 可为非整数），解析梯度；时间衰减、收缩与 DC v1.3.0 相同。
  rho 在攻防参数固定后，用真实进球单独拟合。
  缺技术统计的场次 y 直接取进球。
预测接口（score_matrix / predict_1x2）沿用 DixonColesModel。
修改此文件后请同步更新 version.py 中 "model_sot" 的版本号。
"""
import sqlite3
import numpy as np
import pandas as pd
from datetime import date
from scipy.optimize import minimize, minimize_scalar

from football_prediction.model_dc.dixon_coles import DixonColesModel, XI, SHRINK

LAYER_VERSION = "1.0.0"
GOAL_WEIGHT = 0.7   # 进球权重 w：2324+2425 选参得 0.7，2526 留出确认优于 DC


def _quasi_nll(params, y_h, y_a, hidx, aidx, weights, n, shrink):
    """加权准泊松负对数似然及其解析梯度（省略与参数无关的 log y! 项）"""
    atk, dfc = params[:n], params[n:2 * n]
    home_adv = params[2 * n]
    lam_h = np.exp(atk[hidx] - dfc[aidx] + home_adv)
    lam_a = np.exp(atk[aidx] - dfc[hidx])

    ll = y_h * np.log(lam_h) - lam_h + y_a * np.log(lam_a) - lam_a
    m = atk.mean()
    f = -(weights * ll).sum() + 1e3 * m ** 2
    if shrink > 0:
        f += shrink * (((atk - m) ** 2).sum() + ((dfc - dfc.mean()) ** 2).sum())

    r_h = weights * (y_h - lam_h)
    r_a = weights * (y_a - lam_a)
    g_atk = -(np.bincount(hidx, r_h, n) + np.bincount(aidx, r_a, n)) + 2e3 * m / n
    g_dfc = np.bincount(aidx, r_h, n) + np.bincount(hidx, r_a, n)
    if shrink > 0:
        g_atk += 2 * shrink * (atk - m)
        g_dfc += 2 * shrink * (dfc - dfc.mean())
    return f, np.concatenate([g_atk, g_dfc, [-r_h.sum()]])


def _rho_nll(rho, hg, ag, lam_h, lam_a, weights):
    """固定 lambda 后，低比分修正项的加权负对数似然（与 DC 向量化写法一致）"""
    tau = np.ones_like(lam_h)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    tau[m00] = 1 - lam_h[m00] * lam_a[m00] * rho
    tau[m01] = 1 + lam_h[m01] * rho
    tau[m10] = 1 + lam_a[m10] * rho
    tau[m11] = 1 - rho
    return -(weights * np.where(tau > 0, np.log(np.clip(tau, 1e-12, None)), -10.0)).sum()


class SotDixonColesModel(DixonColesModel):
    MODEL_VER = LAYER_VERSION

    def __init__(self, goal_weight: float = GOAL_WEIGHT,
                 xi: float = XI, shrink: float = SHRINK):
        super().__init__(xi=xi, shrink=shrink)
        self.goal_weight = goal_weight
        self.sot_k: float = 0.0   # 射正→进球 折算系数

    # 子类（如 xG 版）覆盖 _load / _targets 即可换信号，拟合流程共用
    def _load(self, conn: sqlite3.Connection, league: str,
              cutoff_date: str) -> pd.DataFrame:
        """返回 match_date, home_team, away_team, home_goals, away_goals, sig_h, sig_a"""
        return pd.read_sql_query(
            """SELECT m.match_date, m.home_team, m.away_team,
                      m.home_goals, m.away_goals, s.home_sot AS sig_h, s.away_sot AS sig_a
               FROM matches m LEFT JOIN match_stats s ON m.match_id = s.match_id
               WHERE m.league = ? AND m.match_date < ? AND m.home_goals IS NOT NULL
               ORDER BY m.match_date""",
            conn, params=(league, cutoff_date),
        )

    def _targets(self, hg, ag, sig_h, sig_a, weights):
        """y = w·进球 + (1−w)·k·射正；缺射正的场次 y 取进球"""
        has = ~np.isnan(sig_h)
        w_has = weights[has]
        self.sot_k = float((w_has * (hg[has] + ag[has])).sum()
                           / max((w_has * (sig_h[has] + sig_a[has])).sum(), 1e-9))
        w = self.goal_weight
        y_h = np.where(has, w * hg + (1 - w) * self.sot_k * np.nan_to_num(sig_h), hg)
        y_a = np.where(has, w * ag + (1 - w) * self.sot_k * np.nan_to_num(sig_a), ag)
        return y_h, y_a

    def fit(self, conn: sqlite3.Connection, league: str,
            cutoff_date: str) -> None:
        df = self._load(conn, league, cutoff_date)

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
        hg = df["home_goals"].to_numpy(dtype=float)
        ag = df["away_goals"].to_numpy(dtype=float)

        y_h, y_a = self._targets(hg, ag,
                                 df["sig_h"].to_numpy(dtype=float),
                                 df["sig_a"].to_numpy(dtype=float), weights)

        x0 = np.array([0.3] * n + [0.1] * n + [0.3])
        res = minimize(
            _quasi_nll, x0, jac=True,
            args=(y_h, y_a, hidx, aidx, weights, n, self.shrink),
            method="L-BFGS-B", options={"maxiter": 1000, "ftol": 1e-10},
        )
        for i, t in enumerate(teams):
            self.attack[t] = res.x[i]
            self.defence[t] = res.x[n + i]
        self.home_adv = res.x[2 * n]

        # rho：攻防固定，用真实进球拟合低比分修正
        atk, dfc = res.x[:n], res.x[n:2 * n]
        lam_h = np.exp(atk[hidx] - dfc[aidx] + self.home_adv)
        lam_a = np.exp(atk[aidx] - dfc[hidx])
        self.rho = float(minimize_scalar(
            _rho_nll, bounds=(-0.3, 0.3), method="bounded",
            args=(hg.astype(int), ag.astype(int), lam_h, lam_a, weights),
        ).x)

        self._mean_attack = float(atk.mean())
        self._mean_defence = float(dfc.mean())

    def predict_1x2(self, home: str, away: str) -> dict:
        out = super().predict_1x2(home, away)
        out["model_ver"] = self.MODEL_VER
        return out
