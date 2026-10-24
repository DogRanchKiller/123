"""验证层 — 按时间切分回测，计算 Log Loss / Brier Score"""
from .backtest import run_backtest

__all__ = ["run_backtest"]
