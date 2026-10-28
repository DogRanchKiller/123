"""成绩单的同档基准（live_report.base）与对收盘参照 closing_report（review 1.9.0）。"""
from math import log

import pytest

from football_prediction.review.scorecard import CLOSING_NAME, closing_report, live_report, promotion_check
from football_prediction.review.store import save_prediction, score_predictions
from tests.test_review import _scored_set


def _close(conn, mid, h, d, a):
    conn.execute("INSERT INTO match_odds (match_id, avgc_h, avgc_d, avgc_a, fetched_at, layer_ver) "
                 "VALUES (?,?,?,?,'t','t')", (mid, h, d, a))


def test_live_report_pairs_each_horizon_with_its_own_market(conn):
    _scored_set(conn, 10, 0.6, 0.5)                       # 赛前 market_avg 主胜 0.5
    for i in range(6):
        save_prediction(conn, f"m{i}", "market_avg_t1", "1.1.0", "1", 0.7, 0.15, 0.15)
        save_prediction(conn, f"m{i}", "market_implied_t1", "1.0.0", "1", 0.8, 0.1, 0.1)
    save_prediction(conn, "m0", "market_implied_t2", "1.0.0", "1", 0.8, 0.1, 0.1)   # 没有 market_avg_t2
    score_predictions(conn)

    rep = live_report(conn).set_index("model_name")
    assert rep.loc["dc_sot", "base"] == "market_avg"
    assert rep.loc["market_implied_t1", "base"] == "market_avg_t1"
    assert rep.loc["market_implied_t1", "paired_n"] == 6
    assert rep.loc["market_implied_t1", "diff_vs_base"] == pytest.approx(log(0.7) - log(0.8), abs=1e-6)
    assert rep.loc["market_avg_t1", "diff_vs_base"] == pytest.approx(0.0)       # 同档基准自身
    assert rep.loc["market_implied_t2", "base"] == "market_avg_t2"
    assert rep.loc["market_implied_t2", "paired_n"] == 0                        # 同档没有基准时不配对


def test_closing_report_pairs_with_devigged_close(conn):
    _scored_set(conn, 10, 0.6, 0.5)                       # 10 场主胜
    for i in range(8):                                    # 8 场有收盘：去水后主胜 0.55
        _close(conn, f"m{i}", 1 / 0.55, 1 / 0.25, 1 / 0.20)
    _close(conn, "m8", None, 3.2, 4.0)                    # 缺一项不计
    before = conn.total_changes
    rep = closing_report(conn).set_index("model_name")
    assert conn.total_changes == before                   # 只读
    assert rep.loc[CLOSING_NAME, "paired_n"] == 8
    assert rep.loc[CLOSING_NAME, "log_loss"] == pytest.approx(-log(0.55), abs=1e-6)
    assert rep.loc["market_avg", "paired_n"] == 8
    assert rep.loc["market_avg", "diff_vs_close"] == pytest.approx(log(0.55) - log(0.5), abs=1e-6)
    assert rep.loc["market_avg", "log_loss"] == pytest.approx(-log(0.5), abs=1e-6)   # 只算配对的场次
    assert rep["diff_vs_close"].is_monotonic_increasing                # 按差值升序
    # 收盘参照不进替换检查
    assert CLOSING_NAME not in set(promotion_check(conn, ("dc_xg", "1.0.0"), min_n=1)["model_name"])


def test_closing_report_without_close_odds(conn):
    assert closing_report(conn).empty                     # 没有已评分场次
    _scored_set(conn, 5, 0.6, 0.5)
    assert closing_report(conn).empty                     # 有评分、没有收盘赔率
