"""services/monitor：实盘体检（未评分、赛程缺赔率 / 缺主模型存档、多家赔率抓取时间、近 30 天滚动差）。离线。"""
from datetime import datetime, timedelta

from football_prediction import version
from football_prediction.data.oddsportal import init_book_odds
from football_prediction.review.store import save_prediction, score_predictions
from football_prediction.services import monitor
from tests.test_report_live import _fixture

PRIMARY = version.PRIMARY_MODEL[0]
CODE = {"home_win": 0, "draw": 1, "away_win": 2}


def _probs(outcome: str, p_true: float) -> tuple[float, float, float]:
    p = [(1 - p_true) / 2] * 3
    p[CODE[outcome]] = p_true
    return tuple(p)


def _graded(conn, now, n=20):
    """前 n 场合成比赛按最近 n 天开球存档：主模型给真实赛果的概率低，market_avg 高，再评分。"""
    rows = conn.execute("SELECT match_id, home_goals, away_goals FROM matches ORDER BY match_id "
                        "LIMIT ?", (n,)).fetchall()
    for i, (mid, hg, ag) in enumerate(rows):
        out = "home_win" if hg > ag else "away_win" if hg < ag else "draw"
        ko = now - timedelta(days=1 + i)
        extra = {"kickoff_utc": ko.isoformat()}
        save_prediction(conn, mid, PRIMARY, "1", "f", *_probs(out, 0.20 + 0.01 * (i % 5)),
                        extra_markets=extra, at=ko - timedelta(hours=2))
        save_prediction(conn, mid, "market_avg", "1", "f", *_probs(out, 0.60 + 0.01 * (i % 3)),
                        extra_markets=extra, at=ko - timedelta(hours=2))
    score_predictions(conn)


def test_rolling_flags_primary_worse(league):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _graded(conn, now)
    h = monitor.health_check(conn, now)
    r = {x["ref"]: x for x in h["rolling"]}
    assert r["market_avg"]["n"] == 20 and r["market_avg"]["diff"] > 0 and r["market_avg"]["worse"]
    assert r[version.MARKET_MODEL[0]]["n"] == 0
    lines = monitor.health_lines(h)
    assert any(l.startswith("⚠") and "market_avg" in l and "显著更差" in l for l in lines)
    assert any("样本不足" in l for l in lines)

    later = monitor.health_check(conn, now + timedelta(days=monitor.ROLLING_DAYS + 25))
    assert {x["ref"]: x["n"] for x in later["rolling"]}["market_avg"] == 0   # 窗口外不计


def test_stale_upcoming_and_book(league):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    ko = now - timedelta(days=monitor.STALE_DAYS + 2)
    save_prediction(conn, "nores", "market_avg", "1", "f", 0.4, 0.3, 0.3,
                    extra_markets={"kickoff_utc": ko.isoformat()}, at=ko - timedelta(hours=1))
    _fixture(conn, "soon", (now + timedelta(hours=3)).isoformat())
    _fixture(conn, "noodds", (now + timedelta(hours=20)).isoformat(), "B", "E",
             avg_h=None, avg_d=None, avg_a=None)
    _fixture(conn, "far", (now + timedelta(hours=monitor.UPCOMING_HOURS + 5)).isoformat(), "C", "D")
    save_prediction(conn, "soon", PRIMARY, "1", "f", 0.5, 0.3, 0.2,
                    extra_markets={"kickoff_utc": (now + timedelta(hours=3)).isoformat()},
                    at=now - timedelta(hours=1))
    before = conn.total_changes
    h = monitor.health_check(conn, now)
    assert conn.total_changes == before                     # 只读
    assert [m for m, _ in h["stale"]] == ["nores"]
    assert h["upcoming"] == {"n": 2, "no_odds": 1, "no_primary": 1}
    assert h["book_last"] is None
    lines = monitor.health_lines(h)
    assert lines[0].startswith("⚠") and "nores" in lines[0]
    assert lines[1].startswith("⚠") and "缺赛程表赔率 1 场" in lines[1]
    assert any("还没有抓取记录" in l for l in lines)
    assert any(l.startswith("football-data 最近赛果：") for l in lines)   # league fixture 有比分

    init_book_odds(conn)
    conn.execute("INSERT INTO book_odds (match_id, fetched_at, bookmaker, market, line, source, layer_ver) "
                 "VALUES ('soon', ?, 'x', '1x2', 0, 'oddsportal', 't')",
                 ((now - timedelta(hours=monitor.BOOK_STALE_HOURS + 1)).isoformat(),))
    lines = monitor.health_lines(monitor.health_check(conn, now))
    assert any(l.startswith("⚠ 多家赔率最近一次抓取") for l in lines)
