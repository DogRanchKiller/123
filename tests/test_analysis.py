"""output 1.5.0 亚盘为主：数字盘口文字、选择方、盘口与水位变动、同线分歧、±4 线、报告列。"""
import pytest

from football_prediction.model_market.implied import dc_matrix
from football_prediction.output.analysis import (AH_TIERS, ah_pick_text, ah_text, ah_tier, ah_trail,
                                                 analyse, asian, _shift)
from football_prediction.output.derive import AH_LINES, derive_markets


def test_ah_text_quarter_line():
    o = {"win": 0.36, "half_win": 0.18, "push": 0.0, "half_lose": 0.0, "lose": 0.46}
    assert ah_text(-0.75, o) == "主-0.75 赢盘54%（赢36%、赢半18%），输46%"


def test_ah_text_whole_line_push_and_zero_sign():
    o = {"win": 0.40, "half_win": 0.0, "push": 0.25, "half_lose": 0.0, "lose": 0.35}
    assert ah_text(-0.0, o) == "主+0.00 赢盘40%，走25%，输35%"
    o = {"win": 0.0, "half_win": 0.30, "push": 0.0, "half_lose": 0.0, "lose": 0.70}
    assert ah_text(0.25, o) == "主+0.25 赢盘30%（赢半），输70%"


def test_ah_pick_text_side():
    assert ah_pick_text({"line": -0.75, "side": "主", "p_cover": 0.52}) == "主-0.75 52%"
    assert ah_pick_text({"line": -0.75, "side": "客", "p_cover": 0.55}) == "客+0.75 55%"


def test_ah_tier_bounds():
    assert ah_tier(0.5)[0] == AH_TIERS[-1][1]
    assert ah_tier(0.99)[0] == AH_TIERS[0][1]


@pytest.mark.parametrize("l0,l1,want", [
    (-0.5, -0.75, "升盘（主队让更多）"),
    (-0.75, -0.5, "降盘（主队让更少）"),
    (0.5, 0.75, "升盘（客队让更多）"),
    (0.0, -0.25, "升盘（主队让更多）"),
    (0.0, 0.25, "升盘（客队让更多）"),
    (-0.25, 0.25, "让球方换边（客队让）"),
    (-0.5, -0.5, ""),
])
def test_shift(l0, l1, want):
    assert _shift(l0, l1) == want


def test_ah_trail():
    op = {"ah_line": -0.5, "avg_ahh": 1.95, "avg_aha": 1.90}
    last = {"ah_line": -0.75, "avg_ahh": 2.02, "avg_aha": 1.84}
    s = ah_trail(op, last, last)                     # 最新快照与定价相同 → 合并
    assert s == "初盘 主-0.50（1.95/1.90） → 最新快照 主-0.75（2.02/1.84）；升盘（主队让更多）"
    water = {"ah_line": -0.5, "avg_ahh": 1.85, "avg_aha": 2.00}
    assert ah_trail(op, None, water).endswith("盘口未变，只有水位变化")
    assert ah_trail(op, op, op) == "" and ah_trail(None, None, op) == ""


def test_asian_market_line_and_divergence():
    m = dc_matrix(2.0, 0.8)
    od = {"ah_line": -1.0, "ah_h": 1.9, "ah_a": 1.95}
    ah, hints = asian(m, od, dc_matrix(1.2, 1.2), True)
    assert ah["line"] == -1.0 and ah["line_src"] == "市场线" and ah["tier"] != "-"
    assert ah["side"] == ("主" if ah["fair"] >= 0.5 else "客") and ah["p_cover"] >= 0.5
    assert ah["market_fair"] == pytest.approx(1 / 1.9 / (1 / 1.9 + 1 / 1.95))
    assert hints and "dc_xg 在主-1.00" in hints[0]
    _, quiet = asian(m, od, dc_matrix(1.2, 1.2), False)   # 比分矩阵不是市场的，不提示
    assert quiet == []


def test_asian_fair_line_without_market():
    m = dc_matrix(1.5, 1.0)
    ah, _ = asian(m, {}, m, False)
    assert ah["line"] == derive_markets(m)["ah_fair_line"] and ah["line_src"].startswith("公平线")
    assert ah["tier"] == "-" and ah["hit"] is None and ah["market_fair"] is None


def test_ah_lines_cover_four_goals():
    assert AH_LINES[0] == -4.0 and AH_LINES[-1] == 4.0 and len(AH_LINES) == 33
    mk = derive_markets(dc_matrix(3.8, 0.3))
    assert "ah_-4.00" in mk and "ah_+4.00" in mk
    assert mk["ah_fair_line"] <= -2.5                   # 大热门的公平线超过 2.5 球


def test_analyse_ah_move_uses_open_snapshot():
    xg = dc_matrix(1.4, 1.1)
    row = dict(avg_h=2.0, avg_d=3.5, avg_a=3.9, avg_over25=1.9, avg_under25=1.95,
               ah_line=-0.5, avg_ahh=1.92, avg_aha=1.98)
    op = dict(row, ah_line=-0.25, avg_ahh=1.90, avg_aha=2.00)
    a = analyse(row, xg, -0.05, {}, last_row=row, ah_open=op)
    assert a["ah"]["line"] == -0.5 and a["ah_move"].startswith("初盘 主-0.25")
    assert "升盘（主队让更多）" in a["ah_move"]
