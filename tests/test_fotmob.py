"""FotMob 解析与入库（离线：tests/fotmob_fixture.json 是真实页面裁剪后的 __NEXT_DATA__ 片段）。"""
import json
import os
from datetime import date

import pytest

from football_prediction.data import fotmob
from football_prediction.data.fotmob_parse import (
    compact_match, league_matches, next_data, pair_matches, season_param, team_map)

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fotmob_fixture.json"), encoding="utf-8"))


def test_next_data_and_season_param():
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props": {"a": 1}}</script></html>'
    assert next_data(html) == {"props": {"a": 1}}
    assert next_data("<html></html>") is None
    assert season_param("2425") == "2024/2025"


def test_league_matches():
    ms = league_matches(FX["league"])
    assert len(ms) == 3
    m = ms[0]
    assert m["fotmob_id"] == "5795363" and m["home"] == "Arsenal"
    assert "#" not in m["page_url"] and m["finished"] and not m["cancelled"]


def test_compact_finished():
    r = compact_match(FX["finished"])
    assert r["finished"] and r["lineup_type"] == "standard" and r["team_xg"] == [0.5, 0.55]
    roles = {(p["side"], p["role"]) for p in r["lineup"]}
    assert ("home", "starter") in roles and ("away", "sub") in roles and ("home", "unavailable") in roles
    subbed = {p["name"]: p["sub_minute"] for p in r["lineup"]}
    assert subbed["Bobby Thomas"] == 60 and subbed["Stephen Mfuni"] == 60     # 换下 / 换上
    iwobi = next(p for p in r["players"] if p["name"] == "Alex Iwobi")
    assert iwobi["side"] == "away" and iwobi["minutes"] == 74 and iwobi["xg"] == pytest.approx(0.13)
    cairney = next(p for p in r["players"] if p["name"] == "Tom Cairney")
    assert cairney["xg"] == 0.0 and cairney["xa"] == 0.0                    # 无射门：xG 记 0
    assert all(s["side"] in ("home", "away") and s["xg"] is not None for s in r["shots"])
    inj = next(p for p in r["lineup"] if p["role"] == "unavailable")
    assert json.loads(inj["detail"])["type"] == "injury"


def test_compact_upcoming_predicted():
    r = compact_match(FX["upcoming"])
    assert not r["finished"] and r["lineup_type"] == "predicted"
    assert r["players"] == [] and r["shots"] == [] and r["team_xg"] is None
    assert {p["role"] for p in r["lineup"]} == {"starter", "unavailable"}


def test_team_map_and_pairing():
    fm = [{"fotmob_id": "1", "home": "Nottingham Forest", "away": "Wolverhampton Wanderers",
           "kickoff_utc": "2025-09-01T14:00:00Z"},
          {"fotmob_id": "2", "home": "Real Madrid", "away": "Atlético Madrid",
           "kickoff_utc": "2025-09-02T19:00:00Z"},
          {"fotmob_id": "3", "home": "Atlético Madrid", "away": "Real Madrid",
           "kickoff_utc": "2025-12-02T19:00:00Z"}]
    ours = [{"match_id": "a", "match_date": "2025-09-01", "home_team": "Nott'm Forest", "away_team": "Wolverhampton"},
            {"match_id": "b", "match_date": "2025-09-03", "home_team": "Real Madrid", "away_team": "Ath Madrid"},
            {"match_id": "c", "match_date": "2025-12-09", "home_team": "Ath Madrid", "away_team": "Real Madrid"}]
    tm = team_map([n for f in fm for n in (f["home"], f["away"])],
                  [n for o in ours for n in (o["home_team"], o["away_team"])])
    assert tm["Atlético Madrid"] == "Ath Madrid" and tm["Real Madrid"] == "Real Madrid"
    p = pair_matches(fm, ours)
    assert p["1"]["match_id"] == "a" and p["2"]["match_id"] == "b"
    assert "3" not in p                                                       # 日期差 7 天，不配


