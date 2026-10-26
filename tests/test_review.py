"""评分、去重、实盘成绩单与主模型替换检查。"""
import json
from datetime import datetime, timezone
from math import log

import numpy as np
import pytest

from football_prediction.data import fotmob
from football_prediction.review.scorecard import (
    live_report, promotion_check, horizon_report, _paired, _scored_first,
)
from football_prediction.review.store import (
    has_prediction, save_prediction, score_predictions, pending_fotmob, reconcile_results,
    ah_scores, ah_settle, horizon_of,
)


def _match(conn, mid, hg, ag):
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (mid, "E0", "2526", "2025-09-01", "H", "A", hg, ag, "t", "now", "t"))


def test_has_prediction_and_first_only(conn):
    assert not has_prediction(conn, "m1", "dc_xg", "1.0.0")
    save_prediction(conn, "m1", "dc_xg", "1.0.0", "1.0.0", 0.5, 0.3, 0.2)
    assert has_prediction(conn, "m1", "dc_xg", "1.0.0")
    assert not has_prediction(conn, "m1", "dc_xg", "1.0.1")   # 新版本另存
    assert not has_prediction(conn, "m1", "elo", "1.0.0")


def test_score_predictions_values_and_idempotent(conn):
    _match(conn, "m1", 2, 1)   # 主胜
    _match(conn, "m2", 1, 1)   # 平
    save_prediction(conn, "m1", "x", "1", "1", 0.5, 0.3, 0.2)
    save_prediction(conn, "m2", "x", "1", "1", 0.5, 0.3, 0.2)
    save_prediction(conn, "m3", "x", "1", "1", 0.5, 0.3, 0.2)   # 未完赛，不评分
    assert score_predictions(conn) == 2
    assert score_predictions(conn) == 0

    got = dict(conn.execute(
        "SELECT match_id, log_loss FROM predictions WHERE log_loss IS NOT NULL").fetchall())
    assert got["m1"] == pytest.approx(-log(0.5), abs=1e-6)
    assert got["m2"] == pytest.approx(-log(0.3), abs=1e-6)
    br = conn.execute("SELECT brier FROM predictions WHERE match_id='m1'").fetchone()[0]
    assert br == pytest.approx(0.5 ** 2 + 0.3 ** 2 + 0.2 ** 2, abs=1e-6)


def test_fotmob_fallback_and_reconcile(conn):
    fotmob.init_fotmob(conn)
    for mid in ("m1", "m2", "m3", "m4"):
        save_prediction(conn, mid, "x", "1", "1", 0.5, 0.3, 0.2)
    for mid, hg, ag in (("m1", 2, 1), ("m2", 1, 1), ("m4", 1, 0)):
        conn.execute("INSERT INTO fotmob_results VALUES (?,?,?,?,?,?)", (mid, "f" + mid, hg, ag, "t", "t"))
    _match(conn, "m4", 0, 0)                                   # football-data 已有：优先于 FotMob
    src = lambda: dict(conn.execute("SELECT match_id, result_src FROM predictions"))
    assert score_predictions(conn) == 3                        # m3 两边都没有，不评
    assert src() == {"m1": "fotmob", "m2": "fotmob", "m3": None, "m4": "fd"}
    assert pending_fotmob(conn) == 2
    assert set(_scored_first(conn)["match_id"]) == {"m1", "m2", "m4"}   # FotMob 先评的也进成绩单
    assert reconcile_results(conn) == (0, [])                  # football-data 还没到

    _match(conn, "m1", 2, 1)
    _match(conn, "m2", 1, 2)                                   # 与 FotMob 不一致
    n, bad = reconcile_results(conn)
    assert n == 2 and bad == [{"match_id": "m2", "fotmob": (1, 1), "fd": (1, 2)}]
    ll = dict(conn.execute("SELECT match_id, log_loss FROM predictions"))
    out = dict(conn.execute("SELECT match_id, actual_outcome FROM predictions"))
    assert ll["m1"] == pytest.approx(-log(0.5), abs=1e-6)
    assert ll["m2"] == pytest.approx(-log(0.2), abs=1e-6) and out["m2"] == "away_win"
    assert out["m4"] == "draw"
    assert pending_fotmob(conn) == 0 and src()["m1"] == src()["m2"] == "fd"
    assert reconcile_results(conn) == (0, []) and score_predictions(conn) == 0


