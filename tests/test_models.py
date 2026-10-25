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


def _poisson_odds(lh, la, maxg=16):
    """Fair (no-vig) 1X2 and O/U 2.5 odds under independent Poisson."""
    from scipy.stats import poisson
    k = np.arange(maxg)
    j = np.outer(poisson.pmf(k, lh), poisson.pmf(k, la))
    ph, pd_, pa = np.tril(j, -1).sum(), np.trace(j), np.triu(j, 1).sum()
    under = j[(k[:, None] + k[None, :]) <= 2].sum()
    return 1 / ph, 1 / pd_, 1 / pa, 1 / (1 - under), 1 / under


def test_lambdas_from_odds_recovers_poisson():
    from football_prediction.model_dc.market_dc import lambdas_from_odds
    true = [(1.6, 1.1), (0.8, 2.2), (2.9, 0.6)]
    odds = np.array([_poisson_odds(*t) for t in true])
    lh, la = lambdas_from_odds(*odds.T)
    np.testing.assert_allclose(np.stack([lh, la], 1), true, atol=1e-3)
    lh, la = lambdas_from_odds(*odds[:, :3].T)               # 1X2 only
    np.testing.assert_allclose(np.stack([lh, la], 1), true, atol=1e-3)
    lh, _ = lambdas_from_odds([None, 2.0], [3.4, 3.4], [4.0, 4.0])
    assert np.isnan(lh[0]) and not np.isnan(lh[1])


def test_market_dc_goals_only_without_odds_and_uses_odds(league):
    from football_prediction.model_dc.market_dc import MarketDixonColesModel
    conn, cutoff = league
    goals = _fit(SotDixonColesModel, league, goal_weight=1.0).predict_1x2("A", "F")
    no_odds = _fit(MarketDixonColesModel, league).predict_1x2("A", "F")
    assert no_odds["home_win"] == pytest.approx(goals["home_win"], abs=1e-6)

    for mid, lh, la in conn.execute("SELECT match_id, home_xg, away_xg FROM match_xg").fetchall():
        conn.execute("INSERT INTO match_odds (match_id, avg_h, avg_d, avg_a, avg_over25, avg_under25,"
                     " fetched_at, layer_ver) VALUES (?,?,?,?,?,?,?,?)",
                     (mid, *_poisson_odds(lh, la), "now", "t"))
    with_odds = _fit(MarketDixonColesModel, league).predict_1x2("A", "F")
    assert abs(with_odds["home_win"] - goals["home_win"]) > 1e-4
    assert with_odds["model_ver"] == MarketDixonColesModel.MODEL_VER