def test_save_match_and_backfill(league):
    conn, _ = league
    fotmob.init_fotmob(conn)
    mid = conn.execute("SELECT match_id FROM matches ORDER BY match_date LIMIT 1").fetchone()[0]
    rec = compact_match(FX["finished"])
    fotmob.save_match(conn, mid, "/matches/x", rec, "2026-01-01T00:00:00+00:00")
    fotmob.save_match(conn, mid, "/matches/x", rec, "2026-01-01T00:00:00+00:00")   # 重跑不重复
    assert conn.execute("SELECT COUNT(*) FROM player_match WHERE match_id=?", (mid,)).fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM lineups WHERE match_id=?", (mid,)).fetchone()[0] == len(rec["lineup"])
    assert conn.execute("SELECT COUNT(*) FROM fotmob_shots WHERE match_id=?", (mid,)).fetchone()[0] == 5
    # understat 已有的不覆盖；缺的才补
    conn.execute("DELETE FROM match_xg WHERE match_id=?", (mid,))
    assert fotmob.backfill_xg(conn, date(2100, 1, 1)) == 1
    row = conn.execute("SELECT home_xg, away_xg, us_match_id FROM match_xg WHERE match_id=?", (mid,)).fetchone()
    assert row == (0.5, 0.55, "fotmob:5795488")
    assert fotmob.backfill_xg(conn, date(2100, 1, 1)) == 0


def test_backfill_waits_for_understat(league):
    conn, _ = league
    fotmob.init_fotmob(conn)
    mid, d = conn.execute("SELECT match_id, match_date FROM matches ORDER BY match_date DESC LIMIT 1").fetchone()
    fotmob.save_match(conn, mid, "/m", compact_match(FX["finished"]), "t")
    conn.execute("DELETE FROM match_xg WHERE match_id=?", (mid,))
    assert fotmob.backfill_xg(conn, date.fromisoformat(d)) == 0               # 刚完赛，先等 understat


def test_upcoming_lineup_batches(conn):
    fotmob.init_fotmob(conn)
    rec = compact_match(FX["upcoming"])
    for t in ("2026-01-01T10:00:00+00:00", "2026-01-01T12:00:00+00:00"):
        fotmob.save_match(conn, "m1", "/m", rec, t)
    assert conn.execute("SELECT COUNT(DISTINCT fetched_at) FROM lineups").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM player_match").fetchone()[0] == 0


def test_attach_and_reload_pre(league, tmp_path, monkeypatch):
    conn, _ = league
    monkeypatch.setattr(fotmob, "CACHE_DIR", str(tmp_path / "cache"))
    fotmob.attach(conn, str(tmp_path / "fm.db"))
    fotmob.attach(conn, str(tmp_path / "fm.db"))                              # 重复挂载无害
    assert conn.execute("SELECT COUNT(*) FROM fm.lineups").fetchone()[0] == 0
    rec = compact_match(FX["upcoming"])
    fotmob._save_pre(rec, "m1", "/m", "2026-01-01T10:00:00+00:00")
    assert fotmob.reload_pre(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM fm.lineups WHERE match_id='m1'").fetchone()[0] == len(rec["lineup"])
    assert conn.execute("SELECT COUNT(*) FROM main.sqlite_master WHERE name='lineups'").fetchone()[0] == 0


def test_fetch_match_rejects_wrong_page(tmp_path, monkeypatch):
    monkeypatch.setattr(fotmob, "CACHE_DIR", str(tmp_path))
    page = lambda pp: ('<script id="__NEXT_DATA__" type="application/json">'
                       + json.dumps({"props": {"pageProps": pp}}) + "</script>")
    seen = []
    monkeypatch.setattr(fotmob, "_get", lambda path: seen.append(path) or page(FX["finished"]))
    assert fotmob.fetch_match("999") is None                                  # 页面是另一场
    rec = fotmob.fetch_match("5795488")
    assert seen == ["/match/999", "/match/5795488"] and rec["finished"]
    assert fotmob.fetch_match("5795488")["fotmob_id"] == "5795488" and len(seen) == 2   # 读缓存


def test_get_refuses_api():
    with pytest.raises(ValueError):
        fotmob._get("/api/matchDetails?matchId=1")
