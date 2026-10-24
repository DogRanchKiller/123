"""
model_dc/xg_dc.py  v1.0.0
xG 版 Dixon-Coles：用"进球与 xG 的混合"估计攻防实力（xG 来自 understat，match_xg 表）。
  目标值 y = w·进球 + (1−w)·k·xG，k = 训练窗口内 进球总数/xG 总数（通常接近 1）。
  拟合流程（准泊松似然、时间衰减、收缩、rho 用真实进球单独拟合）与射正版完全相同，
  只替换数据读取与信号列；缺 xG 的场次 y 取进球。
修改此文件后请同步更新 version.py 中 "model_xg" 的版本号。
"""
import sqlite3
import pandas as pd

from football_prediction.model_dc.sot_dc import SotDixonColesModel

LAYER_VERSION = "1.0.0"
GOAL_WEIGHT = 0.3   # 进球权重 w：2324+2425 选参得 0.3，2526 留出确认优于 DC


class XgDixonColesModel(SotDixonColesModel):
    MODEL_VER = LAYER_VERSION

    def __init__(self, goal_weight: float = GOAL_WEIGHT, **kw):
        super().__init__(goal_weight=goal_weight, **kw)

    def _load(self, conn: sqlite3.Connection, league: str,
              cutoff_date: str) -> pd.DataFrame:
        return pd.read_sql_query(
            """SELECT m.match_date, m.home_team, m.away_team,
                      m.home_goals, m.away_goals, x.home_xg AS sig_h, x.away_xg AS sig_a
               FROM matches m LEFT JOIN match_xg x ON m.match_id = x.match_id
               WHERE m.league = ? AND m.match_date < ? AND m.home_goals IS NOT NULL
               ORDER BY m.match_date""",
            conn, params=(league, cutoff_date),
        )
