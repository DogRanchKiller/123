"""
output/derive.py  v1.1.0（推导逻辑未变；输出层 1.1.0 新增 report.py）
输出层：从 Dixon-Coles 比分矩阵推导大小球、让球等衍生市场概率。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import numpy as np

LAYER_VERSION = "1.1.0"


def derive_markets(score_matrix: np.ndarray) -> dict:
    """
    输入：(N+1)×(N+1) 比分概率矩阵，行=主队进球，列=客队进球。
    输出：各衍生市场概率及 layer_ver。
    """
    m = score_matrix
    max_g = m.shape[0] - 1

    # 1X2
    home_win = float(np.tril(m, -1).sum())
    draw     = float(np.trace(m))
    away_win = float(np.triu(m, 1).sum())

    # 大小球：总进球数阈值
    over_under: dict[str, float] = {}
    for line in (1.5, 2.5, 3.5, 4.5):
        over = 0.0
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                if i + j > line:
                    over += m[i, j]
        over_under[f"over_{line}"]  = round(over, 4)
        over_under[f"under_{line}"] = round(1.0 - over, 4)

    # 让球（亚盘）：主队净胜球期望
    handicap: dict[str, float] = {}
    for h in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
        cover = 0.0
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                if (i - j) + h > 0:
                    cover += m[i, j]
        label = f"home_cover_{h:+.1f}"
        handicap[label] = round(cover, 4)

    # 最可能比分 Top 5
    flat  = m.flatten()
    top5_idx = flat.argsort()[::-1][:5]
    top5 = []
    for idx in top5_idx:
        hg, ag = divmod(int(idx), max_g + 1)
        top5.append({"score": f"{hg}-{ag}", "prob": round(float(m[hg, ag]), 4)})

    return {
        "home_win":   round(home_win, 4),
        "draw":       round(draw, 4),
        "away_win":   round(away_win, 4),
        **over_under,
        **handicap,
        "top5_scores": top5,
        "layer_ver":   LAYER_VERSION,
    }
