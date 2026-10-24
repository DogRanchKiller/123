# version.py — 各层版本号注册表
# 修改某一层时只更新对应条目，review 层用版本号区分不同批次预测

SYSTEM_VERSION = "1.3.0"

LAYER_VERSIONS = {
    "data":          "1.3.0",   # + understat xG match_xg（v1.2.0: 射门/射正；v1.1.0: 赔率、赛程）
    "features":      "1.0.0",
    "model_elo":     "1.0.0",
    "model_dc":      "1.3.0",   # + 单队参数收缩 shrink=0.5（修复升级队参数发散）
    "model_sot":     "1.0.0",   # 射正版 DC：进球与射正混合估计攻防（w=0.7，回测优于 DC）
    "model_xg":      "1.0.0",   # xG 版 DC：进球与 xG 混合估计攻防（w=0.3，回测优于 DC）
    "model_lgbm":    "1.1.0",   # 滚动 OOS，训练样本翻倍；修复重名方法 bug
    "calibration":   "1.0.0",   # Platt scaling；2425 验证无增益（±0.005），不进主流程
    "output":        "1.1.0",   # + 预测报告 report.py：主模型概率、信心档、比分、大小球
    "validation":    "1.1.0",   # + 市场基准 run_market_backtest、同场配对 paired_compare
    "review":        "1.2.0",   # + 成绩单加命中率与 SE、主模型替换检查 promotion_check
    "live":          "1.3.0",   # 实盘循环：开赛前预测、首条为准、对比市场；输出主模型预测报告
}


# 主预测模型：预测报告只展示它；其余模型并行存档作参考。
# 2026-10-24 按回测选定（2324–2526 三联赛 log loss 最低的自研模型）。
PRIMARY_MODEL = ("dc_xg", "model_xg")   # (predictions.model_name, LAYER_VERSIONS 键)

# 主模型替换规则（事先约定，防止事后挑选）：
#   挑战者与主模型在【同一批实盘已评分比赛】上配对，
#   场数 ≥ PROMOTE_MIN_N 且 (差值 + 2×SE) < 0（即显著更好）才替换。
#   1000 场约为三联赛一个赛季；按回测配对差值的标准差（约 0.09/场），
#   此时 2×SE ≈ 0.0055，约可检出 0.006 以上的稳定提升（回测中 xG 版比 DC 好约 0.008）。
PROMOTE_MIN_N = 1000


def get(layer: str) -> str:
    """获取某层的当前版本号"""
    return LAYER_VERSIONS[layer]
