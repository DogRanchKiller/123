"""model_market/devig.py：按比例 / Shin 去水；implied 的 method 参数默认不改变结果。"""
import numpy as np
import pytest

from football_prediction.model_market import devig as dv
from football_prediction.model_market.implied import fair_probs, fit_lambdas

# mberk/shin（MIT）shin.calculate_implied_probabilities([2.6, 2.4, 4.3]) 的输出
SHIN_REF = [0.37299406033208965, 0.4047794109200184, 0.2222265287474275]


def test_shin_matches_reference_package():
    assert dv.shin([2.6, 2.4, 4.3]) == pytest.approx(SHIN_REF, abs=1e-9)


def test_shin_favourite_longshot_direction():
    odds = [1.2, 6.5, 15.0]
    p, q = dv.shin(odds), dv.proportional(odds)
    assert p.sum() == pytest.approx(1.0)
    assert p[0] > q[0] and p[2] < q[2]          # 热门升、冷门降


def test_shin_symmetric_and_no_margin():
    assert dv.shin([1.9, 1.9]) == pytest.approx([0.5, 0.5])
    assert dv.shin([2.0, 2.0]) == pytest.approx([0.5, 0.5])          # 无抽水 → 按比例
    assert dv.shin([3.0, 3.0, 3.5]) == pytest.approx(dv.proportional([3.0, 3.0, 3.5]))


def test_devig_unknown_method():
    with pytest.raises(ValueError):
        dv.devig([2.0, 2.0], "power")


def test_implied_default_is_proportional():
    odds = {"h": 1.8, "d": 3.8, "a": 4.6, "over": 1.85, "under": 2.0,
            "ah_line": -0.75, "ah_h": 2.0, "ah_a": 1.9}
    q = 1 / np.array([1.8, 3.8, 4.6])
    assert fair_probs(odds)["1x2"] == pytest.approx(q / q.sum())
    a, b = fit_lambdas(odds), fit_lambdas(odds, method="shin")
    assert a["lam_h"] != pytest.approx(b["lam_h"], abs=1e-4)          # shin 确实改变结果
    assert b["lam_h"] - b["lam_a"] > a["lam_h"] - a["lam_a"]           # 热门主队优势更大