@pytest.mark.parametrize("margin,line,want", [
    (1, -0.5, "win"), (0, -0.5, "lose"), (1, -1.0, "push"), (2, -1.0, "win"),
    (0, -0.25, "half_lose"), (1, -0.25, "win"), (1, -0.75, "half_win"), (2, -0.75, "win"),
    (0, 0.0, "push"), (0, 0.25, "half_win"), (-1, 0.75, "half_lose"), (3, -3.0, "push"),
    (3, -3.25, "half_lose"), (4, -3.75, "half_win"), (-2, 2.0, "push"),
])
def test_ah_settle(margin, line, want):
    assert ah_settle(margin, line) == want


def test_ah_scores_from_extra():
    ex = {"ah_-0.75": [0.3, 0.2, 0.0, 0.0, 0.5], "ah_+0.00": [0.4, 0.0, 0.3, 0.0, 0.3]}
    ll, hit = ah_scores(ex, 2, 1, -0.75)               # 净胜 1：赢半；赢盘概率 0.4/0.9 < 50% 选客
    assert ll == pytest.approx(-log(0.2)) and hit == 0.0
    ll, hit = ah_scores(ex, 1, 1, -0.0)                # 平手走盘：命中为空；-0.0 与 +0.00 同一键
    assert ll == pytest.approx(-log(0.3)) and hit is None
    assert ah_scores(ex, 1, 0, -1.5) == (None, None)   # extra 没有该线
    assert ah_scores(ex, 1, 0, None) == (None, None)


def _ah_extra(line, p):
    return {f"ah_{line:+.2f}": p, "ah_+0.00": [0.5, 0, 0, 0, 0.5]}


def test_ah_scoring_uses_market_line_for_all_models(conn):
    _match(conn, "m1", 2, 0)
    _match(conn, "m2", 1, 1)
    # 市场隐含行带赔率（线 -0.5），dc_xg 没有赔率：用同场赛前档的线
    save_prediction(conn, "m1", "market_implied", "1", "1", 0.5, 0.3, 0.2,
                    {**_ah_extra(-0.5, [0.55, 0, 0, 0, 0.45]), "odds": {"ah_line": -0.5}})
    save_prediction(conn, "m1", "dc_xg", "1", "1", 0.5, 0.3, 0.2, _ah_extra(-0.5, [0.4, 0, 0, 0, 0.6]))
    save_prediction(conn, "m1", "market_avg", "1", "1", 0.5, 0.3, 0.2, {"odds": [2.0, 3.3, 4.0]})
    save_prediction(conn, "m1", "market_implied_t1", "1", "1", 0.5, 0.3, 0.2,
                    {**_ah_extra(-0.75, [0.4, 0.2, 0, 0, 0.4]), "odds": {"ah_line": -0.75}})
    save_prediction(conn, "m1", "lineup_t1", "1", "1", 0.5, 0.3, 0.2, _ah_extra(-0.75, [0.5, 0.1, 0, 0, 0.4]))
    save_prediction(conn, "m2", "dc_xg", "1", "1", 0.4, 0.3, 0.3, _ah_extra(-0.5, [0.4, 0, 0, 0, 0.6]))
    score_predictions(conn)
    got = {(m, n): (l, ll, h) for m, n, l, ll, h in conn.execute(
        "SELECT match_id, model_name, ah_line, ah_log_loss, ah_hit FROM predictions")}
    assert got[("m1", "market_implied")] == (-0.5, pytest.approx(-log(0.55), abs=1e-6), 1.0)
    assert got[("m1", "dc_xg")] == (-0.5, pytest.approx(-log(0.4), abs=1e-6), 0.0)   # 选了客队
    assert got[("m1", "market_avg")] == (None, None, None)                          # 没有亚盘概率
    assert got[("m1", "lineup_t1")][0] == -0.75                                      # 临场档用临场线
    assert got[("m2", "dc_xg")] == (None, None, None)                                # 该场没有市场线

    rep = live_report(conn).set_index("model_name")
    assert rep.loc["dc_xg", "ah_n"] == 1 and rep.loc["dc_xg", "ah_hit"] == 0.0
    assert {"ah_n", "ah_ll", "ah_hit"} <= set(rep.columns)


