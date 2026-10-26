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
    assert r["历史命中(首选/双选)"] == "72%/89%"
    from football_prediction.model_market.devig import shin
    ps = sorted(shin([1.5, 4.0, 5.5]), reverse=True)
    assert r["本场估计(首选/双选)"] == f"{ps[0]:.0%}/{ps[0] + ps[1]:.0%}"
    assert r["最可能比分"] and r["大2.5球"] and r["亚盘"].startswith("主-1.00 赢盘")
    assert r["亚盘选择"][0] in "主客" and r["亚盘信心"]
    assert list(df.columns).index("亚盘") == list(df.columns).index("客队") + 1   # 亚盘紧跟对阵
    assert "dc_xg" in r["自研 主/平/客"] and "blend" in r["自研 主/平/客"]
    assert r["开球(北京)"] == (now + timedelta(hours=3)).astimezone(
        ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
    n = df.iloc[2]                                        # 无赔率：回退自研，并提示
    assert n["概率来源"] == "blend" and n["比分来源"].startswith("dc_xg")
    assert "缺胜平负赔率" in n["提示"]


def test_build_report_empty(conn):
    assert build_report(conn, {}, datetime.now(timezone.utc)).empty


def test_report_prefers_fresh_book_consensus(league):
    """报告用 24 小时内 ≥3 家的多家中位数；家数不够或过期回退赛程表；存档仍用赛程表赔率。"""
    import football_prediction.live as live
    from football_prediction.output.pipeline import latest_odds
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    for mid, home, away in (("fresh", "A", "F"), ("few", "B", "E"), ("stale", "C", "D")):
        _fixture(conn, mid, (now + timedelta(hours=5)).isoformat(), home, away)
    _books(conn, "fresh", now - timedelta(hours=2), h=1.6)
    _books(conn, "few", now - timedelta(hours=2), n=2, h=1.6)
    _books(conn, "stale", now - timedelta(hours=30), h=1.6)

    df = build_report(conn, {"E0": "英超"}, now).set_index("主队")
    inv = [1 / 1.6, 1 / 4.0, 1 / 5.0]
    assert df.loc["A", "主胜"] == f"{inv[0] / sum(inv):.0%}"
    assert df.loc["A", "赔率来源"].startswith("多家中位数（3 家")
    fx = [1 / 1.5, 1 / 4.0, 1 / 5.5]
    for t in ("B", "C"):
        assert df.loc[t, "主胜"] == f"{fx[0] / sum(fx):.0%}"
        assert df.loc[t, "赔率来源"].startswith("赛程表")

    row = {"match_id": "nobook", **ODDS}
    assert latest_odds(conn, row, now) == ({k: row[k] for k in ODDS}, "赛程表快照（football-data）")

    live._predict_upcoming(conn, now)
    ex = json.loads(conn.execute("SELECT extra_markets FROM predictions WHERE match_id='fresh' "
                                 "AND model_name='market_avg'").fetchone()[0])
    assert ex["odds"] == [1.5, 4.0, 5.5]                 # 存档不受报告赔率来源影响


def test_latest_odds_without_book_table(conn):
    from football_prediction.output.pipeline import latest_odds
    row = {"match_id": "x", **ODDS}
    assert latest_odds(conn, row, datetime.now(timezone.utc))[1].startswith("赛程表")


def test_movement_compares_same_source_snapshots():
    """定价用多家中位数时，盘口变动仍看赛程表首条 vs 最新，不跨来源比。"""
    import numpy as np
    from football_prediction.output.analysis import analyse
    m = np.full((9, 9), 1 / 81)
    first = {"avg_h": 2.0, "avg_d": 3.4, "avg_a": 3.8}
    a = analyse({**ODDS}, m, -0.05, {}, first, [], last_row=dict(first))
    assert a["move"] == "平稳"                            # 赛程表快照没变；ODDS 本身与 first 差很多
    assert analyse({**ODDS}, m, -0.05, {}, first, [])["move"] != "平稳"


def test_predict_upcoming_saves_once(league, monkeypatch):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _fixture(conn, "f0", (now - timedelta(hours=5)).isoformat(), "B", "E")   # 已开球

    first = live._predict_upcoming(conn, now)
    assert first == 9          # DC / 射正 / xG / 市场版 DC / Elo / blend / 市场 / 市场隐含 / Shin 市场隐含
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
    assert live._predict_upcoming(conn, now) == 7
    assert not conn.execute("SELECT 1 FROM predictions WHERE model_name LIKE 'market_%' "
                            "AND model_name != 'market_avg'").fetchone()


def _books(conn, mid, fetched_at, n=3, h=1.6):
    """n 家公司的 1X2 + 大小2.5 + 亚盘 -1 赔率，写入 book_odds 一个批次。"""
    from football_prediction.data.oddsportal import init_book_odds, save_book_odds
    init_book_odds(conn)
    rows = []
    for i in range(n):
        rows += [(f"b{i}", "1x2", 0.0, h, 4.0, 5.0, None, None, None, None),
                 (f"b{i}", "ou", 2.5, 1.8, 2.0, None, None, None, None, None),
                 (f"b{i}", "ah", -1.0, 1.95, 1.95, None, None, None, None, None)]
    save_book_odds(conn, mid, rows, fetched_at.isoformat())
    conn.commit()


def test_predict_near_needs_window_fresh_odds_and_books(league):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "near", (now + timedelta(hours=1)).isoformat())
    _fixture(conn, "far", (now + timedelta(hours=5)).isoformat(), "C", "D")
    _fixture(conn, "stale", (now + timedelta(hours=1)).isoformat(), "B", "E")
    _fixture(conn, "few", (now + timedelta(minutes=30)).isoformat(), "C", "F")
    _books(conn, "near", now - timedelta(minutes=10))
    _books(conn, "far", now - timedelta(minutes=10))
    _books(conn, "stale", now - timedelta(hours=3))
    _books(conn, "few", now - timedelta(minutes=10), n=2)
    cache = live.ModelCache(conn, cutoff)

    assert live._predict_near(conn, now, cache) == 3    # market_avg / implied / shin，各带 _t1
    assert live._predict_near(conn, now, cache) == 0
    rows = conn.execute("SELECT match_id, model_name FROM predictions").fetchall()
    assert {r[0] for r in rows} == {"near"}
    assert {r[1] for r in rows} == {"market_avg_t1", "market_implied_t1", "market_shin_t1"}
    ex = json.loads(conn.execute("SELECT extra_markets FROM predictions "
                                 "WHERE model_name='market_shin_t1'").fetchone()[0])
    assert ex["horizon"] == "t1" and ex["n_books"] == 3 and ex["hours_to_ko"] == 1.0
    assert ex["odds"]["avg_h"] == 1.6 and "fetched_at" not in ex["odds"]
    assert len(ex["score_matrix"]) == 81


