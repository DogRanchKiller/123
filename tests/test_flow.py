"""v1.4.0 判断流程：亚盘结算、市场隐含反推、Elo 有序 logit、blend、数据迁移与赔率快照、
盘口变动方向、单场判断与赛后大小球/比分评分。"""
import json
import sqlite3

import numpy as np
import pytest

from football_prediction.data import loader
from football_prediction.model_blend.blend import blend_1x2, W_ELO
from football_prediction.model_elo.elo import EloModel, ordlogit, fit_ordlogit
from football_prediction.model_market.implied import dc_matrix, fair_probs, fit_lambdas, implied_matrix
from football_prediction.output.analysis import analyse, movement, devig, matrix_1x2
from football_prediction.output.derive import ah_outcome, ah_fair_prob, margin_pmf, derive_markets
from football_prediction.review.store import market_log_losses, save_prediction, score_predictions


# ---------- 亚盘结算 ----------
PMF = {-1: 0.2, 0: 0.3, 1: 0.3, 2: 0.2}   # 主队净胜球分布


def test_ah_half_line_no_push():
    o = ah_outcome(PMF, -0.5)
    assert o["win"] == pytest.approx(0.5) and o["lose"] == pytest.approx(0.5)
    assert o["push"] == o["half_win"] == o["half_lose"] == 0


def test_ah_whole_line_push():
    o = ah_outcome(PMF, -1.0)
    assert (o["win"], o["push"], o["lose"]) == pytest.approx((0.2, 0.3, 0.5))
    assert ah_fair_prob(o) == pytest.approx(0.2 / 0.7)


def test_ah_quarter_line_splits():
    o = ah_outcome(PMF, -0.75)          # 一半 -0.5、一半 -1.0：净胜1球 = 赢半
    assert o["win"] == pytest.approx(0.2) and o["half_win"] == pytest.approx(0.3)
    assert o["lose"] == pytest.approx(0.5) and o["push"] == 0
    assert sum(o.values()) == pytest.approx(1.0)


def test_derive_ah_keys_and_margin():
    m = dc_matrix(1.6, 1.1)
    mk = derive_markets(m)
    assert sum(margin_pmf(m).values()) == pytest.approx(1.0)
    assert len(mk["ah_-0.50"]) == 5 and sum(mk["ah_-0.75"]) == pytest.approx(1.0, abs=1e-3)
    assert mk["ah_-0.50"][0] == pytest.approx(mk["home_win"], abs=1e-3)   # 让半球赢盘 = 主胜


# ---------- 市场隐含 ----------
def _odds_from(lh, la, rho=-0.05, margin=1.05):
    m = dc_matrix(lh, la, rho)
    ph, pdraw, pa = matrix_1x2(m)
    tot = np.add.outer(np.arange(9), np.arange(9))
    po = m[tot > 2.5].sum()
    o = ah_outcome(margin_pmf(m), -0.5)
    pah = ah_fair_prob(o)
    return {"h": 1 / (ph * margin), "d": 1 / (pdraw * margin), "a": 1 / (pa * margin),
            "over": 1 / (po * margin), "under": 1 / ((1 - po) * margin),
            "ah_line": -0.5, "ah_h": 1 / (pah * margin), "ah_a": 1 / ((1 - pah) * margin)}


def test_implied_round_trip():
    f = fit_lambdas(_odds_from(1.9, 0.9))
    assert (f["lam_h"], f["lam_a"]) == pytest.approx((1.9, 0.9), abs=1e-3)
    assert f["rmse"] < 1e-3 and f["used"] == ["1x2", "over25", "ah"]


def test_implied_needs_1x2():
    assert implied_matrix({"over": 1.9, "under": 1.9}) is None
    fp = fair_probs({"h": 2.0, "d": 3.5, "a": 3.8})
    assert fp["1x2"].sum() == pytest.approx(1.0) and "over25" not in fp


# ---------- Elo / blend ----------
def test_ordlogit_sums_to_one_and_monotone():
    p = ordlogit(np.array([-3, 0, 3]), 0.5, 0.3)
    assert np.allclose(p.sum(1), 1) and (p > 0).all()
    assert p[0, 0] < p[1, 0] < p[2, 0]


