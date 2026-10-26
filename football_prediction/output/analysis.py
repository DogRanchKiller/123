"""
output/analysis.py  v1.7.0（输出层的一部分）
单场判断流程（预测报告与 explain 共用，纯函数，不读库）：
  1 赔率快照（最新一次）
  2 胜平负 = 市场去水概率（无赔率时回退 dc_market）
  3 比分分布 = 市场隐含（1X2 + 大小2.5 + 亚盘 反推 λ）；缺大小球盘时回退 dc_market
  4 自研模型对照：与市场任一结果差 > 8pp 时提示（仅提示，历史上市场更准）
  5 盘口变动：首条 vs 最新快照，主胜变动 ≥ 5pp 或亚盘线变化视为新信息，按变动方向理解，不反向
  6 风险：升班马 / 历史数据少 / 缺赔率 / 盘口之间不一致
  7 结论：倾向、双选、信心档 + 历史命中率 + 本场命中估计；亚盘稳妥线；重点标记
修改此文件后请同步更新 version.py 中 "output" 的版本号。
v1.3.0: 信心档按 Shin 去水的最大概率分档，命中率改用 research.db 5 联赛 1213–2425 重标定
        （_diag/explore/reliability.py）；新增本场命中估计 est1 / est2 = Shin 最大概率 / 前二之和。
        研究显示 Shin 概率在各分箱与实际命中差 ≤ 2.3pp，联赛、赛季初、升班马在 p_max 之外都不显著，
        所以可靠度直接用本场 Shin 概率，不另建修正模型。胜平负显示仍为按比例去水（主模型不变）。
v1.4.0: analyse 增加 last_row：定价赔率可来自多家中位数，盘口变动仍在赛程表快照之间比。
v1.5.0: 亚盘为主。ah 块改为：市场线（缺时用比分矩阵的公平线）上的五种结算、等效赢盘概率、
        选择方（赢盘概率较高的一方）与亚盘信心档 AH_TIERS（research.db 标定，_diag/explore/ah_baseline.py）；
        同线自研 dc_xg 与市场分歧 > AH_DIVERGE_PP 时提示；亚盘线与水位轨迹 ah_trail（初盘 → 最新快照 → 定价，
        升盘 / 降盘按让球方让得更多 / 更少）。ah_text / ah_pick_text 给报告与 explain 共用的数字写法。
v1.6.0: 每场一个结论 + 把握程度。亚盘块加「稳妥线」safe_line / safe_cover：从选择方的线每次退 0.25，
        直到等效赢盘概率 ≥ SAFE_TARGET（0.65）。research.db 研究（_diag/explore/ah_confidence_line.py）：
        市场线以外各线的赢盘概率校准（标定 1213–2425 各分箱差 ≤ 1.4pp，2526 留出 ≤ 3pp），按此找线
        标定命中 0.682、留出 0.674。新增重点标记 highlight：胜平负市场档为「高」（Shin 最大概率 ≥ 0.60，
        标定 0.722 / 留出 0.725，约 27% 的场次）。不再用亚盘信心档做重点：亚盘高档 2526 留出未确认。
        剔除亚盘坏行复核后：稳妥线留出 0.677、重点留出 0.728；亚盘中档标签 0.562 → 0.60（近年 11 联赛）。
        重点场次在市场线上的亚盘选择方命中只有 0.52–0.55，与全体相当：重点只表示胜平负把握高。
v1.7.0: 自研兜底改为 dc_market（SELF_NAME，与 version.FALLBACK_MODEL 一致）：缺赔率 / 缺大小球盘时
        比分矩阵用它，缺胜平负赔率时胜平负也直接用它（不再用 blend）；亚盘同线对照也换成它。
        11 联赛 2324–2627 月度回测 n=12224（_diag/fallback/result.txt）：对 dc_xg −0.0092±0.0011、
        对 blend −0.0060±0.0010，四个赛季都显著；再融合 Elo 无增益（−0.0004±0.0003）。
        MODEL_TIERS 按 dc_market 在 2324–2526 重标定，2627 留出同向（_diag/fallback/tiers.txt）。
"""
import numpy as np

