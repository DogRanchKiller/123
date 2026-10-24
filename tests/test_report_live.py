"""预测报告与实盘循环：信心档边界、双选标签、只报未开赛、重跑不重复保存。"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from football_prediction import version
from football_prediction.output.report import confidence_tier, _double_label, build_report


@pytest.mark.parametrize("p,tier", [(0.80, "高"), (0.60, "高"), (0.5999, "中"),
                                    (0.45, "中"), (0.4499, "低"), (0.34, "低")])
def test_confidence_tier_boundaries(p, tier):
    assert confidence_tier(p)[0] == tier


def test_confidence_tiers_monotonic():
    hits = [confidence_tier(p)[1:] for p in (0.7, 0.5, 0.4)]
    assert hits[0] > hits[1] > hits[2]
    assert all(h2 > h1 for h1, h2 in hits)   # 双选命中率必高于首选


@pytest.mark.parametrize("top2,label", [
    (["home_win", "draw"], "主胜或平"), (["draw", "home_win"], "主胜或平"),
    (["away_win", "draw"], "平或客胜"), (["away_win", "home_win"], "不平局"),
])
def test_double_label(top2, label):
    assert _double_label(top2) == label


ODDS = dict(avg_h=1.5, avg_d=4.0, avg_a=5.5, avg_over25=1.8, avg_under25=2.0,
            ah_line=-1.0, avg_ahh=1.95, avg_aha=1.95)


def _fixture(conn, mid, kickoff, home="A", away="F", **odds):
    o = {**ODDS, **odds}
    cols = list(o)
    conn.execute(
        f"""INSERT INTO fixtures (match_id, league, season, match_date, kickoff_utc,
               home_team, away_team, {','.join(cols)}, fetched_at, layer_ver)
           VALUES ({','.join('?' * (9 + len(cols)))})""",
        (mid, "E0", "2425", kickoff[:10], kickoff, home, away, *o.values(), "now", "t"))
    conn.commit()


def test_build_report_market_based_and_future_only(league):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "past", (now - timedelta(hours=1)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=2)).isoformat(), "C", "D")
    _fixture(conn, "soon", (now + timedelta(hours=3)).isoformat())
    _fixture(conn, "noodds", (now + timedelta(days=3)).isoformat(), "B", "E",
             avg_h=None, avg_d=None, avg_a=None, avg_over25=None, avg_under25=None, ah_line=None)

    df = build_report(conn, {"E0": "英超"}, now)
    assert list(df["主队"]) == ["A", "C", "B"]            # 已开球的剔除，按开球排序
    r = df.iloc[0]
    # 胜平负 = 市场去水：1/1.6 : 1/4 : 1/5.5
    inv = [1 / 1.5, 1 / 4.0, 1 / 5.5]
    assert r["主胜"] == f"{inv[0] / sum(inv):.0%}"
    assert (r["概率来源"], r["倾向"], r["信心"], r["比分来源"]) == ("市场", "主胜", "高", "市场隐含")
    assert r["历史命中(首选/双选)"] == "73%/90%"
    assert r["最可能比分"] and r["大2.5球"] and r["亚盘"].startswith("主-1.00")
    assert "dc_xg" in r["自研 主/平/客"] and "blend" in r["自研 主/平/客"]
    assert r["开球(北京)"] == (now + timedelta(hours=3)).astimezone(
        ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
    n = df.iloc[2]                                        # 无赔率：回退自研，并提示
    assert n["概率来源"] == "blend" and n["比分来源"].startswith("dc_xg")
    assert "缺胜平负赔率" in n["提示"]


def test_build_report_empty(conn):
    assert build_report(conn, {}, datetime.now(timezone.utc)).empty


def test_predict_upcoming_saves_once(league, monkeypatch):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _fixture(conn, "f0", (now - timedelta(hours=5)).isoformat(), "B", "E")   # 已开球

    first = live._predict_upcoming(conn, now)
    assert first == 7          # DC / 射正 / xG / Elo / blend / 市场 / 市场隐含
    assert live._predict_upcoming(conn, now) == 0
    names = {r[0] for r in conn.execute("SELECT DISTINCT model_name FROM predictions")}
    assert version.PRIMARY_MODEL[0] in names and "blend_xg_elo" in names
    assert conn.execute("SELECT COUNT(*) FROM predictions WHERE match_id='f0'").fetchone()[0] == 0
    ex = json.loads(conn.execute("SELECT extra_markets FROM predictions WHERE match_id='f1' "
                                 "AND model_name='market_implied'").fetchone()[0])
    assert len(ex["score_matrix"]) == 81 and abs(sum(ex["score_matrix"]) - 1) < 1e-3

    df = build_report(conn, live.LEAGUES, now)
    assert len(df) == 1 and df.iloc[0]["最可能比分"] and df.iloc[0]["大2.5球"]


def test_predict_upcoming_no_ou_skips_implied(league):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat(), avg_over25=None, avg_under25=None)
    assert live._predict_upcoming(conn, now) == 6
    assert not conn.execute("SELECT 1 FROM predictions WHERE model_name='market_implied'").fetchone()