def test_ah_backfill_for_rows_scored_before(conn):
    _match(conn, "m1", 1, 0)
    save_prediction(conn, "m1", "market_implied", "1", "1", 0.5, 0.3, 0.2,
                    {**_ah_extra(-1.0, [0.3, 0, 0.25, 0, 0.45]), "odds": {"ah_line": -1.0}})
    score_predictions(conn)
    conn.execute("UPDATE predictions SET ah_line=NULL, ah_log_loss=NULL, ah_hit=NULL")  # 模拟 1.6.0 之前
    assert score_predictions(conn) == 0                 # 不重复计 1X2 评分，只补亚盘
    row = conn.execute("SELECT ah_line, ah_log_loss, ah_hit FROM predictions").fetchone()
    assert row[0] == -1.0 and row[1] == pytest.approx(-log(0.25), abs=1e-6) and row[2] is None


def test_scored_first_keeps_earliest(conn):
    _match(conn, "m1", 0, 1)
    save_prediction(conn, "m1", "x", "1", "1", 0.2, 0.2, 0.6)   # 首条：客胜命中
    save_prediction(conn, "m1", "x", "1", "1", 0.6, 0.2, 0.2)   # 后补的不算
    score_predictions(conn)
    df = _scored_first(conn)
    assert len(df) == 1
    assert df.iloc[0]["p_away_win"] == pytest.approx(0.6)
    assert df.iloc[0]["hit"] == 1.0


def test_no_archive_or_score_after_kickoff(conn):
    """开球后不存档；旧库里开球后才存的行（generated_at ≥ kickoff_utc）不进成绩。"""
    _match(conn, "m1", 0, 1)
    ko = {"kickoff_utc": "2025-09-01T14:00:00+00:00"}
    late = datetime(2025, 9, 1, 14, 5, tzinfo=timezone.utc)
    assert save_prediction(conn, "m1", "x", "1", "1", 0.2, 0.2, 0.6, ko, at=late) is None
    assert not has_prediction(conn, "m1", "x", "1")
    early = datetime(2025, 9, 1, 13, 0, tzinfo=timezone.utc)
    assert save_prediction(conn, "m1", "x", "1", "1", 0.2, 0.2, 0.6, ko, at=early)
    conn.execute("""INSERT INTO predictions (pred_id, match_id, model_name, model_ver, feature_ver,
                    layer_ver, p_home_win, p_draw, p_away_win, extra_markets, generated_at)
                    VALUES ('old','m1','y','1','1','1',0.2,0.2,0.6,?,?)""",
                 (json.dumps(ko), late.isoformat()))   # 修复前留下的开球后存档
    score_predictions(conn)
    assert set(_scored_first(conn)["model_name"]) == {"x"}


def test_paired_diff_and_se():
    import pandas as pd
    a = pd.DataFrame({"match_id": ["1", "2", "3", "9"], "log_loss": [1.0, 1.2, 0.8, 5.0]})
    b = pd.DataFrame({"match_id": ["1", "2", "3"], "log_loss": [1.1, 1.0, 1.0]})
    n, diff, se = _paired(a, b)   # 只配同场：9 号不计
    d = np.array([-0.1, 0.2, -0.2])
    assert n == 3
    assert diff == pytest.approx(d.mean())
    assert se == pytest.approx(d.std(ddof=1) / np.sqrt(3))


def _scored_set(conn, n, p_ch, p_pr):
    """n 场主胜；挑战者 / 主模型 / 市场 各自给出主胜概率。"""
    rng = np.random.default_rng(1)
    for i in range(n):
        mid = f"m{i}"
        _match(conn, mid, 1, 0)
        jitter = rng.uniform(-0.02, 0.02)
        for name, ver, p in (("dc_sot", "1.0.0", p_ch + jitter), ("dc_xg", "1.0.0", p_pr),
                             ("market_avg", "1.1.0", 0.5)):
            save_prediction(conn, mid, name, ver, "1", p, (1 - p) / 2, (1 - p) / 2)
    score_predictions(conn)