from football_prediction.model_market.devig import shin
from football_prediction.model_market.implied import implied_matrix, fair_probs
from football_prediction.output.derive import derive_markets, margin_pmf, ah_outcome, ah_fair_prob

LAYER_VERSION = "1.7.0"

SELF_NAME = "dc_market"  # 自研兜底与对照模型（= version.FALLBACK_MODEL 的名字）
DIVERGE_PP = 0.08      # 自研与市场分歧提示阈值
SAFE_TARGET = 0.65     # 稳妥线：选择方等效赢盘概率达到这个值的最近一条线
SAFE_MAX_STEPS = 12    # 稳妥线最多退 3 球（研究里 T=0.65 最多退 4 步）
AH_DIVERGE_PP = 0.08   # 同一亚盘线上自研兜底与市场赢盘概率的分歧提示阈值
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
# 自研档（无赔率时用）：dc_market 月度回测，11 联赛 2324–2526 n=11395 标定
# （2627 留出 n=829：高 0.753/0.929，中 0.540/0.804，低 0.378/0.711）。
MODEL_TIERS = [
    (0.60, "高", 0.74, 0.90),
    (0.45, "中", 0.52, 0.78),
    (0.00, "低", 0.40, 0.71),
]
# 亚盘信心档：(赢盘概率下限, 档名, 历史选择方命中率（不含走盘）)；赢盘概率 = 市场隐含比分在市场线上的
# 等效赢盘概率，取较高一方。隐含赢盘与该线去水水位平均只差 0.003，分档实际看的是水位偏离五五开的程度
# （_diag/explore/ah_baseline.log）。下限不变；命中标签按剔除坏行（两边水位隐含概率和 < 1）后的复核
# （_diag/explore/ah_clean_recheck.log）：
#   高：research.db 5 联赛 1213–2425 n=1409 命中 0.608，取 0.607 不变；近年几乎不出现（football.db
#       11 联赛 2122–2627 只有 7 场），原 2526 留出的 0.457（n=35）里 34 场是坏行。
#   中：football.db 11 联赛 2122–2425 n=601 命中 0.599 → 0.60；2526–2627 留出 0.586（n=174）。
#       原 0.562 是 research.db 1213–2425 的值。
#   低：research.db 1213–2425 0.517 不变（football.db 2122–2425 0.526，2526–2627 留出 0.508）。
AH_TIERS = [
    (0.56, "高", 0.607),
    (0.54, "中", 0.60),
    (0.00, "低", 0.517),
]


def ah_tier(p_cover: float) -> tuple[str, float]:
    """按选择方赢盘概率返回 (档名, 历史命中率)。"""
    for lo, name, hit in AH_TIERS:
        if p_cover >= lo:
            return name, hit
    raise ValueError(p_cover)


def ah_text(line: float, o: dict) -> str:
    """主队方向的数字写法：主-0.75 赢盘54%（赢36%、赢半18%），输46%；有走盘时写「走x%」。"""
    def part(word, short, full, half):
        tot = o[full] + o[half]
        if o[half] <= 0.005:
            return f"{word}{tot:.0%}"
        if o[full] <= 0.005:
            return f"{word}{tot:.0%}（{short}半）"
        return f"{word}{tot:.0%}（{short}{o[full]:.0%}、{short}半{o[half]:.0%}）"
    s = f"主{line + 0.0:+.2f} " + part("赢盘", "赢", "win", "half_win")
    if o["push"] > 0.005:
        s += f"，走{o['push']:.0%}"
    return s + "，" + part("输", "输", "lose", "half_lose")


