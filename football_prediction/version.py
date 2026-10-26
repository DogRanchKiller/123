# version.py — 各层版本号注册表
# 修改某一层时只更新对应条目，review 层用版本号区分不同批次预测

SYSTEM_VERSION = "1.12.0"

LAYER_VERSIONS = {
    "data":          "1.9.0",   # 入库前剔除隐含概率之和 < 1 的赔率组（亚盘连线一起），旧行不改（1.8.0: book_odds.fetched_at 记每组抓回时刻，抓回时已开球的不入库（1.7.0:+ E1/N1/P1/SC0/B1/T1 实盘（2122–2627）与 OddsPortal 队名、understat US_LEAGUES（v1.6.0: 意甲 I1 / 法甲 F1 实盘（2122–2627）与 OddsPortal / FotMob 队名（v1.5.0: 多家公司赔率 book_odds；v1.4.0: 亚盘/Pinnacle/赛程大小球、快照表；v1.3.0: xG；v1.2.0: 射正；v1.1.0: 赔率、赛程））））
    "data_fotmob":   "1.2.0",   # + 六个新联赛的 FotMob 联赛 id 与队名（1.1.0：联赛页完赛比分 fotmob_results（只用于先评分）（1.0.0：FotMob 阵容 / 伤停 / 球员 xG / 射门（HTML 页，不用 /api/）；understat 缺时补 match_xg））
    "features":      "1.0.0",
    "model_elo":     "1.1.0",   # 净胜球加权更新 + 有序 logit（v1.0.0 融合无增益）
    "model_dc":      "1.3.0",   # + 单队参数收缩 shrink=0.5（修复升级队参数发散）
    "model_sot":     "1.0.0",   # 射正版 DC：进球与射正混合估计攻防（w=0.7，回测优于 DC）
    "model_xg":      "1.0.0",   # xG 版 DC：进球与 xG 混合估计攻防（w=0.3，回测优于 DC）
    "model_dc_market": "1.0.0", # 市场版 DC：进球与历史赔率 λ 混合（w=0.3；2526 留出对 dc_xg −0.0059±0.0022）
    "model_market":  "1.0.0",   # 市场隐含比分：由 1X2+大小2.5+亚盘 反推 λ，回测全面优于 dc_xg
    "model_market_shin": "1.0.0",   # 同上，去水改 Shin（1X2 n=21588：−0.0004±0.0001）；并行存档 market_shin
    "model_lineup":  "1.1.0",   # 合并规则：系数分 COEF_PRE / COEF_POST，按赔率与首发先后选用（仍为 0）（1.0.0：阵容调整乘到市场 λ 上，只用于 lineup_t1）
    "model_blend":   "1.0.0",  # dc_xg 0.77 + Elo 0.23 的 1X2 融合（确认期 −0.0046±0.0013）
    "model_lgbm":    "1.1.0",   # 滚动 OOS，训练样本翻倍；修复重名方法 bug
    "calibration":   "1.0.0",   # Platt scaling；2425 验证无增益（±0.005），不进主流程
    "output":        "1.7.0",   # 自研兜底与亚盘同线对照改为 dc_market，无赔率胜平负不再用 blend，MODEL_TIERS 按 dc_market 重标定（1.6.0：每场结论 + 把握：亚盘稳妥线（赢盘 ≥ 65% 的最近一条线）、重点标记（胜平负市场档高）、亚盘中档标签 0.60（1.5.0：亚盘为主：报告 / explain 先列市场线亚盘（数字盘口、五种结算、赢盘信心档、盘口与水位变动、dc_xg 同线分歧），AH_LINES 扩到 ±4（1.4.0：报告 / explain 优先用多家中位数赔率（≥3 家、24h 内），列赔率来源（1.3.0：Shin 信心档 + 本场估计；1.2.0：判断流程 + explain）））
    "validation":    "1.1.0",   # + 市场基准 run_market_backtest、同场配对 paired_compare
    "review":        "1.8.0",   # 临场档分 _t1 / _t2：亚盘参照线按档分组，_t2 不进替换检查，horizon_report 对赛前档与 _t1 配对（1.7.0：开球后不存档（save_prediction 收生成时刻 at），成绩单不计开球后才存的旧行（1.6.0: 亚盘评分：按存档时的市场亚盘线算五种结算 log loss 与赢盘命中（ah_line / ah_log_loss / ah_hit，旧行回填）；成绩单拆到 scorecard.py（1.5.0：football-data 未到时用 FotMob 比分先评分（result_src），到达后核对重评（1.4.0：临场档 _t1 不参与替换检查；horizon_report 临场对赛前））））
    "live":          "1.12.0",  # 无赔率兜底改 dc_market；--near 加第二临场档 *_t2（开球前 0.6 小时内）（v1.11.0: 快照加亚盘稳妥线，页面重点改为胜平负高档（v1.10.1: 一轮的时钟 round_clock：存档前再取时刻，已开球的不存（v1.10.0: 成绩单加亚盘列（v1.9.0: + 英冠 / 荷甲 / 葡超 / 苏超 / 比甲 / 土超，understat 没有的联赛跳过 load_xg（v1.8.0: 抓 FotMob 完赛比分并先评分、核对 football-data（v1.7.0: 临场档先抓阵容再抓赔率，按先后选阵容系数，打印临场最终看法；v1.6.0: + 意甲 I1 / 法甲 F1；v1.5.0: market_shin / dc_market 存档、FotMob 补 xG、--near 临场档 *_t1））））））
}


# 主预测模型：预测报告以它为准；其余模型并行存档作对照。
# 2026-10-24 v1.4.0 起改为市场隐含模型（用户确定的"以市场为底"策略 + 回测门槛）：
#   2324–2627 三联赛赛前赔率 n=3411，相对 dc_xg：1X2 −0.0163±0.0025、大小2.5 −0.0080±0.0021、
#   精确比分 −0.0213±0.0038、亚盘 −0.0138±0.0029，各赛季同向（_diag/explore/implied_eval.py）。
#   无赔率的场次由报告回退到兜底模型。此前主模型为 dc_xg（model_xg）。
PRIMARY_MODEL = ("market_implied", "model_market")   # (predictions.model_name, LAYER_VERSIONS 键)
# 兜底：2026-10-26 v1.12.0 起 dc_market（此前 dc_xg）。11 联赛 2324–2627 月度回测 n=12224：
#   对 dc_xg −0.0092±0.0011、对 blend（此前无赔率时的胜平负）−0.0060±0.0010，四个赛季都显著
#   （_diag/fallback/result.txt）。dc_market 自 v1.5.0 起每场并行存档。
FALLBACK_MODEL = ("dc_market", "model_dc_market")    # 无赔率时的比分与胜平负来源

# 主模型替换规则（事先约定，防止事后挑选）：
#   挑战者与主模型在【同一批实盘已评分比赛】上配对，
#   场数 ≥ PROMOTE_MIN_N 且 (差值 + 2×SE) < 0（即显著更好）才替换。
#   1000 场约为三联赛一个赛季；按回测配对差值的标准差（约 0.09/场），
#   此时 2×SE ≈ 0.0055，约可检出 0.006 以上的稳定提升（回测中 xG 版比 DC 好约 0.008）。
PROMOTE_MIN_N = 1000


def get(layer: str) -> str:
    """获取某层的当前版本号"""
    return LAYER_VERSIONS[layer]