def test_predict_near_archives_lineup_pair_only_for_standard_xi(league, monkeypatch):
    import football_prediction.live as live
    import football_prediction.model_lineup.adjust as adjust
    from tests.test_lineup import POS, _lineups, _pid
    conn, cutoff = league
    _lineups(conn)
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "near", (now + timedelta(hours=1)).isoformat())
    _fixture(conn, "pred", (now + timedelta(hours=1)).isoformat(), "B", "E")
    for mid, (h, a), kind in (("near", ("A", "F"), "standard"), ("pred", ("B", "E"), "predicted")):
        _books(conn, mid, now - timedelta(minutes=10))
        for side, t in (("home", h), ("away", a)):
            # 主队 A 两名前锋换成替补：进攻评分下降
            ks = [*range(9), 11, 12] if t == "A" else range(11)
            for k in ks:
                conn.execute("INSERT INTO lineups VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (mid, "t1", kind, side, _pid(t, k), None, "starter", POS[k], None, None))
    conn.commit()
    # 阵容批次名 "t1" 按字符串排在 ISO 时间之后：赔率算作早于首发 → 走 COEF_PRE
    monkeypatch.setattr(adjust, "COEF_PRE", {"d_att": 1.0, "rot": 0.0, "opp_rot_def": 0.0, "opp_rot": 0.0})

    assert live._predict_near(conn, now, live.ModelCache(conn, cutoff)) == 3 + 3 + 2
    rows = {(m, n): (ph, json.loads(ex)) for m, n, ph, ex in conn.execute(
        "SELECT match_id, model_name, p_home_win, extra_markets FROM predictions")}
    assert ("pred", "lineup_t1") not in rows            # 预测阵容不存
    base, adj = rows[("near", "lineup_base_t1")], rows[("near", "lineup_t1")]
    assert base[0] == pytest.approx(rows[("near", "market_implied_t1")][0])
    assert adj[0] < base[0]                              # 主队进攻变弱 -> 主胜概率下降
    assert adj[1]["lineup"]["home"]["rot"] == pytest.approx(2 / 11)
    assert adj[1]["lam"][0] < base[1]["lam"][0] and adj[1]["lam"][1] == base[1]["lam"][1]
    assert adj[1]["horizon"] == "t1" and adj[1]["odds_vs_lineup"] == "pre"
    assert live._predict_near(conn, now, live.ModelCache(conn, cutoff)) == 0


def test_lineup_after_odds_uses_post_coef(league, monkeypatch):
    """赔率晚于首次看到正式首发：用 COEF_POST（此处为 0），lineup_t1 与 lineup_base_t1 相同。"""
    import football_prediction.live as live
    import football_prediction.model_lineup.adjust as adjust
    from tests.test_lineup import POS, _lineups, _pid
    conn, cutoff = league
    _lineups(conn)
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "near", (now + timedelta(hours=1)).isoformat())
    _books(conn, "near", now - timedelta(minutes=5))
    seen = (now - timedelta(minutes=20)).isoformat()
    for side, t in (("home", "A"), ("away", "F")):
        for k in ([*range(9), 11, 12] if t == "A" else range(11)):
            conn.execute("INSERT INTO lineups VALUES (?,?,?,?,?,?,?,?,?,?)",
                         ("near", seen, "standard", side, _pid(t, k), None, "starter", POS[k], None, None))
    conn.commit()
    monkeypatch.setattr(adjust, "COEF_PRE", {"d_att": 1.0, "rot": 0.0, "opp_rot_def": 0.0, "opp_rot": 0.0})
    assert live._predict_near(conn, now, live.ModelCache(conn, cutoff)) == 3 + 2
    rows = {n: (ph, json.loads(ex)) for n, ph, ex in conn.execute(
        "SELECT model_name, p_home_win, extra_markets FROM predictions")}
    assert rows["lineup_t1"][0] == pytest.approx(rows["lineup_base_t1"][0])
    assert rows["lineup_t1"][1]["odds_vs_lineup"] == "post"
    assert rows["lineup_t1"][1]["lineup_first_seen"] == seen


def test_run_near_uses_injected_collectors(league):
    import football_prediction.live as live
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "near", (now + timedelta(hours=1)).isoformat())
    calls = []

    def fake_odds(c, leagues, t, hours):
        calls.append(("odds", hours))
        _books(c, "near", t)
        return 9

    def fake_lineups(c, t, hours):
        calls.append(("lineups", hours))
        raise RuntimeError("网络断开")     # 阵容失败不影响赔率存档

    assert live._run_near(conn, now, fake_odds, fake_lineups) == 3
    assert calls == [("lineups", live.T1_HOURS), ("odds", live.T1_HOURS)]   # 先阵容后赔率
