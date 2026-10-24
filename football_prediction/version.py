# version.py — 各层版本号注册表
# 修改某一层时只更新对应条目，review 层用版本号区分不同批次预测

SYSTEM_VERSION = "1.1.0"

LAYER_VERSIONS = {
    "data":          "1.3.0",   # + understat xG match_xg（v1.2.0: 射门/射正；v1.1.0: 赔率、赛程）
    "features":      "1.0.0",
    "model_elo":     "1.0.0",
    "model_dc":      "1.3.0",   # + 单队参数收缩 shrink=0.5（修复升级队参数发散）
    "model_sot":     "1.0.0",   # 射正版 DC：进球与射正混合估计攻防（w=0.7，回测优于 DC）
    "model_xg":      "1.0.0",   # xG 版 DC：进球与 xG 混合估计攻防（w=0.3，回测优于 DC）
    "model_lgbm":    "1.1.0",   # 滚动 OOS，训练样本翻倍；修复重名方法 bug
    "calibration":   "1.0.0",   # Platt scaling；2425 验证无增益（±0.005），不进主流程
    "output":        "1.0.0",
    "validation":    "1.1.0",   # + 市场基准 run_market_backtest、同场配对 paired_compare
    "review":        "1.1.0",   # + has_prediction 去重、live_report 实盘成绩单
    "live":          "1.2.0",   # 实盘循环：开赛前预测、首条为准、对比市场；射正版 + xG 版 DC
}


def get(layer: str) -> str:
    """获取某层的当前版本号"""
    return LAYER_VERSIONS[layer]
