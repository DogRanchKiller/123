"""动态攻防 DC（model_dc/dynamic_dc.py）：合成比赛上的基本性质，不联网、不碰 football.db。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from football_prediction.model_dc.dynamic_dc import (
    DynamicDixonColesModel, DynamicShotsDixonColesModel, run_filter,
)


def _fixtures(conn, season, d, pairs):
    for i, (h, a) in enumerate(pairs):
        conn.execute(
            """INSERT INTO fixtures (match_id, league, season, match_date, kickoff_utc,
                   home_team, away_team, fetched_at, layer_ver) VALUES (?,?,?,?,?,?,?,?,?)""",
            (f"fx{i}", "E0", season, d, d + "T15:00:00+00:00", h, a, "now", "t"))
    conn.commit()


def test_matrix_and_strength_order(league):
    conn, cutoff = league
    for cls in (DynamicDixonColesModel, DynamicShotsDixonColesModel):
        m = cls()
        m.fit(conn, "E0", cutoff)
        mat = m.score_matrix("A", "F")
        assert abs(mat.sum() - 1) < 1e-9
        lh, la = m._lambda("A", "F")
        assert lh > la                                  # 合成数据里 A 最强、F 最弱
        assert m.attack["A"] > m.attack["F"] and m.defence["A"] > m.defence["F"]
        assert -0.3 <= m.rho <= 0.3
        assert m.predict_1x2("A", "F")["model_ver"] == cls.MODEL_VER


def test_no_future_information(league):
    conn, cutoff = league
    early = (date.fromisoformat(cutoff) - timedelta(days=30)).isoformat()
    a = DynamicShotsDixonColesModel()
    a.fit(conn, "E0", early)
    conn.execute("DELETE FROM matches WHERE match_date >= ?", (early,))
    b = DynamicShotsDixonColesModel()
    b.fit(conn, "E0", early)
    assert a.attack == b.attack and a.defence == b.defence and a.home_adv == b.home_adv


def test_newcomer_from_fixtures_takes_departed_mean(league):
    """新赛季开踢前：按 fixtures 换季，升班马 G 取离开球队 F 的均值；c=1 时留下的球队不变。"""
    conn, cutoff = league
    before = DynamicDixonColesModel()
    before.fit(conn, "E0", cutoff)
    _fixtures(conn, "2526", cutoff, [("A", "G"), ("B", "C"), ("D", "E")])
    after = DynamicDixonColesModel()
    after.fit(conn, "E0", cutoff)
    assert after.attack["G"] == before.attack["F"] and after.defence["G"] == before.defence["F"]
    assert after.attack["A"] == pytest.approx(before.attack["A"], abs=1e-12)
    assert after._lambda("H", "A") == pytest.approx(after._lambda("G", "A"))   # 不认识的球队同样按新来球队处理


def test_fixtures_same_season_no_transition(league):
    conn, cutoff = league
    before = DynamicDixonColesModel()
    before.fit(conn, "E0", cutoff)
    _fixtures(conn, "2425", cutoff, [("A", "B")])
    after = DynamicDixonColesModel()
    after.fit(conn, "E0", cutoff)
    assert after.attack == before.attack


def test_missing_signal_falls_back_to_goals():
    rng = np.random.default_rng(1)
    rows = [("2425", d, h, a, int(rng.poisson(1.4)), int(rng.poisson(1.1)))
            for d in range(40) for h, a in (("A", "B"), ("C", "D"))]
    df = pd.DataFrame(rows, columns=["season", "day", "home_team", "away_team", "hg", "ag"])
    nan = df.assign(sig_h=np.nan, sig_a=np.nan)
    goals = df.assign(sig_h=df.hg.astype(float), sig_a=df.ag.astype(float))
    s1, l1 = run_filter(nan, 0.7, 1e-4, 1.0)
    s2, l2 = run_filter(goals, 1.0, 1e-4, 1.0)
    assert np.allclose(l1, l2) and s1["attack"] == s2["attack"]
    assert not np.isnan(l1).any()
