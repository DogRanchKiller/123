# version.py — 各层版本号注册表
# 修改某一层时只更新对应条目，review 层用版本号区分不同批次预测

SYSTEM_VERSION = "1.0.0"

LAYER_VERSIONS = {
    "data":          "1.0.0",
    "features":      "1.0.0",
    "model_elo":     "1.0.0",
    "model_dc":      "1.3.0",   # + 单队参数收缩 shrink=0.5（修复升级队参数发散）
    "model_lgbm":    "1.1.0",   # 滚动 OOS，训练样本翻倍；修复重名方法 bug
    "calibration":   "1.0.0",   # Platt scaling；2425 验证无增益（±0.005），不进主流程
    "output":        "1.0.0",
    "validation":    "1.0.0",
    "review":        "1.0.0",
}


def get(layer: str) -> str:
    """获取某层的当前版本号"""
    return LAYER_VERSIONS[layer]
