"""
calibration/platt.py  v1.0.0
Platt scaling 概率校准层：用逻辑回归对三分类 DC 输出概率做温度校准。
原理：对每个类别 c，学习 w_c、b_c 使 sigmoid(w_c * logit(p_c) + b_c) → 更准的概率。
训练数据为 OOS 预测（DC fit 在前 N-1 赛季，校准集为第 N 赛季）。
修改此文件后请同步更新 version.py 中 "calibration" 的版本号。
"""
import numpy as np
import pandas as pd
import sqlite3
from datetime import date, timedelta

LAYER_VERSION = "1.0.0"

# 映射结果字符串 → 独热索引
_OUTCOME_IDX = {"home_win": 0, "draw": 1, "away_win": 2}


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class PlattCalibrator:
    """
    对三分类概率向量 [p_home, p_draw, p_away] 做 Platt scaling。

    用法：
        cal = PlattCalibrator()
        cal.fit(conn, league, dc_model_cls, calib_seasons=["2324"])
        p_cal = cal.calibrate(np.array([[0.55, 0.25, 0.20]]))
    """

    def __init__(self):
        # 每个类别独立的 [weight, bias]，初始为恒等变换
        self._params = np.array([[1.0, 0.0],
                                 [1.0, 0.0],
                                 [1.0, 0.0]], dtype=float)
        self.fitted = False

    # ------------------------------------------------------------------
    # 拟合
    # ------------------------------------------------------------------

    def fit(self, conn: sqlite3.Connection, league: str,
            dc_model_cls, calib_seasons: list,
            helper_seasons: list | None = None) -> None:
        """
        在 calib_seasons 上拟合校准参数。

        helper_seasons: 用于拟合辅助 DC 的赛季（若为 None，则从 calib_seasons
                        之前所有已有数据中取）。DC 不得见过 calib_seasons 数据。
        """
        if helper_seasons is None:
            # 取 calib_seasons 第一个赛季之前的所有赛季
            all_seasons = pd.read_sql_query(
                """SELECT DISTINCT season FROM matches
                   WHERE league = ? AND home_goals IS NOT NULL
                   ORDER BY season""",
                conn, params=[league],
            )["season"].tolist()
            helper_seasons = [s for s in all_seasons
                              if s < min(calib_seasons)]

        if not helper_seasons:
            raise ValueError("找不到早于校准赛季的历史数据来拟合辅助 DC")

        # 辅助 DC（不能见过校准赛季）
        raw_cutoff = pd.read_sql_query(
            f"""SELECT MAX(match_date) AS dt FROM matches
                WHERE league = ? AND season IN ({','.join('?'*len(helper_seasons))})
                  AND home_goals IS NOT NULL""",
            conn, params=[league] + helper_seasons,
        ).iloc[0]["dt"]
        helper_cutoff = (date.fromisoformat(raw_cutoff) + timedelta(days=1)).isoformat()

        dc = dc_model_cls()
        dc.fit(conn, league, helper_cutoff)
        print(f"  [校准] helper DC cutoff={helper_cutoff}，校准赛季={calib_seasons}")

        # 收集 DC 预测概率和真实标签
        df = pd.read_sql_query(
            f"""SELECT match_date, home_team, away_team, home_goals, away_goals
                FROM matches
                WHERE league = ? AND season IN ({','.join('?'*len(calib_seasons))})
                  AND home_goals IS NOT NULL
                ORDER BY match_date""",
            conn, params=[league] + calib_seasons,
        )

        P, Y = [], []
        for _, row in df.iterrows():
            try:
                probs = dc.predict_1x2(row["home_team"], row["away_team"])
            except Exception:
                continue
            hg, ag = int(row["home_goals"]), int(row["away_goals"])
            label = 0 if hg > ag else (1 if hg == ag else 2)
            P.append([probs["home_win"], probs["draw"], probs["away_win"]])
            Y.append(label)

        if len(P) < 30:
            print(f"  [校准] 样本太少（{len(P)} 场），跳过校准，使用恒等变换")
            return

        P = np.array(P, dtype=float)   # (N, 3)
        Y = np.array(Y, dtype=int)     # (N,)
        print(f"  [校准] 校准样本: {len(P)} 场", flush=True)

        # 对每个类别分别用梯度下降拟合 sigmoid(w * logit(p) + b)
        logit_P = _logit(P)   # (N, 3)
        for c in range(3):
            lp = logit_P[:, c]
            yc = (Y == c).astype(float)   # 二元标签
            w, b = self._fit_sigmoid_one(lp, yc)
            self._params[c] = [w, b]
            print(f"  [校准] 类别{c} w={w:.4f} b={b:.4f}")

        self.fitted = True

    def _fit_sigmoid_one(self, lp: np.ndarray, y: np.ndarray,
                         lr: float = 0.01, max_iter: int = 1000) -> tuple:
        """对单个类别用梯度下降拟合 Platt scaling 参数 (w, b)。"""
        w, b = 1.0, 0.0
        n = len(lp)
        for _ in range(max_iter):
            z = w * lp + b
            sig = 1.0 / (1.0 + np.exp(-z))
            err = sig - y
            dw = (err * lp).mean()
            db = err.mean()
            w -= lr * dw
            b -= lr * db
        return float(w), float(b)

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------

    def calibrate(self, P: np.ndarray) -> np.ndarray:
        """
        P: (N, 3) 原始概率矩阵（行为 [p_home, p_draw, p_away]）
        返回校准后的归一化概率矩阵，形状相同。
        未拟合时返回原始概率。
        """
        if not self.fitted:
            return P.copy()
        logit_P = _logit(P)
        calibrated = np.empty_like(P)
        for c in range(3):
            w, b = self._params[c]
            calibrated[:, c] = 1.0 / (1.0 + np.exp(-(w * logit_P[:, c] + b)))
        # 归一化为合法概率分布
        calibrated = np.clip(calibrated, 1e-6, 1.0)
        calibrated /= calibrated.sum(axis=1, keepdims=True)
        return calibrated

    def calibrate_dict(self, probs: dict) -> dict:
        """输入/输出均为 {'home_win':…, 'draw':…, 'away_win':…} 字典。"""
        P = np.array([[probs["home_win"], probs["draw"], probs["away_win"]]])
        cal = self.calibrate(P)[0]
        return {
            "home_win": round(float(cal[0]), 4),
            "draw":     round(float(cal[1]), 4),
            "away_win": round(float(cal[2]), 4),
        }