def ah_pick_text(ah: dict) -> str:
    """选择方与等效赢盘概率：主-0.75 52% / 客+0.75 55%。"""
    line = ah["line"] if ah["side"] == "主" else -ah["line"]
    return f"{ah['side']}{line + 0.0:+.2f} {ah['p_cover']:.0%}"


def safe_line(home_fair, line: float, side: str, target: float = SAFE_TARGET) -> tuple[float, float] | None:
    """稳妥线：从 line（主队方向）起，每次向选择方退 0.25，返回第一条选择方等效赢盘概率 ≥ target 的
    (线, 概率)。home_fair(line) 给主队在该线的等效赢盘概率，返回 None 表示没有该线的数据；
    退 SAFE_MAX_STEPS 步仍不到或缺线时返回 None。"""
    step = 0.25 if side == "主" else -0.25
    for k in range(SAFE_MAX_STEPS + 1):
        x = round(line + k * step, 2)
        f = home_fair(x)
        if f is None:
            return None
        p = f if side == "主" else 1 - f
        if p >= target:
            return x + 0.0, p
    return None


def safe_text(ah: dict) -> str:
    """稳妥线写法：「客+1.25 66%」；没有时为空串。"""
    if ah.get("safe_line") is None:
        return ""
    return ah_pick_text({"line": ah["safe_line"], "side": ah["side"], "p_cover": ah["safe_cover"]})


def _ah_stage(row: dict | None) -> tuple | None:
    if not row or row.get("ah_line") is None:
        return None
    return float(row["ah_line"]), row.get("avg_ahh"), row.get("avg_aha")


def _shift(l0: float, l1: float) -> str:
    """升盘 / 降盘：按让球方让得更多 / 更少；让球方换边时写换边。"""
    if l0 == l1:
        return ""
    if l0 * l1 < 0:
        return f"让球方换边（{'主' if l1 < 0 else '客'}队让）"
    giver = "主" if (l0 or l1) < 0 else "客"
    return f"{'升盘' if abs(l1) > abs(l0) else '降盘'}（{giver}队让{'更多' if abs(l1) > abs(l0) else '更少'}）"


def ah_trail(open_row: dict | None, last_row: dict | None, price_row: dict | None) -> str:
    """亚盘线与主 / 客水位：初盘 → 最新快照 → 定价（相同的相邻阶段合并）；升盘 / 降盘看初盘到定价。
    定价可能来自多家中位数，水位与 football-data 平均不是同一批公司，只作参考。"""
    stages = []
    for name, row in (("初盘", open_row), ("最新快照", last_row), ("定价", price_row)):
        st = _ah_stage(row)
        if st is not None and (not stages or stages[-1][1] != st):
            stages.append((name, st))
    if len(stages) < 2:
        return ""
    w = lambda x: "-" if x is None else f"{x:.2f}"
    s = " → ".join(f"{n} 主{l + 0.0:+.2f}（{w(h)}/{w(a)}）" for n, (l, h, a) in stages)
    sh = _shift(stages[0][1][0], stages[-1][1][0])
    return s + (f"；{sh}" if sh else "；盘口未变，只有水位变化")


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


