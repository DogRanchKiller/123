"""data/oddsportal.py：盘口键解析、逐家赔率解析、队名配对、抓取流程（假 runner）与多家共识。"""
import sqlite3
from datetime import datetime, timezone

import pytest

from football_prediction.data import loader, oddsportal as op


def _book(name, **kw):
    hist = kw.pop("hist", None)
    b = {"bookmaker_name": name, "period": "FullTime", **kw}
    if hist is not None:
        b["odds_history_data"] = [{"odds_history": [], "opening_odds":
                                   {"timestamp": ts, "odds": o} if o else None} for o, ts in hist]
    return b


REC = {
    "match_link": "https://www.oddsportal.com/football/h2h/brighton-2XrRecc3/liverpool-lId4TMwf/#t8xcEZ7K",
    "home_team": "Liverpool", "away_team": "Brighton", "match_date": "2026-10-25 14:00:00 UTC",
    "1x2_market": [
        _book("A", **{"1": "2.10", "X": "3.80", "2": "3.20"},
              hist=[(1.83, "2026-10-10T16:22:00"), (3.75, "2026-10-10T16:22:00"), (3.75, "2026-10-10T16:22:00")]),
        _book("B", **{"1": "2.00", "X": "3.90", "2": "3.40"},
              hist=[(1.90, "2026-10-11T08:00:00"), (3.60, "2026-10-11T08:00:00"), (3.80, "2026-10-11T08:00:00")]),
        _book("C", **{"1": "2.20", "X": "3.70", "2": "3.00"}),
    ],
    "over_under_2_5_market": [_book("A", odds_over="1.53", odds_under="2.50"),
                              _book("B", odds_over="1.55", odds_under="2.40")],
    "asian_handicap_-0_25_market": [_book("A", team1_handicap="1.83", team2_handicap="2.03"),
                                    _book("B", team1_handicap="1.80", team2_handicap="1.90")],
    "asian_handicap_-0_5_market": [_book("A", team1_handicap="2.05", team2_handicap="1.75")],
    "asian_handicap_-2_5_market": [_book("A", team1_handicap="7.00", team2_handicap="1.10",
                                         blocked_outcomes=["team1_handicap", "team2_handicap"])],
    "asian_handicap_+3_5_market": [_book("A", team1_handicap="-", team2_handicap="31.00")],
}


@pytest.mark.parametrize("key,exp", [
    ("1x2_market", ("1x2", 0.0)), ("over_under_2_5_market", ("ou", 2.5)),
    ("asian_handicap_-0_25_market", ("ah", -0.25)), ("asian_handicap_+1_market", ("ah", 1.0)),
    ("asian_handicap_0_market", ("ah", 0.0)), ("asian_handicap_-1_75_market", ("ah", -1.75)),
    ("btts_market", None), ("venue", None),
])
def test_market_of(key, exp):
    assert op.market_of(key) == exp


@pytest.mark.parametrize("line,key", [(-0.25, "asian_handicap_-0_25"), (0.5, "asian_handicap_+0_5"),
                                      (0.0, "asian_handicap_0"), (-1.0, "asian_handicap_-1"),
                                      (1.75, "asian_handicap_+1_75")])
def test_ah_key_round_trip(line, key):
    assert op._ah_key(line) == key
    assert op.market_of(key + "_market") == ("ah", line)


def test_ah_lines_for():
    assert op.ah_lines_for(-0.25) == (-0.5, -0.25, 0.0)
    assert op.ah_lines_for(None) == op.AH_DEFAULT


def test_parse_record_books_openings_blocked():
    rows = op.parse_record(REC)
    by = {(r[0], r[1], r[2]): r for r in rows}
    a = by[("A", "1x2", 0.0)]
    assert a[3:6] == (2.10, 3.80, 3.20) and a[6:9] == (1.83, 3.75, 3.75)
    assert a[9] == "2026-10-10T16:22:00"
    assert by[("C", "1x2", 0.0)][6:10] == (None, None, None, None)   # 无历史
    assert by[("A", "ou", 2.5)][3:6] == (1.53, 2.50, None)
    assert ("A", "ah", -2.5) not in by                                # 全部被撤下
    assert by[("A", "ah", 3.5)][3:5] == (None, 31.0)                  # "-" 记为空


def test_link_teams_and_names():
    assert op.link_teams(REC["match_link"]) == ("brighton", "liverpool")
    assert op.link_teams("https://x/football/england/premier-league/") is None
    assert op.name_sim("Manchester United", "Manchester Utd") == 1.0
    assert op.name_sim("1 fc koln", "FC Koln") >= 0.9
    assert op.name_sim("Real Madrid", "Ath Madrid") < op.MATCH_MIN + 0.2


