"""
model_market/devig.py  v1.0.0
去水方法：赔率 → 概率（和为 1）。
  proportional：1/赔率 按比例归一（market_avg 基准与 market_implied 用这个，不要改）。
  shin：Shin (1993) 内幕交易者模型，解 z 使 Σp=1。热门的概率比按比例去水高、冷门低，
        修正"热门-冷门偏差"。research.db 5 联赛 21.6k 场 1X2 相对比例去水 −0.00042±0.00014。
  与 mberk/shin（MIT）在 [2.6, 2.4, 4.3] 上结果一致（见 tests/test_devig.py）。
修改此文件后请同步更新 version.py 中 "model_market_shin" 的版本号。
"""
import numpy as np
from scipy.optimize import brentq

LAYER_VERSION = "1.0.0"
METHODS = ("proportional", "shin")
SHIN_NAME = "market_shin"   # implied_matrix(..., method="shin") 的存档名，版本键 model_market_shin


def proportional(odds) -> np.ndarray:
    q = 1.0 / np.asarray(odds, dtype=float)
    return q / q.sum()


def _shin_p(q: np.ndarray, z: float) -> np.ndarray:
    s = q.sum()
    return (np.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))


def shin(odds) -> np.ndarray:
    """Shin 去水；无抽水（Σ1/o ≤ 1）或求解失败时退回按比例。"""
    q = 1.0 / np.asarray(odds, dtype=float)
    if q.sum() <= 1.0 + 1e-12:
        return q / q.sum()
    try:
        z = brentq(lambda z: _shin_p(q, z).sum() - 1.0, 0.0, 0.5, xtol=1e-12)
    except ValueError:
        return q / q.sum()
    p = _shin_p(q, z)
    return p / p.sum()


def devig(odds, method: str = "proportional") -> np.ndarray:
    if method == "proportional":
        return proportional(odds)
    if method == "shin":
        return shin(odds)
    raise ValueError(f"未知去水方法 {method}，可选 {METHODS}")
