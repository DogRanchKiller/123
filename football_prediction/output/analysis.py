"""
output/analysis.py  v1.4.0（输出层的一部分）
单场判断流程（预测报告与 explain 共用，纯函数，不读库）：
  1 赔率快照（最新一次）
  2 胜平负 = 市场去水概率（无赔率时回退 blend / dc_xg）
  3 比分分布 = 市场隐含（1X2 + 大小2.5 + 亚盘 反推 λ）；缺大小球盘时回退 dc_xg
  4 自研模型对照：与市场任一结果差 > 8pp 时提示（仅提示，历史上市场更准）
  5 盘口变动：首条 vs 最新快照，主胜变动 ≥ 5pp 或亚盘线变化视为新信息，按变动方向理解，不反向
  6 风险：升班马 / 历史数据少 / 缺赔率 / 盘口之间不一致
  7 结论：倾向、双选、信心档 + 历史命中率 + 本场命中估计
修改此文件后请同步更新 version.py 中 "output" 的版本号。
v1.3.0: 信心档按 Shin 去水的最大概率分档，命中率改用 research.db 5 联赛 1213–2425 重标定
        （_diag/explore/reliability.py）；新增本场命中估计 est1 / est2 = Shin 最大概率 / 前二之和。
        研究显示 Shin 概率在各分箱与实际命中差 ≤ 2.3pp，联赛、赛季初、升班马在 p_max 之外都不显著，
        所以可靠度直接用本场 Shin 概率，不另建修正模型。胜平负显示仍为按比例去水（主模型不变）。
v1.4.0: analyse 增加 last_row：定价赔率可来自多家中位数，盘口变动仍在赛程表快照之间比。
"""
import numpy as np

from football_prediction.model_market.devig import shin
from football_prediction.model_market.implied import implied_matrix, fair_probs
from football_prediction.output.derive import derive_markets, margin_pmf, ah_outcome, ah_fair_prob

LAYER_VERSION = "1.4.0"

DIVERGE_PP = 0.08      # 自研与市场分歧提示阈值
MOVE_PP = 0.05         # 盘口变动阈值（主胜概率）
FIT_RMSE_WARN = 0.02   # 市场隐含拟合误差提示阈值（回测中约 4% 的场次超过）

LABEL = {"home_win": "主胜", "draw": "平", "away_win": "客胜"}
_KEYS = ("home_win", "draw", "away_win")

# 信心档：(下限, 档名, 首选命中, 前二命中)；首选=概率最高一项，前二=最高两项之一。
# 市场档：赛前平均赔率 Shin 去水的最大概率；research.db 5 联赛 1213–2425 n=23488 标定
# （2526 留出：高 0.725/0.897，中 0.499/0.792，低 0.428/0.700）。各联赛同档首选命中相差 ≤ 4pp。
MARKET_TIERS = [
    (0.60, "高", 0.722, 0.892),
    (0.45, "中", 0.523, 0.790),
    (0.00, "低", 0.406, 0.712),
]
# 自研档（无赔率时用）：xG 版 DC 月度回测，2324–2526 共 3198 场。
MODEL_TIERS = [
    (0.60, "高", 0.73, 0.90),
    (0.45, "中", 0.52, 0.76),
    (0.00, "低", 0.41, 0.71),
]


def confidence_tier(p_max: float, tiers=MARKET_TIERS) -> tuple[str, float, float]:
    """按最大概率返回 (档名, 历史首选命中率, 历史前二命中率)。"""
    for lo, name, hit1, hit2 in tiers:
        if p_max >= lo:
            return name, hit1, hit2
    raise ValueError(p_max)


def double_label(top2: list[str]) -> str:
    s = set(top2)
    if s == {"home_win", "away_win"}:
        return "不平局"
    return "或".join(LABEL[k] for k in _KEYS if k in s)


