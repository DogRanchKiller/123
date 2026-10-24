---
name: numpy-analysis
description: >
  用 NumPy 分析指标、矩阵、分布和回测数值。Use when the user asks to analyze
  results, metrics, score matrices, distributions, log loss, or Brier, or
  mentions NumPy / numpy。先读 docs/ml-stack.md 的「分析」。
---

# NumPy 分析

1. 读 `docs/ml-stack.md` 的「分析」和「预测契约」。完成标准：已经确定指标该调用哪一个现有函数。
2. 在 NumPy 数组上计算。足球概率用 `football_prediction/validation/backtest.py` 的 `_log_loss_one`、`_brier_one`、`paired_compare`；比分矩阵用 `football_prediction/output/derive.py` 的 `derive_markets`。完成标准：报出的每个指标都能指回这些函数之一，张量已转成 NumPy 再计算。
3. 新测试放在 `tests/`，数据用内存 SQLite 或合成数组。完成标准：`.venv/bin/python -m pytest tests` 通过，且测试不联网。