def test_fit_ordlogit_default_when_few():
    assert fit_ordlogit([0.1] * 10, [0] * 10) == (0.5, 0.3)


def test_elo_mov_and_fit(league):
    conn, cutoff = league
    e = EloModel()
    e.fit(conn, "E0", cutoff)
    assert e.ab != (0.5, 0.3)                              # 120 场 ≥ MIN_FIT，已拟合
    assert e.ratings["A"] > e.ratings["F"]
    p = e.predict("A", "F")
    assert p["home_win"] > p["away_win"] and sum(p[k] for k in ("home_win", "draw", "away_win")) \
        == pytest.approx(1, abs=1e-3)
    big, small = EloModel(), EloModel()                   # 净胜球越多，评分变化越大
    big.update_one("X", "Y", 4, 0)
    small.update_one("X", "Y", 1, 0)
    assert big.ratings["X"] > small.ratings["X"] > 1500


def test_blend():
    p = blend_1x2((0.5, 0.3, 0.2), (0.3, 0.3, 0.4))
    assert p[0] == pytest.approx(0.5 * (1 - W_ELO) + 0.3 * W_ELO) and sum(p) == pytest.approx(1)


# ---------- 数据层：迁移、只补空值、快照 ----------
OLD_SCHEMA = """
CREATE TABLE match_odds (match_id TEXT PRIMARY KEY, avg_h REAL, avg_d REAL, avg_a REAL,
    avgc_h REAL, avgc_d REAL, avgc_a REAL, b365_h REAL, b365_d REAL, b365_a REAL,
    avg_over25 REAL, avg_under25 REAL, avgc_over25 REAL, avgc_under25 REAL,
    fetched_at TEXT NOT NULL, layer_ver TEXT NOT NULL);
CREATE TABLE fixtures (match_id TEXT PRIMARY KEY, league TEXT NOT NULL, season TEXT NOT NULL,
    match_date TEXT NOT NULL, kickoff_utc TEXT, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
    avg_h REAL, avg_d REAL, avg_a REAL, fetched_at TEXT NOT NULL, layer_ver TEXT NOT NULL);
INSERT INTO match_odds (match_id, avg_h, fetched_at, layer_ver) VALUES ('m1', 2.0, 'old', '1.3.0');
"""


def test_migration_idempotent(tmp_path):
    db = str(tmp_path / "old.db")
    c = sqlite3.connect(db)
    c.executescript(OLD_SCHEMA)
    c.close()
    for _ in range(2):
        c = loader.init_db(db)
        cols = {r[1] for r in c.execute("PRAGMA table_info(match_odds)")}
        assert {"ah_line", "avgc_ahh", "ps_h", "psc_a"} <= cols
        assert {"ah_line", "avg_over25"} <= {r[1] for r in c.execute("PRAGMA table_info(fixtures)")}
        assert c.execute("SELECT avg_h FROM match_odds WHERE match_id='m1'").fetchone()[0] == 2.0
        c.close()


def test_upsert_odds_fills_nulls_only(conn):
    cur = conn.cursor()
    loader._upsert_odds(cur, [{"match_id": "m", "avg_h": 2.0}], "t1")
    loader._upsert_odds(cur, [{"match_id": "m", "avg_h": 9.9, "ah_line": -0.5}], "t2")
    assert conn.execute("SELECT avg_h, ah_line FROM match_odds").fetchone() == (2.0, -0.5)


def test_snapshots_append_on_change_and_movement(conn):
    cols = list(loader._FIX_ODDS_COLS.values())
    a = dict(zip(cols, (2.0, 3.4, 3.8, 1.9, 1.9, -0.25, 1.9, 1.95)))
    assert loader.save_snapshots(conn, [("m", *a.values())], "2025-01-01T00") == 1
    assert loader.save_snapshots(conn, [("m", *a.values())], "2025-01-01T06") == 0   # 未变不写
    assert loader.odds_movement(conn, "m") is None
    b = {**a, "avg_h": 1.7, "avg_a": 4.8, "ah_line": -0.5}
    assert loader.save_snapshots(conn, [("m", *b.values())], "2025-01-02T00") == 1
    assert loader.save_snapshots(conn, [("x", *[None] * len(cols))], "2025-01-02T00") == 0
    first, last = loader.odds_movement(conn, "m")
    assert first["avg_h"] == 2.0 and last["ah_line"] == -0.5
    txt = movement(first, last)
    assert "偏向主队" in txt and "亚盘" in txt and "不反向" in txt


