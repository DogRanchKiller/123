"""
model_blend/blend.py  v1.0.0
自研模型融合：1X2 = (1−w)·dc_xg + w·Elo，w = 0.23。
权重在 2324+2425 选定，2526+2627 确认（_diag/explore/blend_pkg_elo.py，n=3411）：
    相对 dc_xg 确认期 logloss −0.0046±0.0013。
只融合 1X2；比分/大小球仍用各自比分矩阵。
组件（model_xg、model_elo）任一升版本时，本层也须升版本并重新验证权重。
修改此文件后请同步更新 version.py 中 "model_blend" 的版本号。
"""
LAYER_VERSION = "1.0.0"
MODEL_NAME = "blend_xg_elo"
W_ELO = 0.23


def blend_1x2(p_xg, p_elo, w: float = W_ELO) -> tuple[float, float, float]:
    """线性融合两组 [主胜, 平, 客胜] 概率，返回归一化结果"""
    p = [(1 - w) * a + w * b for a, b in zip(p_xg, p_elo)]
    s = sum(p)
    return tuple(x / s for x in p)
