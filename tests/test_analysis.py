"""output 1.5.0 亚盘为主：数字盘口文字、选择方、盘口与水位变动、同线分歧、±4 线、报告列。
output 1.6.0：亚盘稳妥线、重点标记。
output 2.0.0：主模型 dc_dyn 的矩阵给概率、亚盘与信心档；市场只作对照与分歧提示。"""
import pytest

from football_prediction.model_market.implied import dc_matrix
from football_prediction.output.analysis import (AH_TIERS, PRIMARY_AH_TIERS, PRIMARY_NAME, PRIMARY_TIERS,
                                                 SAFE_TARGET, ah_pick_text, ah_text, ah_tier, ah_trail, analyse,
                                                 asian, confidence_tier, safe_line, safe_text, _shift)
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
    assert ah_tier(0.5, AH_TIERS)[0] == AH_TIERS[-1][1]       # 旧市场存档的三档
    assert ah_tier(0.99, AH_TIERS)[0] == AH_TIERS[0][1]
    assert ah_tier(0.5) == ah_tier(0.99) == (PRIMARY_AH_TIERS[0][1], PRIMARY_AH_TIERS[0][2])   # dc_dyn 只一档


def test_primary_tiers_bounds():
    assert confidence_tier(0.34)[0] == "低" and confidence_tier(0.50)[0] == "中"
    assert confidence_tier(0.61) == tuple(PRIMARY_TIERS[0][1:])


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
    m = dc_matrix(2.0, 0.8)                                # 主模型：主队明显强
    od = {"ah_line": -1.0, "ah_h": 1.9, "ah_a": 1.95}
    ah, hints = asian(m, od, dc_matrix(1.2, 1.2))          # 市场隐含：接近五五
    assert ah["line"] == -1.0 and ah["line_src"] == "市场线" and ah["tier"] != "-"
    assert ah["side"] == ("主" if ah["fair"] >= 0.5 else "客") and ah["p_cover"] >= 0.5
    assert ah["self_fair"] == ah["fair"]
    assert ah["market_fair"] == pytest.approx(1 / 1.9 / (1 / 1.9 + 1 / 1.95))
    assert ah["implied_fair"] < ah["fair"]
    assert hints and hints[0].startswith("市场在主-1.00") and "dc_dyn" in hints[0] and "仅提示" in hints[0]
    _, quiet = asian(m, od, m)                             # 市场隐含与主模型一致：不提示
    assert quiet == []
    ah2, h2 = asian(m, dict(od, ah_h=2.6, ah_a=1.5))      # 没有市场隐含：用水位去水比
    assert ah2["implied_fair"] is None and h2 and f"{ah2['market_fair']:.0%}" in h2[0]


def test_asian_fair_line_without_market():
    m = dc_matrix(1.5, 1.0)
    ah, _ = asian(m, {})
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


def test_safe_line_steps_toward_pick():
    fair = {-1.0: 0.50, -0.75: 0.56, -0.5: 0.62, -0.25: 0.66, 0.0: 0.72}.get   # 主队各线赢盘
    assert safe_line(fair, -1.0, "主") == (-0.25, 0.66)
    assert safe_line(fair, -1.0, "主", target=0.5) == (-1.0, 0.50)               # 本线已够，不退
    away = {-1.0: 0.40, -1.25: 0.37, -1.5: 0.30}.get                            # 客队方向往更深的主让线退
    assert safe_line(away, -1.0, "客") == (-1.5, 0.70)
    assert safe_line(fair, -0.5, "客") is None                                  # 缺线
    assert safe_text({"side": "客", "safe_line": -1.5, "safe_cover": 0.70}) == "客+1.50 70%"
    assert safe_text({"side": "主", "safe_line": None, "safe_cover": None}) == ""


def test_asian_safe_line_from_matrix():
    ah, _ = asian(dc_matrix(1.6, 1.1), {"ah_line": -0.5, "ah_h": 1.95, "ah_a": 1.92})
    assert ah["safe_cover"] >= SAFE_TARGET
    side = 1 if ah["side"] == "主" else -1
    assert (ah["safe_line"] - ah["line"]) * side > 0                            # 市场线赢盘不到 65%，要退


def test_analyse_highlight_follows_primary_tier():
    hot = dict(avg_h=1.35, avg_d=5.0, avg_a=8.5, avg_over25=1.7, avg_under25=2.15,
               ah_line=-1.5, avg_ahh=1.92, avg_aha=1.98)
    big, even = dc_matrix(3.0, 0.4), dc_matrix(1.3, 1.2)
    a = analyse(hot, even, -0.05)                       # 市场一边倒、dc_dyn 接近五五：不标重点
    assert a["tier"] != "高" and a["highlight"] is False
    assert a["hints"] and any(h.startswith("市场与 dc_dyn 分歧") for h in a["hints"])
    for row in (hot, None):                             # dc_dyn 档高：有没有赔率都标重点
        a = analyse(row, big, -0.05)
        assert a["tier"] == "高" and a["highlight"] is True
        assert a["hit1"] == PRIMARY_TIERS[0][2] and a["est1"] == pytest.approx(max(a["p1x2"]))


def test_analyse_probabilities_are_primary_matrix():
    m = dc_matrix(1.6, 1.0)
    row = dict(avg_h=1.8, avg_d=3.6, avg_a=4.5, avg_over25=1.8, avg_under25=2.0,
               ah_line=-0.75, avg_ahh=1.95, avg_aha=1.92)
    a = analyse(row, m, -0.05)
    mk = derive_markets(m)
    assert a["p_src"] == a["source"] == PRIMARY_NAME
    assert a["p1x2"] == pytest.approx([mk["home_win"], mk["draw"], mk["away_win"]], abs=1e-3)   # derive 四舍五入
    inv = [1 / 1.8, 1 / 3.6, 1 / 4.5]
    assert a["market"] == pytest.approx([x / sum(inv) for x in inv])
    assert a["fit"] is not None and a["ref_markets"] is not None
    assert a["ah"]["implied_fair"] is not None and a["ah"]["tier"] == PRIMARY_AH_TIERS[0][1]
    b = analyse(None, m, -0.05)                         # 无赔率：概率不变，只少了市场对照
    assert b["p1x2"] == pytest.approx(a["p1x2"]) and b["market"] is None and b["fit"] is None
    assert any("缺胜平负赔率" in r for r in b["risks"])
