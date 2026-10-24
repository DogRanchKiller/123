"""各模块 LAYER_VERSION 必须与 version.py 登记一致：防止改了代码忘记升版本，
导致新旧预测混在同一版本号下。"""
import importlib

import pytest

from football_prediction import version

MODULES = {
    "football_prediction.data.loader":           "data",
    "football_prediction.data.understat":        "data",
    "football_prediction.data.oddsportal":       "data",
    "football_prediction.features.builder":      "features",
    "football_prediction.model_elo.elo":         "model_elo",
    "football_prediction.model_dc.dixon_coles":  "model_dc",
    "football_prediction.model_dc.sot_dc":       "model_sot",
    "football_prediction.model_dc.xg_dc":        "model_xg",
    "football_prediction.model_market.implied":  "model_market",
    "football_prediction.model_blend.blend":     "model_blend",
    "football_prediction.model_lgbm.lgbm_model": "model_lgbm",
    "football_prediction.calibration.platt":     "calibration",
    "football_prediction.output.derive":         "output",
    "football_prediction.output.report":         "output",
    "football_prediction.output.analysis":       "output",
    "football_prediction.output.pipeline":       "output",
    "football_prediction.explain":               "output",
    "football_prediction.validation.backtest":   "validation",
    "football_prediction.review.store":          "review",
}


@pytest.mark.parametrize("mod,layer", MODULES.items())
def test_layer_version_matches_registry(mod, layer):
    try:
        m = importlib.import_module(mod)
    except ImportError as e:   # 可选依赖（如 lightgbm）未安装时跳过
        pytest.skip(f"{mod}: {e}")
    assert m.LAYER_VERSION == version.get(layer)


def test_model_classes_report_own_version():
    from football_prediction.model_dc.sot_dc import SotDixonColesModel
    from football_prediction.model_dc.xg_dc import XgDixonColesModel
    assert SotDixonColesModel.MODEL_VER == version.get("model_sot")
    assert XgDixonColesModel.MODEL_VER == version.get("model_xg")


def test_live_docstring_version():
    import football_prediction.live as live
    assert f"v{version.get('live')}" in live.__doc__.splitlines()[1]


def test_primary_model_is_registered():
    name, key = version.PRIMARY_MODEL
    assert key in version.LAYER_VERSIONS
    assert name in ("dixon_coles", "dc_sot", "dc_xg", "elo", "market_implied")
    fb_name, fb_key = version.FALLBACK_MODEL
    assert fb_key in version.LAYER_VERSIONS and fb_name == "dc_xg"
    assert version.PROMOTE_MIN_N >= 100