def asian(matrix: np.ndarray, od: dict, self_matrix: np.ndarray, priced: bool) -> tuple[dict, list[str]]:
    """亚盘块与提示。有市场线用市场线，否则用比分矩阵的公平线（赢盘约五五开，不分档）。
    self_matrix：自研兜底（SELF_NAME）的比分矩阵；priced：比分矩阵来自市场（市场隐含）时才和自研比分歧。"""
    pmf, hints = margin_pmf(matrix), []
    line, src = od.get("ah_line"), "市场线"
    if line is None:
        line, src = derive_markets(matrix)["ah_fair_line"], "公平线（无市场亚盘）"
    line = float(line)
    out = ah_outcome(pmf, line)
    fair = ah_fair_prob(out)
    side, p_cover = ("主", fair) if fair >= 0.5 else ("客", 1 - fair)
    tier, hit = ah_tier(p_cover) if src == "市场线" else ("-", None)
    mkt_ah = fair_probs(od).get("ah")
    self_fair = ah_fair_prob(ah_outcome(margin_pmf(self_matrix), line))
    if priced and abs(self_fair - fair) > AH_DIVERGE_PP:
        hints.append(f"{SELF_NAME} 在主{line + 0.0:+.2f} 的主队赢盘 {self_fair:.0%}，市场 {fair:.0%}，"
                     f"差 {(self_fair - fair) * 100:+.0f}pp（仅提示，历史上市场更准）")
    safe = safe_line(lambda x: ah_fair_prob(ah_outcome(pmf, x)), line, side)
    return {"line": line, "line_src": src, "outcome": out, "fair": fair, "side": side,
            "safe_line": safe[0] if safe else None, "safe_cover": safe[1] if safe else None,
            "p_cover": p_cover, "tier": tier, "hit": hit, "self_fair": self_fair,
            "market_fair": mkt_ah[1] if mkt_ah else None}, hints


def analyse(odds_row: dict | None, self_matrix: np.ndarray, rho: float,
            models: dict[str, tuple] | None = None, first_row: dict | None = None,
            risks: list[str] | tuple = (), last_row: dict | None = None,
            ah_open: dict | None = None) -> dict:
    """
    单场判断。odds_row：定价用的最新赔率（fixtures 列名，可为多家中位数）；
    first_row/last_row：同一来源的首条/最新快照，算盘口变动（last_row 缺省为 odds_row）；
    ah_open：亚盘初盘（赛程表首条快照，只有一条快照时也有；缺省为 first_row）；
    self_matrix：自研兜底 SELF_NAME 的比分矩阵；rho：联赛 rho（市场隐含用）；
    models：自研 1X2 {名称: (主,平,客)}，只作分歧提示；risks：调用方已知的风险（升班马、数据少）。
    """
    models, risks, hints = dict(models or {}), list(risks), []
    od = odds_dict(odds_row)
    mkt = devig(od.get("h"), od.get("d"), od.get("a"))
    matrix, source, fit = self_matrix, SELF_NAME, None
    if mkt is None:
        risks.append("缺胜平负赔率：概率来自自研模型，可靠性低于市场")
        source = f"{SELF_NAME}（无赔率）"
    elif devig(od.get("over"), od.get("under")) is None:
        risks.append(f"缺大小球盘：比分/大小球用 {SELF_NAME}")
        source = f"{SELF_NAME}（缺大小球盘）"
    else:
        matrix, fit = implied_matrix(od, rho)
        source = "市场隐含"
        if fit["rmse"] > FIT_RMSE_WARN:
            risks.append(f"各盘口之间不完全一致（拟合误差 {fit['rmse']:.3f}）")

    mk = derive_markets(matrix)
    if mkt is not None:
        p, p_src, tiers = tuple(mkt), "市场", MARKET_TIERS
    else:
        p, p_src, tiers = matrix_1x2(matrix), SELF_NAME, MODEL_TIERS

    if mkt is not None:
        for name, q in models.items():
            d = [q[i] - mkt[i] for i in range(3)]
            i = int(np.argmax(np.abs(d)))
            if abs(d[i]) > DIVERGE_PP:
                hints.append(f"{name} 与市场分歧：{LABEL[_KEYS[i]]} {d[i]*100:+.0f}pp"
                             "（仅提示，历史上市场更准）")

    ah, ah_hints = asian(matrix, od, self_matrix, source == "市场隐含")
    hints = ah_hints + hints                     # 亚盘为主：亚盘提示排在前

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
        "ah_move": ah_trail(ah_open or first_row, last_row, odds_row),
        "risks": risks, "lean": LABEL[order[0]], "double": double_label(order[:2]),
        "tier": tier, "hit1": hit1, "hit2": hit2, "est1": est1, "est2": est2,
        "highlight": mkt is not None and tier == "高",   # 重点：只认市场档（自研档样本少）
    }
