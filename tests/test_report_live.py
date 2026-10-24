"""预测报告与实盘循环：信心档边界、双选标签、只报未开赛、重跑不重复保存。"""
from datetime import datetime, timedelta, timezone

import pytest

from football_prediction import version
from football_prediction.output.report import confidence_tier, _double_label, build_report
from football_prediction.review.store import save_prediction


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


def _fixture(conn, mid, kickoff, home="A", away="F"):
    conn.execute(
        """INSERT INTO fixtures (match_id, league, season, match_date, kickoff_utc,
               home_team, away_team, avg_h, avg_d, avg_a, fetched_at, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, "E0", "2425", kickoff[:10], kickoff, home, away, 1.8, 3.6, 4.5, "now", "t"))
    conn.commit()


def test_build_report_first_prediction_and_future_only(conn):
    now = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    _fixture(conn, "past", (now - timedelta(hours=1)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=2)).isoformat(), "C", "D")
    _fixture(conn, "soon", (now + timedelta(hours=3)).isoformat())
    extra = {"top5_scores": [{"score": "1-0", "prob": 0.12}, {"score": "2-0", "prob": 0.1},
                             {"score": "1-1", "prob": 0.09}, {"score": "0-0", "prob": 0.08}],
             "over_2.5": 0.55}
    for mid in ("past", "late", "soon"):
        save_prediction(conn, mid, "dc_xg", "1.0.0", "1", 0.62, 0.22, 0.16, extra)
    save_prediction(conn, "soon", "dc_xg", "1.0.0", "1", 0.20, 0.20, 0.60)   # 后补，不得采用
    save_prediction(conn, "soon", "dixon_coles", "1.3.0", "1", 0.30, 0.30, 0.40)

    df = build_report(conn, {"E0": "英超"}, "dc_xg", "1.0.0", now)
    assert list(df["主队"]) == ["A", "C"]                 # 已开球的剔除，按开球排序
    r = df.iloc[0]
    assert (r["主胜"], r["倾向"], r["信心"]) == ("62%", "主胜", "高")
    assert r["最可能比分"] == "1-0(12%) 2-0(10%) 1-1(9%)"
    assert r["大2.5球"] == "55%"
    assert r["开球(北京)"] == "01-01 23:00"               # UTC+8
    assert r["模型"] == "dc_xg 1.0.0"


def test_build_report_empty(conn):
    assert build_report(conn, {}, "dc_xg", "1.0.0", datetime.now(timezone.utc)).empty


def test_predict_upcoming_saves_once(league, monkeypatch):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _fixture(conn, "f0", (now - timedelta(hours=5)).isoformat(), "B", "E")   # 已开球

    first = live._predict_upcoming(conn, now)
    assert first == 5          # DC / 射正 / xG / Elo / 市场
    assert live._predict_upcoming(conn, now) == 0
    names = {r[0] for r in conn.execute("SELECT DISTINCT model_name FROM predictions")}
    assert version.PRIMARY_MODEL[0] in names
    assert conn.execute("SELECT COUNT(*) FROM predictions WHERE match_id='f0'").fetchone()[0] == 0

    df = build_report(conn, live.LEAGUES, version.PRIMARY_MODEL[0],
                      version.get(version.PRIMARY_MODEL[1]), now)
    assert len(df) == 1 and df.iloc[0]["最可能比分"] and df.iloc[0]["大2.5球"]
