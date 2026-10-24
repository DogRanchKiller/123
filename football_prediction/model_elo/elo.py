"""
model_elo/elo.py  v1.0.0
Elo 基线模型：用球队评分差预测胜/平/负概率。
修改此文件后请同步更新 version.py 中 "model_elo" 的版本号。
"""
import math
import sqlite3
import pandas as pd

LAYER_VERSION = "1.0.0"

# 标准 Elo 参数
K = 20.0          # 更新步长
HOME_ADV = 65.0   # 主场优势（分）
BASE_RATING = 1500.0


def _expected_home(rating_diff: float) -> float:
    """主队预期得分（含主场优势），范围 0~1"""
    return 1.0 / (1.0 + math.pow(10, -rating_diff / 400.0))


class EloModel:
    """
    顺序更新 Elo 评分，并在任意时点预测 1X2 概率。
    1X2 用 expected_home 映射到三个结果：
      home_win = E + d, away_win = 1 - E - d, draw = (1 - |2E-1|) * d_scale
    其中 d 为经验平局概率。
    """
    def __init__(self, k: float = K, home_adv: float = HOME_ADV):
        self.k = k
        self.home_adv = home_adv
        self.ratings: dict[str, float] = {}

    def _rating(self, team: str) -> float:
        return self.ratings.get(team, BASE_RATING)

    def update_one(self, home: str, away: str,
                   home_goals: int, away_goals: int) -> None:
        """用一场比赛更新双方评分"""
        r_home = self._rating(home) + self.home_adv
        r_away = self._rating(away)
        e_home = _expected_home(r_home - r_away)

        # 实际得分：胜1 平0.5 负0
        if home_goals > away_goals:
            s_home = 1.0
        elif home_goals == away_goals:
            s_home = 0.5
        else:
            s_home = 0.0

        delta = self.k * (s_home - e_home)
        self.ratings[home] = self._rating(home) + delta
        self.ratings[away] = self._rating(away) - delta

    def fit(self, conn: sqlite3.Connection, league: str,
            cutoff_date: str) -> None:
        """按时间顺序用 cutoff_date 前的所有比赛更新评分"""
        df = pd.read_sql_query(
            """SELECT match_date, home_team, away_team, home_goals, away_goals
               FROM matches
               WHERE league = ? AND match_date < ? AND home_goals IS NOT NULL
               ORDER BY match_date""",
            conn, params=(league, cutoff_date),
        )
        for _, r in df.iterrows():
            self.update_one(r["home_team"], r["away_team"],
                            int(r["home_goals"]), int(r["away_goals"]))

    def predict(self, home: str, away: str) -> dict:
        """返回 1X2 概率及评分"""
        diff = (self._rating(home) + self.home_adv) - self._rating(away)
        e_home = _expected_home(diff)

        # 经验平局概率：两队越接近，平局越多
        draw_prob = 0.28 * (1.0 - abs(2 * e_home - 1))
        home_win = max(e_home - draw_prob / 2, 0.0)
        away_win = max((1.0 - e_home) - draw_prob / 2, 0.0)
        # 归一化
        total = home_win + draw_prob + away_win
        return {
            "home_win":  round(home_win / total, 4),
            "draw":      round(draw_prob / total, 4),
            "away_win":  round(away_win / total, 4),
            "home_elo":  round(self._rating(home), 2),
            "away_elo":  round(self._rating(away), 2),
            "model_ver": LAYER_VERSION,
        }
