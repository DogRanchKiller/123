"""services/team_read：联赛代码、某队最近几场与下一场、阵容（没挂 fotmob 时 None）、评分行。"""
from datetime import datetime, timedelta

import pytest

from football_prediction import services, version
from football_prediction.data import fotmob
from football_prediction.review.store import score_predictions
from tests.test_report_live import _fixture


def test_league_code():
    assert services.league_code("E0") == "E0" and services.league_code(" 德甲 ") == "D1"
    with pytest.raises(ValueError, match="未知联赛"):
        services.league_code("XX")


def test_team_recent_and_next_fixture(league, tmp_path):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    rec = services.read_team_recent(conn, "E0", "A", n=3)
    assert len(rec) == 3 and all("A" in (m["home"], m["away"]) and m["score"] for m in rec)
    assert [m["match_date"] for m in rec] == sorted((m["match_date"] for m in rec), reverse=True)
    assert services.read_team_recent(conn, "D1", "A") == []

    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    nxt = services.read_next_fixture(conn, "E0", "F", now)
    assert (nxt["match_id"], nxt["home"], nxt["away"], nxt["league_name"]) == ("f1", "A", "F", "英超")
    assert services.read_next_fixture(conn, "E0", "F", now + timedelta(hours=6)) is None

    # 只有 FotMob 比分、football-data 还没到的场次也算最近一场
    assert services.read_lineups(conn, "f1") is None                      # 没挂 fotmob 库
    fotmob.attach(conn, str(tmp_path / "fm.db"))
    assert services.read_lineups(conn, "f1") is None                      # 挂了但没抓到
    conn.execute("INSERT INTO fm.fotmob_results VALUES ('f1','99',3,0,'2030-01-01T00:00:00+00:00','t')")
    top = services.read_team_recent(conn, "E0", "A", n=1)[0]
    assert top["match_id"] == "f1" and top["score"] == {"home": 3, "away": 0} and top["score_source"] == "fotmob"


def test_read_grading(league, tmp_path):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    assert services.read_grading(conn, "f1") == []
    services.predict_upcoming(conn, now)
    assert services.read_grading(conn, "f1") == []                        # 还没评分
    fotmob.attach(conn, str(tmp_path / "fm.db"))
    conn.execute("INSERT INTO fm.fotmob_results VALUES ('f1','99',0,2,'2030-01-01T00:00:00+00:00','t')")
    assert score_predictions(conn) > 0
    rows = services.read_grading(conn, "f1")
    assert rows[0]["model_name"] == version.PRIMARY_MODEL[0]               # 按 GRADED_MODELS 的顺序
    assert {r["model_name"] for r in rows} <= set(services.GRADED_MODELS)
    assert all(r["result_src"] == "fotmob" and r["actual_outcome"] == "away_win" and r["scored_at"]
               for r in rows)
    everything = services.read_grading(conn, "f1", None)
    assert len(everything) >= len(rows) and len({(r["model_name"], r["model_ver"]) for r in everything}) == len(everything)
    assert [r["model_name"] for r in services.read_grading(conn, "f1", ("market_avg",))] == ["market_avg"]