def test_live_report_columns_and_hit_rate(conn):
    _scored_set(conn, 20, 0.6, 0.5)
    rep = live_report(conn).set_index("model_name")
    assert {"matches", "log_loss", "brier", "hit_rate", "paired_n",
            "diff_vs_base", "se"} <= set(rep.columns)
    assert rep.loc["dc_sot", "hit_rate"] == 1.0
    assert rep.loc["dc_sot", "paired_n"] == 20
    assert rep.loc["dc_sot", "diff_vs_base"] < 0       # 主胜给得更高 → 优于市场
    assert rep.loc["market_avg", "diff_vs_base"] == pytest.approx(0.0)


def test_promotion_check_verdicts(conn):
    _scored_set(conn, 30, 0.6, 0.5)
    chk = promotion_check(conn, ("dc_xg", "1.0.0"), min_n=50).set_index("model_name")
    assert "market_avg" not in chk.index and "dc_xg" not in chk.index
    assert chk.loc["dc_sot", "verdict"].startswith("样本不足")

    chk = promotion_check(conn, ("dc_xg", "1.0.0"), min_n=30).set_index("model_name")
    assert chk.loc["dc_sot", "verdict"] == "可替换"

    # 反过来：主模型更好，挑战者不替换
    chk = promotion_check(conn, ("dc_sot", "1.0.0"), min_n=30).set_index("model_name")
    assert chk.loc["dc_xg", "verdict"] == "不替换"


def test_reports_empty_without_scores(conn):
    assert live_report(conn).empty
    assert promotion_check(conn, ("dc_xg", "1.0.0"), 1000).empty
    assert horizon_report(conn).empty


def test_horizon_report_pairs_t1_with_pre_match(conn):
    _scored_set(conn, 10, 0.6, 0.5)
    for i in range(6):                          # 临场档只覆盖其中 6 场，主胜概率更高
        save_prediction(conn, f"m{i}", "market_avg_t1", "1.1.0", "1", 0.7, 0.15, 0.15)
        save_prediction(conn, f"m{i}", "lineup_t1", "1.0.0", "1", 0.55, 0.25, 0.2)
        save_prediction(conn, f"m{i}", "lineup_base_t1", "1.0.0", "1", 0.5, 0.25, 0.25)
    save_prediction(conn, "m0", "orphan_t1", "1", "1", 0.5, 0.25, 0.25)   # 没有赛前档，不列出
    score_predictions(conn)

    hz = horizon_report(conn).set_index("model_name")
    assert set(hz.index) == {"market_avg_t1", "lineup_t1"}
    assert hz.loc["market_avg_t1", "base"] == "market_avg"
    assert hz.loc["lineup_t1", "base"] == "lineup_base_t1"
    assert hz.loc["market_avg_t1", "paired_n"] == 6
    assert hz.loc["market_avg_t1", "diff"] == pytest.approx(log(0.5) - log(0.7), abs=1e-6)
    # 临场档不参加主模型替换
    chk = promotion_check(conn, ("dc_xg", "1.0.0"), min_n=1)
    assert not chk["model_name"].str.endswith("_t1").any()


def test_horizon_report_pairs_t2_with_pre_match_and_t1(conn):
    _scored_set(conn, 10, 0.6, 0.5)
    for i in range(6):
        save_prediction(conn, f"m{i}", "market_avg_t1", "1.1.0", "1", 0.7, 0.15, 0.15)
    for i in range(4):                          # 第二临场档覆盖其中 4 场
        save_prediction(conn, f"m{i}", "market_avg_t2", "1.1.0", "1", 0.8, 0.1, 0.1)
    score_predictions(conn)

    hz = horizon_report(conn)
    t2 = hz[hz["model_name"] == "market_avg_t2"].set_index("base")
    assert set(t2.index) == {"market_avg", "market_avg_t1"}
    assert t2.loc["market_avg", "paired_n"] == 4
    assert t2.loc["market_avg_t1", "diff"] == pytest.approx(log(0.7) - log(0.8), abs=1e-6)
    chk = promotion_check(conn, ("dc_xg", "1.0.0"), min_n=1)
    assert not chk["model_name"].str.endswith("_t2").any()
    assert [horizon_of(n) for n in ("market_avg", "lineup_t1", "market_avg_t2")] == ["", "_t1", "_t2"]