def test_movement_directions():
    base = dict(avg_h=2.0, avg_d=3.4, avg_a=3.8, ah_line=-0.25)
    assert movement(base, dict(base)) == "平稳"
    away = dict(avg_h=2.6, avg_d=3.4, avg_a=2.8, ah_line=0.0)
    assert "偏向客队" in movement(base, away)
    mixed = dict(avg_h=1.7, avg_d=3.6, avg_a=4.8, ah_line=0.0)   # 概率偏主、盘口偏客
    assert "方向不一致" in movement(base, mixed)


# ---------- 单场判断 ----------
def test_analyse_market_base_and_divergence_hint():
    xg = dc_matrix(1.2, 1.2)
    row = dict(avg_h=1.5, avg_d=4.2, avg_a=6.5, avg_over25=1.7, avg_under25=2.1,
               ah_line=-1.0, avg_ahh=1.9, avg_aha=1.95)
    a = analyse(row, xg, -0.05, {"dc_xg": matrix_1x2(xg)}, risks=["X 升班马"])
    assert a["p_src"] == "市场" and a["source"] == "市场隐含"
    assert a["p1x2"] == pytest.approx(devig(1.5, 4.2, 6.5))
    assert a["tier"] == "高" and a["lean"] == "主胜"
    assert a["hints"] and "dc_xg 与市场分歧" in a["hints"][0]       # dc_xg 主胜远低于市场
    assert a["risks"] == ["X 升班马"] and a["ah"]["line"] == -1.0
    assert a["ah"]["fair"] == pytest.approx(a["ah"]["market_fair"], abs=0.03)
    assert a["markets"]["exp_home_goals"] > a["markets"]["exp_away_goals"]


def test_analyse_fallbacks():
    xg = dc_matrix(1.5, 1.0)
    a = analyse(None, xg, -0.05, {"blend": (0.5, 0.3, 0.2)})
    assert a["p_src"] == "blend" and a["p1x2"] == (0.5, 0.3, 0.2) and a["hit1"] == 0.52
    assert any("缺胜平负" in r for r in a["risks"]) and a["ah"] is None
    b = analyse(dict(avg_h=2.0, avg_d=3.4, avg_a=3.8), xg, -0.05)
    assert b["p_src"] == "市场" and b["source"].startswith("dc_xg")
    assert any("缺大小球盘" in r for r in b["risks"])


# ---------- 赛后大小球 / 比分评分 ----------
def test_market_log_losses():
    m = [0.0] * 81
    m[2 * 9 + 1] = 0.25
    ou, sc = market_log_losses({"over_2.5": 0.6, "score_matrix": m}, 2, 1)
    assert ou == pytest.approx(-np.log(0.6)) and sc == pytest.approx(-np.log(0.25))
    ou, sc = market_log_losses({"over_2.5": 0.6}, 1, 0)
    assert ou == pytest.approx(-np.log(0.4)) and sc is None
    assert market_log_losses({}, 9, 0) == (None, None)


def test_score_predictions_fills_market_losses(conn):
    conn.execute("INSERT INTO matches VALUES ('g',?,?,?,?,?,?,?,?,?,?)",
                 ("E0", "2425", "2025-01-01", "A", "B", 2, 1, "t", "now", "t"))
    m = dc_matrix(1.5, 1.0).ravel().tolist()
    save_prediction(conn, "g", "market_implied", "1.0.0", "1", 0.5, 0.3, 0.2,
                    {"over_2.5": 0.55, "score_matrix": m})
    save_prediction(conn, "g", "elo", "1.1.0", "1", 0.5, 0.3, 0.2)
    assert score_predictions(conn) == 2
    rows = dict(conn.execute("SELECT model_name, score_log_loss FROM predictions").fetchall())
    assert rows["market_implied"] == pytest.approx(-np.log(m[19]), abs=1e-5)
    assert rows["elo"] is None
