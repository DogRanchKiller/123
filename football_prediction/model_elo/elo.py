"""
model_elo/elo.py  v1.1.0
Elo 基线模型：用球队评分差预测胜/平/负概率。
v1.1.0: 更新步长按净胜球放大 K·ln(1+|净胜|)（平局为 K）；主场优势 60 分；
        1X2 改为有序 logit：P(主胜)=σ(a·d−b)，P(主胜或平)=σ(a·d+b)，d=评分差/100，
        a、b 用 cutoff 前每场的赛前评分差拟合（无未来信息）。
        v1.0.0 的经验平局公式与 dc_xg 融合时最优权重≈0，没有增益。
修改此文件后请同步更新 version.py 中 "model_elo" 的版本号。
"""
import math
import sqlite3

import numpy as np
import pandas as pd
from scipy.optimize import minimize

LAYER_VERSION = "1.1.0"

# Elo 参数
K = 20.0          # 基础更新步长
HOME_ADV = 60.0   # 主场优势（分）
BASE_RATING = 1500.0
MIN_FIT = 50      # 少于此场数时不拟合 logit，用默认参数
DEFAULT_AB = (0.5, 0.3)


def _expected_home(rating_diff: float) -> float:
    """主队预期得分（含主场优势），范围 0~1"""
    return 1.0 / (1.0 + math.pow(10, -rating_diff / 400.0))


def ordlogit(d, a: float, b: float) -> np.ndarray:
    """有序 logit：d=评分差/100 -> [主胜, 平, 客胜]"""
    d = np.asarray(d, float)
    c1 = 1 / (1 + np.exp(-(a * d - b)))   # P(主胜)
    c2 = 1 / (1 + np.exp(-(a * d + b)))   # P(主胜或平)
    return np.stack([c1, c2 - c1, 1 - c2], -1)


def fit_ordlogit(d, y) -> tuple[float, float]:
    """用评分差 d（/100）与结果 y（0主胜 1平 2客胜）拟合 (a, b)"""
    d, y = np.asarray(d, float), np.asarray(y, int)
    if len(y) < MIN_FIT:
        return DEFAULT_AB
    idx = np.arange(len(y))
    nll = lambda x: -np.log(np.clip(ordlogit(d, *x)[idx, y], 1e-12, None)).sum()
    return tuple(float(v) for v in minimize(nll, DEFAULT_AB, method="Nelder-Mead").x)


class EloModel:
    """顺序更新 Elo 评分；1X2 用拟合的有序 logit 映射。"""
    def __init__(self, k: float = K, home_adv: float = HOME_ADV):
        self.k = k
        self.home_adv = home_adv
        self.ratings: dict[str, float] = {}
        self.ab = DEFAULT_AB

    def _rating(self, team: str) -> float:
        return self.ratings.get(team, BASE_RATING)

    def diff(self, home: str, away: str) -> float:
        """赛前评分差（含主场优势）"""
        return self._rating(home) + self.home_adv - self._rating(away)

    def update_one(self, home: str, away: str,
                   home_goals: int, away_goals: int) -> None:
        """用一场比赛更新双方评分（步长随净胜球放大）"""
        e_home = _expected_home(self.diff(home, away))
        if home_goals > away_goals:
            s_home = 1.0
        elif home_goals == away_goals:
            s_home = 0.5
        else:
            s_home = 0.0
        margin = abs(home_goals - away_goals)
        k = self.k * math.log1p(margin) if margin else self.k
        delta = k * (s_home - e_home)
        self.ratings[home] = self._rating(home) + delta
        self.ratings[away] = self._rating(away) - delta

    def fit(self, conn: sqlite3.Connection, league: str,
            cutoff_date: str) -> None:
        """按时间顺序用 cutoff_date 前的比赛更新评分，并用赛前评分差拟合有序 logit"""
        df = pd.read_sql_query(
            """SELECT match_date, home_team, away_team, home_goals, away_goals
               FROM matches
               WHERE league = ? AND match_date < ? AND home_goals IS NOT NULL
               ORDER BY match_date""",
            conn, params=(league, cutoff_date),
        )
        diffs, ys = [], []
        for _, r in df.iterrows():
            hg, ag = int(r["home_goals"]), int(r["away_goals"])
            diffs.append(self.diff(r["home_team"], r["away_team"]) / 100)
            ys.append(0 if hg > ag else 1 if hg == ag else 2)
            self.update_one(r["home_team"], r["away_team"], hg, ag)
        self.ab = fit_ordlogit(diffs, ys)

    def predict(self, home: str, away: str) -> dict:
        """返回 1X2 概率及评分"""
        ph, pdraw, pa = ordlogit(self.diff(home, away) / 100, *self.ab)
        return {
            "home_win":  round(float(ph), 4),
            "draw":      round(float(pdraw), 4),
            "away_win":  round(float(pa), 4),
            "home_elo":  round(self._rating(home), 2),
            "away_elo":  round(self._rating(away), 2),
            "model_ver": LAYER_VERSION,
        }
