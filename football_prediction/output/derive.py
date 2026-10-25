"""
output/derive.py  v1.4.0
输出层：从比分矩阵推导胜平负、大小球、双方进球、亚盘让球等衍生市场概率。
v1.2.0: 亚盘改为 赢/赢半/走/输半/输 五种结算（修复整数盘把"走盘"算作输的 bug），
        支持四分之一盘（-0.25/-0.75…拆成两半注），盘口 -2.5~+2.5 步长 0.25；
        新增双方进球、预期进球、公平盘口（最接近五五开的亚盘线）。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import numpy as np

LAYER_VERSION = "1.4.0"

OU_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
AH_LINES = tuple(x / 4 for x in range(-10, 11))   # 主队让球线：-2.5 … +2.5
AH_KEYS = ("win", "half_win", "push", "half_lose", "lose")


def margin_pmf(m: np.ndarray) -> dict[int, float]:
    """比分矩阵 -> 主队净胜球分布 {净胜: 概率}"""
    n = m.shape[0]
    return {d: float(np.trace(m, offset=-d)) for d in range(-(n - 1), n)}


def _half_lines(line: float) -> tuple[float, float]:
    """四分之一盘拆成相邻两条半注线（-0.75 -> -1.0 与 -0.5）；其余盘口两半相同。"""
    if np.isclose((line * 4) % 2, 1):
        return line - 0.25, line + 0.25
    return line, line


def ah_outcome(pmf: dict[int, float], line: float) -> dict[str, float]:
    """
    主队按让球线 line 投注的结算分布（line=-0.75 表示主让 0.75，+0.5 表示主受让 0.5）。
    返回 win / half_win / push / half_lose / lose 五项概率，和为 1。
    """
    out = dict.fromkeys(AH_KEYS, 0.0)
    l1, l2 = _half_lines(line)
    for d, p in pmf.items():
        r = [np.sign(d + l) for l in (l1, l2)]     # 每半注：1 赢 / 0 走 / -1 输
        s = r[0] + r[1]
        key = {2: "win", 1: "half_win", 0: "push", -1: "half_lose", -2: "lose"}[int(s)]
        if s == 0 and r[0] != 0:                    # 一赢一输：两条线相差 0.5，不会出现
            raise AssertionError((line, d))
        out[key] += p
    return out


def ah_fair_prob(o: dict[str, float]) -> float:
    """
    亚盘"等效赢盘概率"：公平赔率 = 1/该值，与盘口去水后的概率可直接比较。
    推导：期望收益 0 ⇔ (赔率-1)·(赢+赢半/2) = 输+输半/2。走盘不计入。
    """
    w = o["win"] + o["half_win"] / 2
    l_ = o["lose"] + o["half_lose"] / 2
    return w / (w + l_) if w + l_ > 0 else 0.5


def derive_markets(score_matrix: np.ndarray) -> dict:
    """
    输入：(N+1)×(N+1) 比分概率矩阵，行=主队进球，列=客队进球。
    输出：各衍生市场概率及 layer_ver。
    """
    m = score_matrix
    n = m.shape[0]
    g = np.arange(n)

    out: dict = {
        "home_win": round(float(np.tril(m, -1).sum()), 4),
        "draw":     round(float(np.trace(m)), 4),
        "away_win": round(float(np.triu(m, 1).sum()), 4),
        "exp_home_goals": round(float((m.sum(1) * g).sum()), 3),
        "exp_away_goals": round(float((m.sum(0) * g).sum()), 3),
        "btts_yes": round(float(m[1:, 1:].sum()), 4),
    }

    tot = np.add.outer(g, g)
    for line in OU_LINES:
        over = float(m[tot > line].sum())
        out[f"over_{line}"] = round(over, 4)
        out[f"under_{line}"] = round(1.0 - over, 4)

    # 亚盘：每条线存 [赢, 赢半, 走, 输半, 输]（主队方向）
    pmf = margin_pmf(m)
    best, fair_line = 1.0, 0.0
    for line in AH_LINES:
        o = ah_outcome(pmf, line)
        out[f"ah_{line:+.2f}"] = [round(o[k], 4) for k in AH_KEYS]
        gap = abs(ah_fair_prob(o) - 0.5)
        if gap < best:
            best, fair_line = gap, line
    out["ah_fair_line"] = fair_line

    flat = m.flatten()
    out["top5_scores"] = [
        {"score": f"{i // n}-{i % n}", "prob": round(float(flat[i]), 4)}
        for i in flat.argsort()[::-1][:5]
    ]
    out["layer_ver"] = LAYER_VERSION
    return out