@pytest.mark.parametrize("op_name,ours", [
    ("wolves", "Wolverhampton"), ("sheffield utd", "Sheffield United"), ("g a eagles", "Go Ahead Eagles"),
    ("psv", "PSV Eindhoven"), ("sporting cp", "Sp Lisbon"), ("royale union sg", "St. Gilloise"),
    ("st liege", "Standard"), ("basaksehir", "Buyuksehyr"), ("dundee utd", "Dundee United")])
def test_new_league_aliases(op_name, ours):
    assert op.name_sim(op_name, ours) == 1.0


def test_dundee_pairs_with_right_club():
    fx = [{"match_id": "m1", "league": "SC0", "match_date": "2026-11-01",
           "home_team": "Dundee", "away_team": "Kilmarnock"},
          {"match_id": "m2", "league": "SC0", "match_date": "2026-11-01",
           "home_team": "Celtic", "away_team": "Dundee United"}]
    links = [{"match_link": f"https://www.oddsportal.com/football/h2h/{a}-AAAAAAAA/{b}-BBBBBBBB/#x{i}",
              "league": "scotland-premiership", "kickoff_utc": "2026-11-01 15:00:00 UTC"}
             for i, (a, b) in enumerate([("celtic", "dundee-utd"), ("dundee-fc", "kilmarnock")])]
    got = {ln: fx["match_id"] for ln, fx in op.match_links(links, fx).items()}
    assert got == {links[0]["match_link"]: "m2", links[1]["match_link"]: "m1"}


def test_match_links_one_to_one_and_date_window():
    fx = [{"match_id": "m1", "league": "E0", "match_date": "2026-10-25",
           "home_team": "Liverpool", "away_team": "Brighton"},
          {"match_id": "m2", "league": "E0", "match_date": "2026-11-20",
           "home_team": "Brighton", "away_team": "Liverpool"}]
    links = [{"match_link": REC["match_link"], "league": "england-premier-league",
              "kickoff_utc": "2026-10-25 16:00:00 UTC"},
             {"match_link": "https://www.oddsportal.com/football/h2h/aston-villa-W00wmLO0/"
                            "manchester-city-Wtn9Stg0/inplay-odds/#lEVTjuAd",
              "league": "england-premier-league", "kickoff_utc": None}]
    got = op.match_links(links, fx)
    assert list(got) == [REC["match_link"]] and got[REC["match_link"]]["match_id"] == "m1"


def test_record_orientation():
    fx = {"home_team": "Liverpool", "away_team": "Brighton"}
    assert op.record_orientation(REC, fx)
    assert not op.record_orientation(REC, {"home_team": "Brighton", "away_team": "Liverpool"})


@pytest.fixture
def conn():
    c = loader.init_db(":memory:")
    c.execute("""INSERT INTO fixtures (match_id, league, season, match_date, kickoff_utc,
                 home_team, away_team, ah_line, fetched_at, layer_ver)
                 VALUES ('m1','E0','2627','2026-10-25','2026-10-25T14:00:00+00:00',
                 'Liverpool','Brighton',-0.25,'t','1.5.0')""")
    return c


def test_collect_with_fake_runner_and_consensus(conn):
    calls = []

    def runner(args, timeout):
        calls.append(args)
        if "--links-only" in args:
            return [{"match_link": REC["match_link"], "league": "england-premier-league",
                     "kickoff_utc": "2026-10-25 16:00:00 UTC"}]
        return [REC]

    now = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
    n = op.collect(conn, ["E0"], now, hours=48, runner=runner, log=lambda *_: None,
                   timer=lambda: 0.0)
    assert n == len(op.parse_record(REC))
    scrape = calls[1]
    assert "asian_handicap_-0_25" in scrape[1] and "asian_handicap_-0_5" in scrape[1]
    assert scrape.count("--match-link") == 1 and "--odds-history" in scrape

    c = op.book_consensus(conn, "m1")
    assert c["n_books"] == 3 and (c["avg_h"], c["avg_d"], c["avg_a"]) == (2.10, 3.80, 3.20)
    assert (c["avg_over25"], c["avg_under25"]) == (1.54, 2.45)
    assert c["ah_line"] == -0.25 and (c["avg_ahh"], c["avg_aha"]) == (1.815, 1.965)
    o = op.book_consensus(conn, "m1", opening=True)
    assert (o["avg_h"], o["avg_d"], o["avg_a"]) == (1.865, 3.675, 3.775)

    # 窗外不抓；同一时刻重跑不重复写（计时固定，fetched_at 相同）
    assert op.collect(conn, ["E0"], datetime(2026, 11, 1, tzinfo=timezone.utc),
                      runner=runner, log=lambda *_: None) == 0
    op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None, timer=lambda: 0.0)
    assert conn.execute("SELECT COUNT(*) FROM book_odds").fetchone()[0] == n