def devig(*odds) -> list[float] | None:
    """欧赔按比例去水；任一缺失或 ≤1 返回 None。"""
    if not odds or any(o is None or o != o or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    return [x / sum(inv) for x in inv]


def odds_dict(row: dict | None) -> dict:
    """fixtures / odds_snapshots 列名 -> model_market 的 odds 键。"""
    row = row or {}
    m = {"h": "avg_h", "d": "avg_d", "a": "avg_a", "over": "avg_over25", "under": "avg_under25",
         "ah_line": "ah_line", "ah_h": "avg_ahh", "ah_a": "avg_aha"}
    return {k: row.get(c) for k, c in m.items() if row.get(c) is not None}


def matrix_1x2(m: np.ndarray) -> tuple[float, float, float]:
    """比分矩阵（行=主队进球）-> (主胜, 平, 客胜)"""
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def movement(first: dict | None, last: dict | None) -> str:
    """首条 vs 最新快照的盘口变动说明；不足两条快照返回空串。"""
    if not first or not last:
        return ""
    parts, score = [], 0
    p0 = devig(first.get("avg_h"), first.get("avg_d"), first.get("avg_a"))
    p1 = devig(last.get("avg_h"), last.get("avg_d"), last.get("avg_a"))
    if p0 and p1 and abs(p1[0] - p0[0]) >= MOVE_PP:
        parts.append(f"主胜 {p0[0]:.0%}→{p1[0]:.0%}")
        score += 1 if p1[0] > p0[0] else -1
    l0, l1 = first.get("ah_line"), last.get("ah_line")
    if l0 is not None and l1 is not None and l0 != l1:
        parts.append(f"亚盘 主{l0:+.2f}→{l1:+.2f}")
        score += 1 if l1 < l0 else -1          # 主队让得更多 = 偏向主队
    if not parts:
        return "平稳"
    side = "偏向主队" if score > 0 else "偏向客队" if score < 0 else "方向不一致"
    return "；".join(parts) + f" → {side}（新信息，已含在最新赔率里，不反向理解）"


def analyse(odds_row: dict | None, xg_matrix: np.ndarray, rho: float,
            models: dict[str, tuple] | None = None, first_row: dict | None = None,
            risks: list[str] | tuple = (), last_row: dict | None = None) -> dict:
    """
    单场判断。odds_row：定价用的最新赔率（fixtures 列名，可为多家中位数）；
    first_row/last_row：同一来源的首条/最新快照，算盘口变动（last_row 缺省为 odds_row）；
    xg_matrix、rho：dc_xg 比分矩阵与联赛 rho；models：自研 1X2 {名称: (主,平,客)}；
    risks：调用方已知的风险（升班马、数据少）。
    """
    models, risks, hints = dict(models or {}), list(risks), []
    od = odds_dict(odds_row)
    mkt = devig(od.get("h"), od.get("d"), od.get("a"))
    matrix, source, fit = xg_matrix, "dc_xg", None
    if mkt is None:
        risks.append("缺胜平负赔率：概率来自自研模型，可靠性低于市场")
        source = "dc_xg（无赔率）"
    elif devig(od.get("over"), od.get("under")) is None:
        risks.append("缺大小球盘：比分/大小球用 dc_xg")
        source = "dc_xg（缺大小球盘）"
    else:
        matrix, fit = implied_matrix(od, rho)
        source = "市场隐含"
        if fit["rmse"] > FIT_RMSE_WARN:
            risks.append(f"各盘口之间不完全一致（拟合误差 {fit['rmse']:.3f}）")

    mk = derive_markets(matrix)
    if mkt is not None:
        p, p_src, tiers = tuple(mkt), "市场", MARKET_TIERS
    elif "blend" in models:
        p, p_src, tiers = tuple(models["blend"]), "blend", MODEL_TIERS
    else:
        p, p_src, tiers = matrix_1x2(matrix), "dc_xg", MODEL_TIERS

    if mkt is not None:
        for name, q in models.items():
            d = [q[i] - mkt[i] for i in range(3)]
            i = int(np.argmax(np.abs(d)))
            if abs(d[i]) > DIVERGE_PP:
                hints.append(f"{name} 与市场分歧：{LABEL[_KEYS[i]]} {d[i]*100:+.0f}pp"
                             "（仅提示，历史上市场更准）")

    ah = None
    line = od.get("ah_line")
    if line is not None:
        out = ah_outcome(margin_pmf(matrix), line)
        mkt_ah = fair_probs(od).get("ah")
        ah = {"line": line, "outcome": out, "fair": ah_fair_prob(out),
              "market_fair": mkt_ah[1] if mkt_ah else None}

    probs = dict(zip(_KEYS, p))
    order = sorted(probs, key=probs.get, reverse=True)
    est1 = est2 = None
    if mkt is not None:
        # 本场命中估计：Shin 概率（与按比例去水同序，倾向 / 双选不变）；市场档也按它分档
        ps = sorted(shin([od["h"], od["d"], od["a"]]), reverse=True)
        est1, est2 = float(ps[0]), float(ps[0] + ps[1])
        tier, hit1, hit2 = confidence_tier(est1, tiers)
    else:
        tier, hit1, hit2 = confidence_tier(probs[order[0]], tiers)
    return {
        "p1x2": p, "p_src": p_src, "market": mkt, "source": source, "fit": fit,
        "markets": mk, "ah": ah, "models": models, "hints": hints,
        "move": movement(first_row, last_row or odds_row) if first_row else "",
        "risks": risks, "lean": LABEL[order[0]], "double": double_label(order[:2]),
        "tier": tier, "hit1": hit1, "hit2": hit2, "est1": est1, "est2": est2,
    }
