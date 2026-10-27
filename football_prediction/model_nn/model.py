"""
model_nn/model.py  v0.1.0
PyTorch 表格网络（研究中，未过 G1，不进实盘、不存档）。接口与其他模型一致：fit(conn, league, cutoff_date)。
  fit 把联赛组（默认五联赛）的样本表拼起来，按 TrainConfig 的窗口规则取 match_date < cutoff 的场次训练；
  pool="league" 时只用本联赛。预测用 cutoff 前的联赛状态现算特征，比分矩阵用 implied.dc_matrix。
  变体 B 必须给该场赛前赔率（odds 键同 model_market），没有时抛 ValueError。
  模块顶层不 import torch。
修改此文件后请同步更新 version.py 中 "model_nn" 的版本号。
"""
import sqlite3
from datetime import date

import numpy as np
import pandas as pd

from football_prediction.model_market.implied import dc_matrix
from football_prediction.model_nn.dataset import build_table, market_features, state_at
from football_prediction.model_nn.train import Fitted, TrainConfig, train

LAYER_VERSION = "0.1.0"
MODEL_NAME = "nn"
FIVE = ("E0", "D1", "SP1", "I1", "F1")
SIX = ("E1", "N1", "P1", "SC0", "B1", "T1")


def group_of(league: str) -> tuple[str, ...]:
    return FIVE if league in FIVE else SIX


class NNModel:
    MODEL_VER = LAYER_VERSION

    def __init__(self, cfg: TrainConfig | None = None, cache: bool = True, verbose: bool = False):
        self.cfg = cfg or TrainConfig()
        self.cache, self.verbose = cache, verbose
        self.fitted: Fitted | None = None
        self.state = None
        self.cutoff: str | None = None

    def fit(self, conn: sqlite3.Connection, league: str, cutoff_date: str) -> None:
        leagues = (league,) if self.cfg.pool == "league" else group_of(league)
        tables = [build_table(conn, lg, self.cache) for lg in leagues]
        table = pd.concat([t for t in tables if len(t)], ignore_index=True)
        self.fit_table(table, cutoff_date)
        self.state = state_at(conn, league, cutoff_date)

    def fit_table(self, table: pd.DataFrame, cutoff_date: str) -> None:
        """在已建好的样本表上训练（选参脚本用，省掉重复建表）。"""
        self.fitted = train(table, self.cfg, cutoff_date, verbose=self.verbose)
        self.cutoff = cutoff_date

    def predict_rows(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float]:
        """样本表里的行（特征已按各自 cutoff 算好）-> (λ主, λ客, rho)。"""
        if self.cfg.variant == "B" and df["mk_lam_h"].isna().any():
            raise ValueError("变体 B 需要赛前 1X2 赔率")
        return self.fitted.predict(df)

    def _row(self, home: str, away: str, odds: dict | None) -> pd.DataFrame:
        r = self.state.features(home, away, date.fromisoformat(self.cutoff))
        r |= market_features(odds or {})
        return pd.DataFrame([r])

    def score_matrix(self, home: str, away: str, odds: dict | None = None) -> np.ndarray:
        lh, la, rho = self.predict_rows(self._row(home, away, odds))
        return dc_matrix(float(lh[0]), float(la[0]), rho)

    def predict_1x2(self, home: str, away: str, odds: dict | None = None) -> dict:
        m = self.score_matrix(home, away, odds)
        return {"home_win": float(np.tril(m, -1).sum()), "draw": float(np.trace(m)),
                "away_win": float(np.triu(m, 1).sum()), "model_ver": LAYER_VERSION}