def test_collect_records_return_time_and_drops_started(conn):
    """fetched_at 是抓回时刻（now + 已过秒数）；抓回时已开球的不入库。"""
    def runner(args, timeout):
        if "--links-only" in args:
            return [{"match_link": REC["match_link"], "league": "england-premier-league",
                     "kickoff_utc": "2026-10-25 16:00:00 UTC"}]
        ticks.append(elapsed)                    # 抓一组要 elapsed 秒
        return [REC]

    now = datetime(2026, 10, 25, 13, 0, tzinfo=timezone.utc)   # 开球 14:00
    ticks, elapsed = [], 1800.0
    timer = lambda: sum(ticks)
    assert op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None, timer=timer) > 0
    got = conn.execute("SELECT DISTINCT fetched_at FROM book_odds").fetchall()
    assert got == [("2026-10-25T13:30:00+00:00",)]

    ticks, elapsed = [], 3600.0                  # 抓回时 14:00 已开球
    assert op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None, timer=timer) == 0
    assert conn.execute("SELECT COUNT(DISTINCT fetched_at) FROM book_odds").fetchone()[0] == 1


def test_collect_skips_swapped_home_away(conn):
    swapped = {**REC, "home_team": "Brighton", "away_team": "Liverpool"}
    runner = lambda args, timeout: ([{"match_link": REC["match_link"],
                                      "league": "england-premier-league",
                                      "kickoff_utc": "2026-10-25 16:00:00 UTC"}]
                                    if "--links-only" in args else [swapped])
    now = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
    assert op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None) == 0
    assert op.book_consensus(conn, "m1") is None


def test_collect_survives_scrape_failure(conn):
    def runner(args, timeout):
        if "--links-only" in args:
            return [{"match_link": REC["match_link"], "league": "england-premier-league",
                     "kickoff_utc": "2026-10-25 16:00:00 UTC"}]
        calls.append(args)
        raise RuntimeError("blocked")
    calls = []
    now = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
    assert op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None, pause=0) == 0
    assert len(calls) == 2                       # 失败重试一次


def test_run_harvester_missing_exe_raises_runtime_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDSHARVESTER", str(tmp_path / "no-such-oddsharvester"))
    with pytest.raises(RuntimeError, match="无法启动"):
        op.run_harvester(["-l", "x"], timeout=5)


def test_run_harvester_bad_json_raises_runtime_error(monkeypatch):
    class P:
        returncode, stderr = 0, ""

    def fake_run(cmd, **kw):
        with open(cmd[cmd.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write("[{truncated")
        return P()
    monkeypatch.setattr(op.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="JSON"):
        op.run_harvester(["-l", "x"], timeout=5)


def test_collect_refetches_matches_missing_from_group(conn):
    """同组两场只回来一场时，缺的那场单独补抓（实盘遇到过整组只返回部分记录）。"""
    conn.execute("""INSERT INTO fixtures (match_id, league, season, match_date, kickoff_utc,
                    home_team, away_team, ah_line, fetched_at, layer_ver)
                    VALUES ('m2','E0','2627','2026-10-25','2026-10-25T16:30:00+00:00',
                    'Chelsea','Tottenham',-0.25,'t','1.5.0')""")
    link2 = "https://www.oddsportal.com/football/h2h/chelsea-4fGZN2oK/tottenham-UDg08Ohm/#abc"
    rec2 = {**REC, "match_link": link2, "home_team": "Chelsea", "away_team": "Tottenham"}
    calls = []

    def runner(args, timeout):
        if "--links-only" in args:
            return [{"match_link": ln, "league": "england-premier-league",
                     "kickoff_utc": "2026-10-25 16:00:00 UTC"} for ln in (REC["match_link"], link2)]
        calls.append(args)
        return [REC] if args.count("--match-link") == 2 else [rec2]

    now = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
    op.collect(conn, ["E0"], now, runner=runner, log=lambda *_: None, pause=0)
    assert [a.count("--match-link") for a in calls] == [2, 1] and link2 in calls[1]
    assert op.book_consensus(conn, "m1") and op.book_consensus(conn, "m2")
