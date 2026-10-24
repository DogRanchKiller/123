# version.py — 各层版本号注册表
# 修改某一层时只更新对应条目，review 层用版本号区分不同批次预测

SYSTEM_VERSION = "1.4.0"

LAYER_VERSIONS = {
    "data":          "1.5.0",   # + 多家公司赔率 book_odds（OddsPortal 爬虫）（v1.4.0: 亚盘/Pinnacle/赛程大小球、快照表；v1.3.0: xG；v1.2.0: 射正；v1.1.0: 赔率、赛程）
    "features":      "1.0.0",
    "model_elo":     "1.1.0",   # 净胜球加权更新 + 有序 logit（v1.0.0 融合无增益）
    "model_dc":      "1.3.0",   # + 单队参数收缩 shrink=0.5（修复升级队参数发散）
    "model_sot":     "1.0.0",   # 射正版 DC：进球与射正混合估计攻防（w=0.7，回测优于 DC）
    "model_xg":      "1.0.0",   # xG 版 DC：进球与 xG 混合估计攻防（w=0.3，回测优于 DC）
    "model_market":  "1.0.0",   # 市场隐含比分：由 1X2+大小2.5+亚盘 反推 λ，回测全面优于 dc_xg
    "model_blend":   "1.0.0",   # dc_xg 0.77 + Elo 0.23 的 1X2 融合（确认期 −0.0046±0.0013）
    "model_lgbm":    "1.1.0",   # 滚动 OOS，训练样本翻倍；修复重名方法 bug
    "calibration":   "1.0.0",   # Platt scaling；2425 验证无增益（±0.005），不进主流程
    "output":        "1.2.0",   # 按判断流程重做报告 + explain 单场说明；亚盘五种结算；信心档按市场重标定
    "validation":    "1.1.0",   # + 市场基准 run_market_backtest、同场配对 paired_compare
    "review":        "1.3.0",   # + 大小2.5 / 精确比分 log loss（存比分矩阵的模型）
    "live":          "1.4.0",   # 判断流程：快照 → 市场隐含 → 自研对照 → 变动/风险 → 结论；新增 market_implied / blend 存档
}


# 主预测模型：预测报告以它为准；其余模型并行存档作对照。
# 2026-10-24 v1.4.0 起改为市场隐含模型（用户确定的"以市场为底"策略 + 回测门槛）：
#   2324–2627 三联赛赛前赔率 n=3411，相对 dc_xg：1X2 −0.0163±0.0025、大小2.5 −0.0080±0.0021、
#   精确比分 −0.0213±0.0038、亚盘 −0.0138±0.0029，各赛季同向（_diag/explore/implied_eval.py）。
#   无赔率的场次由报告回退到 dc_xg。此前主模型为 dc_xg（model_xg）。
PRIMARY_MODEL = ("market_implied", "model_market")   # (predictions.model_name, LAYER_VERSIONS 键)
FALLBACK_MODEL = ("dc_xg", "model_xg")                # 无赔率时的比分来源

# 主模型替换规则（事先约定，防止事后挑选）：
#   挑战者与主模型在【同一批实盘已评分比赛】上配对，
#   场数 ≥ PROMOTE_MIN_N 且 (差值 + 2×SE) < 0（即显著更好）才替换。
#   1000 场约为三联赛一个赛季；按回测配对差值的标准差（约 0.09/场），
#   此时 2×SE ≈ 0.0055，约可检出 0.006 以上的稳定提升（回测中 xG 版比 DC 好约 0.008）。
PROMOTE_MIN_N = 1000


def get(layer: str) -> str:
    """获取某层的当前版本号"""
    return LAYER_VERSIONS[layer]
