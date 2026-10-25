"""model_lineup：位置分组、常规首发、阵容特征、系数拟合与 λ 调整（合成阵容，不联网）。"""
import numpy as np
import pytest

from football_prediction.data.fotmob import init_fotmob
from football_prediction.model_lineup.adjust import (
    COEF_POST, COEF_PRE, FEATURES, adjust_lambdas, coef_for, fit_coef, odds_timing)
from football_prediction.model_lineup.ratings import (
    LineupModel, current_lineup, first_standard_at, load_history, pos_group)
from tests.conftest import TEAMS

# 每队 14 人：0 门将、1–4 后卫、5–8 中场、9–10 前锋，11–13 替补（中场 / 前锋 / 门将）
POS = [11, 32, 33, 34, 35, 62, 63, 64, 65, 103, 105, 64, 104, 11]
ATT = [0.0, 0.05, 0.05, 0.05, 0.05, 0.2, 0.2, 0.2, 0.2, 0.6, 0.6, 0.1, 0.1, 0.0]


def _pid(team, k):
    return TEAMS.index(team) * 100 + k


def _lineups(conn):
    """每场两队都首发 0–10 号，替补 11–13 号不上场；进攻产出按 ATT。"""
    init_fotmob(conn)
    for mid, h, a in conn.execute("SELECT match_id, home_team, away_team FROM matches").fetchall():
        for side, t in (("home", h), ("away", a)):
            for k in range(14):
                starter = k < 11
                conn.execute("INSERT INTO lineups VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (mid, "f1", "standard", side, _pid(t, k), None,
                              "starter" if starter else "sub", POS[k], None, None))
                if starter:
                    conn.execute("INSERT INTO player_match VALUES (?,?,?,?,?,?,?,?)",
                                 (mid, _pid(t, k), side, None, 90, ATT[k] / 2, ATT[k] / 2, ATT[k] / 2))
    conn.commit()


def test_pos_group():
    assert [pos_group(p) for p in (11, 32, 65, 104, None)] == ["GK", "DEF", "MID", "FWD", "UNK"]


def test_usual_xi_and_features(league):
    conn, cutoff = league
    _lineups(conn)
    m = LineupModel()
    m.fit(conn, "E0", cutoff)
    assert set(m.usual_xi("A")) == {_pid("A", k) for k in range(11)}
    assert m.pos[_pid("A", 0)] == "GK" and m.pos[_pid("A", 9)] == "FWD"
    assert m.player_rate(_pid("A", 9)) > m.player_rate(_pid("A", 5)) > m.player_rate(_pid("A", 1))

    same = [(_pid("A", k), POS[k]) for k in range(11)]
    f = m.team_features("A", same)
    assert f == pytest.approx({"d_att": 0.0, "rot": 0.0, "rot_def": 0.0})

    # 两名前锋换成替补中场 / 前锋、门将换替补门将：进攻评分下降，轮换 3/11，防守轮换 1/5
    rotated = same[:9] + [(_pid("A", 11), 64), (_pid("A", 12), 104)]
    rotated[0] = (_pid("A", 13), 11)
    f = m.team_features("A", rotated)
    assert f["d_att"] < 0
    assert f["rot"] == pytest.approx(3 / 11)
    assert f["rot_def"] == pytest.approx(1 / 5)

    assert m.team_features("A", same[:10]) is None             # 不足 11 人
    assert m.team_features("Z", same) is None                  # 没有历史


def test_history_respects_cutoff_and_latest_batch(league):
    conn, cutoff = league
    _lineups(conn)
    first = conn.execute("SELECT MIN(match_date) FROM matches").fetchone()[0]
    assert load_history(conn, "E0", first).empty
    mid = "E0-0"
    conn.execute("INSERT INTO lineups VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (mid, "f2", "predicted", "home", 999, None, "starter", 11, None, None))
    hist = load_history(conn, "E0", cutoff)
    assert set(hist.loc[hist.match_id == mid, "player_id"]) == {999}
    assert current_lineup(conn, mid) == ("predicted", {"home": [(999, 11)], "away": []})
    assert current_lineup(conn, "nope") is None


def test_fit_coef_recovers_coefficients():
    rng = np.random.default_rng(1)
    n = 60000                      # SE ≈ 0.011；6000 时 SE ≈ 0.036，0.08 的容差会偶发失败
    X = rng.normal(0, 0.3, (n, len(FEATURES)))
    true = np.array([0.5, -0.3, 0.2, 0.0])
    log_lam = np.log(rng.uniform(0.8, 2.0, n))
    goals = rng.poisson(np.exp(log_lam + X @ true))
    b = fit_coef(X, log_lam, goals, ridge=0.0)
    assert np.array([b[k] for k in FEATURES]) == pytest.approx(true, abs=0.05)


def test_adjust_lambdas():
    f = {"d_att": 0.0, "rot": 0.0, "rot_def": 0.0}
    assert adjust_lambdas(1.5, 1.1, f, f) == pytest.approx((1.5, 1.1))   # COEF 为 0 时不调整
    weak = {"d_att": -0.2, "rot": 0.3, "rot_def": 0.5}
    coef = {"d_att": 1.0, "rot": 0.0, "opp_rot_def": 0.2, "opp_rot": 0.0}
    lh, la = adjust_lambdas(1.5, 1.1, weak, f, coef)
    assert lh == pytest.approx(1.5 * np.exp(-0.2))
    assert la == pytest.approx(1.1 * np.exp(0.2 * 0.5))


def test_merge_rule_timing():
    t0, t1 = "2026-10-25T10:00:00+00:00", "2026-10-25T10:30:00+00:00"
    assert odds_timing(t0, t1) == "pre"           # 赔率早于首发：赔率里还没有阵容
    assert odds_timing(t1, t0) == "post"
    assert odds_timing(t1, t1) == "post"          # 同一轮先抓阵容再抓赔率
    assert odds_timing(t0, None) == odds_timing(None, t1) == "pre"
    assert coef_for("pre") is COEF_PRE and coef_for("post") is COEF_POST


def test_first_standard_at(league):
    conn, _ = league
    init_fotmob(conn)
    for at, kind in (("2026-10-25T09:00", "predicted"), ("2026-10-25T10:00", "standard"),
                     ("2026-10-25T11:00", "standard")):
        conn.execute("INSERT INTO lineups VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("m", at, kind, "home", 1, None, "starter", 11, None, None))
    assert first_standard_at(conn, "m") == "2026-10-25T10:00"
    assert first_standard_at(conn, "nope") is None
