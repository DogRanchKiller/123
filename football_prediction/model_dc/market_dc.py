"""
model_dc/market_dc.py  v1.0.0
市场版 Dixon-Coles（dc_market）：用"进球与历史赔率反推 λ 的混合"估计攻防实力，给没有赔率的场次兜底。
  每场历史比赛的 λ 由该场赔率反推（有收盘价用收盘价，否则用赛前平均；胜平负 + 大小2.5 按比例去水），
  目标值 y = w·进球 + (1−w)·k·λ，k = 训练窗口内 进球总数/λ 总数；缺赔率的场次 y 取进球。
  拟合流程（准泊松似然、时间衰减、收缩、rho 用真实进球单独拟合）与射正版相同。
  λ 反推用独立泊松近似（不含 rho），只作强度信号；实盘有赔率时仍以 model_market 为准。
  按 docs/modules.md，模型族之间不互相引用，所以这里不调用 model_market 的反推。
修改此文件后请同步更新 version.py 中 "model_dc_market" 的版本号。
"""
import sqlite3

import numpy as np
import pandas as pd
from scipy.stats import poisson

from football_prediction.model_dc.sot_dc import SotDixonColesModel

LAYER_VERSION = "1.0.0"
MODEL_NAME = "dc_market"
GOAL_WEIGHT = 0.3   # 进球权重 w：研究库 1718–2425 选参，2526 留出确认优于 dc_xg（_diag/explore/dc_market.py）
_MAXG = 16          # 比分网格上限；11 时 λ≈3 的 1X2 概率和只有 0.9998，反推偏 0.005


def _probs(lh: np.ndarray, la: np.ndarray) -> np.ndarray:
    """独立泊松下的 (主胜, 客胜, 大2.5)，形状 (n, 3)。"""
    k = np.arange(_MAXG)
    ph, pa = poisson.pmf(k, lh[:, None]), poisson.pmf(k, la[:, None])
    joint = ph[:, :, None] * pa[:, None, :]
    home = np.tril(np.ones((_MAXG, _MAXG)), -1).astype(bool)
    under = (k[:, None] + k[None, :]) <= 2
    return np.stack([joint[:, home].sum(1), joint[:, home.T].sum(1),
                     1 - joint[:, under].sum(1)], axis=1)


def lambdas_from_odds(h, d, a, over=None, under=None, iters: int = 30) -> tuple[np.ndarray, np.ndarray]:
    """
    向量化反推 (λ主, λ客)：胜平负（与大小2.5，若有）去水后的概率做高斯-牛顿最小二乘。
    缺胜平负的行返回 NaN；缺大小球的行只拟合主胜 / 客胜。
    """
    h, d, a = (np.asarray(x, dtype=float) for x in (h, d, a))
    n = len(h)
    over = np.full(n, np.nan) if over is None else np.asarray(over, dtype=float)
    under = np.full(n, np.nan) if under is None else np.asarray(under, dtype=float)
    ok = (h > 1) & (d > 1) & (a > 1)
    inv = np.stack([1 / h, 1 / d, 1 / a], axis=1)
    p1x2 = inv / inv.sum(1, keepdims=True)
    has_ou = ok & (over > 1) & (under > 1)
    p_over = np.where(has_ou, (1 / over) / (1 / over + 1 / under), 0.5)
    target = np.stack([p1x2[:, 0], p1x2[:, 2], p_over], axis=1)
    wts = np.stack([np.ones(n), np.ones(n), has_ou.astype(float)], axis=1)

    x = np.log(np.stack([np.full(n, 1.45), np.full(n, 1.15)], axis=1))
    x[:, 0] += np.where(ok, (p1x2[:, 0] - p1x2[:, 2]) * 0.8, 0)
    x[:, 1] -= np.where(ok, (p1x2[:, 0] - p1x2[:, 2]) * 0.8, 0)
    eps = 1e-4
    for _ in range(iters):
        lh, la = np.exp(x[:, 0]), np.exp(x[:, 1])
        r = (_probs(lh, la) - target) * wts
        jh = (_probs(lh * np.exp(eps), la) - _probs(lh, la)) / eps * wts
        ja = (_probs(lh, la * np.exp(eps)) - _probs(lh, la)) / eps * wts
        J = np.stack([jh, ja], axis=2)                       # (n, 3, 2)
        JtJ = np.einsum("nij,nik->njk", J, J) + 1e-9 * np.eye(2)
        step = np.linalg.solve(JtJ, np.einsum("nij,ni->nj", J, r)[..., None])[..., 0]
        x = np.clip(x - step, np.log(0.1), np.log(6.0))
        if np.abs(step).max() < 1e-7:
            break
    lh, la = np.exp(x[:, 0]), np.exp(x[:, 1])
    return np.where(ok, lh, np.nan), np.where(ok, la, np.nan)


class MarketDixonColesModel(SotDixonColesModel):
    MODEL_VER = LAYER_VERSION

    def __init__(self, goal_weight: float = GOAL_WEIGHT, **kw):
        super().__init__(goal_weight=goal_weight, **kw)

    def _load(self, conn: sqlite3.Connection, league: str,
              cutoff_date: str) -> pd.DataFrame:
        df = pd.read_sql_query(
            """SELECT m.match_date, m.home_team, m.away_team, m.home_goals, m.away_goals,
                      o.avg_h, o.avg_d, o.avg_a, o.avgc_h, o.avgc_d, o.avgc_a,
                      o.avg_over25, o.avg_under25, o.avgc_over25, o.avgc_under25
               FROM matches m LEFT JOIN match_odds o ON m.match_id = o.match_id
               WHERE m.league = ? AND m.match_date < ? AND m.home_goals IS NOT NULL
               ORDER BY m.match_date""",
            conn, params=(league, cutoff_date),
        )
        # 收盘价三项齐全才用收盘价，否则用赛前平均（同一盘口不混用两组价格）
        c1 = df[["avgc_h", "avgc_d", "avgc_a"]].notna().all(axis=1)
        c2 = df[["avgc_over25", "avgc_under25"]].notna().all(axis=1)
        pick = lambda cond, c, o: np.where(cond, df[c], df[o])
        lh, la = lambdas_from_odds(pick(c1, "avgc_h", "avg_h"), pick(c1, "avgc_d", "avg_d"),
                                   pick(c1, "avgc_a", "avg_a"),
                                   pick(c2, "avgc_over25", "avg_over25"),
                                   pick(c2, "avgc_under25", "avg_under25"))
        df["sig_h"], df["sig_a"] = lh, la
        return df[["match_date", "home_team", "away_team", "home_goals", "away_goals",
                   "sig_h", "sig_a"]]
