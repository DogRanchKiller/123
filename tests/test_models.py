"""模型层：比分矩阵与衍生市场一致性；射正 / xG 版在 w=1 时退化为纯进球拟合。"""
import numpy as np
import pytest

from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.model_dc.sot_dc import SotDixonColesModel
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.output.derive import derive_markets


def _fit(cls, league, **kw):
    conn, cutoff = league
    m = cls(**kw)
    m.fit(conn, "E0", cutoff)
    return m


def test_derive_markets_consistent(league):
    m = _fit(XgDixonColesModel, league)
    mk = derive_markets(m.score_matrix("A", "F"))
    assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0, abs=1e-3)
    for line in (1.5, 2.5, 3.5, 4.5):
        assert mk[f"over_{line}"] + mk[f"under_{line}"] == pytest.approx(1.0, abs=1e-6)
    assert mk["over_1.5"] >= mk["over_2.5"] >= mk["over_3.5"]
    probs = [s["prob"] for s in mk["top5_scores"]]
    assert probs == sorted(probs, reverse=True) and len(probs) == 5


def test_stronger_team_favoured(league):
    for cls in (DixonColesModel, SotDixonColesModel, XgDixonColesModel):
        p = _fit(cls, league).predict_1x2("A", "F")
        assert p["home_win"] > 0.5 > p["away_win"], cls.__name__


def test_signal_models_identical_at_w1(league):
    """w=1 时只用进球：射正版与 xG 版必须完全一致，且接近原版 DC。"""
    sot = _fit(SotDixonColesModel, league, goal_weight=1.0)
    xg = _fit(XgDixonColesModel, league, goal_weight=1.0)
    dc = _fit(DixonColesModel, league)
    for h, a in (("A", "F"), ("C", "D"), ("F", "B")):
        ms, mx, md = sot.score_matrix(h, a), xg.score_matrix(h, a), dc.score_matrix(h, a)
        np.testing.assert_allclose(ms, mx, atol=1e-12)
        # 原版用不同的似然实现与优化器，只要求数值接近
        p_s, p_d = derive_markets(ms), derive_markets(md)
        for k in ("home_win", "draw", "away_win"):
            assert p_s[k] == pytest.approx(p_d[k], abs=0.02), (h, a, k)


def test_signal_actually_used(league):
    """w<1 时信号确实参与拟合（结果应与 w=1 不同）。"""
    a = _fit(XgDixonColesModel, league, goal_weight=1.0).predict_1x2("A", "F")
    b = _fit(XgDixonColesModel, league, goal_weight=0.3).predict_1x2("A", "F")
    assert abs(a["home_win"] - b["home_win"]) > 1e-4


def test_model_ver_in_output(league):
    p = _fit(XgDixonColesModel, league).predict_1x2("A", "B")
    assert p["model_ver"] == XgDixonColesModel.MODEL_VER
