"""中间层 services：实盘一轮写快照、读接口（当前列表 / 单场详情 / 成绩单）、分层边界。离线，不碰 football.db。"""
import json
import math
import pathlib
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from football_prediction import services, version
from football_prediction.data import fotmob
from football_prediction.services import live_round
from tests.test_report_live import _fixture

PKG = pathlib.Path(__file__).resolve().parent.parent / "football_prediction"


def _round(conn, now, tmp_path, monkeypatch):
    """跑一轮实盘（不联网：更新数据换成空操作；报告与快照写到临时目录）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live_round, "update_data", lambda *a, **k: None)
    snap = str(tmp_path / "latest_round.json")
    return live_round.run_round(conn, now, snapshot_path=snap, log=lambda s: None), snap


def test_run_round_writes_report_and_snapshot(league, tmp_path, monkeypatch):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "soon", (now + timedelta(hours=3)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=2)).isoformat(), "C", "D")
    _fixture(conn, "noodds", (now + timedelta(days=3)).isoformat(), "B", "E",
             avg_h=None, avg_d=None, avg_a=None, avg_over25=None, avg_under25=None, ah_line=None)
    out, snap = _round(conn, now, tmp_path, monkeypatch)

    assert list(out["report"]["主队"]) == ["A", "C", "B"]
    assert pathlib.Path(out["report_path"]).exists()
    assert out["primary"] == (version.PRIMARY_MODEL[0], version.get(version.PRIMARY_MODEL[1]))
    assert out["scorecard"].empty and out["promotion"] is None     # 还没有评分
    data = json.loads(pathlib.Path(snap).read_text(encoding="utf-8"))
    assert data["schema"] == live_round.SNAPSHOT_SCHEMA and data["system_version"] == version.SYSTEM_VERSION
    assert [m["match_id"] for m in data["matches"]] == ["soon", "late", "noodds"]

    m = data["matches"][0]
    assert list(m)[11:13] == ["odds_source", "asian"]                 # 对阵、赔率来源之后先是亚盘
    ah = m["asian"]
    assert ah["line"] == -1.0 and ah["line_source"] == "市场线" and ah["side"] in ("主", "客")
    assert abs(sum(ah["outcome"].values()) - 1) < 1e-3 and ah["tier"] in ("高", "中", "低")
    assert m["odds_source"].startswith("赛程表") and abs(sum(m["probabilities"]) - 1) < 1e-3
    assert m["probability_source"] == "市场" and m["score_source"] == "市场隐含"
    assert (m["model_name"], m["model_version"]) == out["primary"]
    assert m["recommended"] == (m["confidence"] == "高")              # 重点 = 胜平负市场档高
    assert (m["recommendation_note"] is None) != m["recommended"]
    side = 1 if ah["side"] == "主" else -1                           # 稳妥线从市场线向选择方退
    assert ah["safe_cover"] >= 0.65 and (ah["safe_line"] - ah["line"]) * side >= 0
    n = data["matches"][2]                                          # 无赔率：公平线、不分档
    assert n["model_name"] == version.FALLBACK_MODEL[0] and n["recommended"] is False
    assert n["odds_source"] is None and n["asian"]["line_source"] == "公平线"
    assert n["asian"]["tier"] == "-" and n["asian"]["historical_hit"] is None
    assert any("缺胜平负赔率" in h for h in n["hints"] + n["risks"])


def test_snapshot_absent_reads_none(tmp_path, conn):
    p = str(tmp_path / "none.json")
    now = datetime.now().astimezone()
    assert services.read_current(now, p) is None and services.read_scorecard(p) is None
    assert services.read_match(conn, "nothing", p) is None


def test_read_current_drops_started(league, tmp_path, monkeypatch):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "soon", (now + timedelta(hours=1)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=1)).isoformat(), "C", "D")
    _, snap = _round(conn, now, tmp_path, monkeypatch)
    assert [m["match_id"] for m in services.read_current(now, snap)["matches"]] == ["soon", "late"]
    later = services.read_current(now + timedelta(hours=2), snap)
    assert [m["match_id"] for m in later["matches"]] == ["late"]      # 快照后已开球的剔除
    assert later["primary_model"]["name"] == version.PRIMARY_MODEL[0]


def test_read_match_current_and_first_archive(league, tmp_path, monkeypatch):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _, snap = _round(conn, now, tmp_path, monkeypatch)
    first_at = conn.execute("SELECT generated_at FROM predictions WHERE match_id='f1' AND model_name=?",
                            (version.PRIMARY_MODEL[0],)).fetchone()[0]
    services.predict_upcoming(conn, now + timedelta(hours=1))      # 不会覆盖首次存档

    d = services.read_match(conn, "f1", snap)
    assert d["match"]["home"] == "A" and d["match"]["score"] is None and d["match"]["kickoff_utc"]
    assert d["current"]["match_id"] == "f1" and d["generated_at"] == now.isoformat()
    ar = d["archived"]
    assert (ar["model_name"], ar["model_version"]) == (version.PRIMARY_MODEL[0],
                                                      version.get(version.PRIMARY_MODEL[1]))
    assert ar["generated_at"] == first_at and ar["scored"] is False and ar["log_loss"] is None
    assert ar["asian"]["line"] == -1.0 and abs(sum(ar["asian"]["outcome"].values()) - 1) < 1e-3
    assert ar["asian"]["line_source"] == "市场线" and ar["asian"]["tier"] in ("高", "中", "低")
    assert ar["asian"]["side"] in ("主", "客") and ar["asian"]["p_cover"] >= 0.5
    assert ar["asian"]["safe_cover"] >= 0.65                         # 存档各线的结算算出稳妥线
    assert ar["lean"] == "主胜" and ar["confidence"] in ("高", "中", "低")   # 主胜赔率 1.5
    assert ar["likely_scores"] and ar["historical_first_hit"] > 0
    assert ar["odds"]["avg_h"] == 1.5 and 0 < ar["over25"] < 1
    json.dumps(d)                                                   # 接口可直接序列化

    assert services.read_match(conn, "unknown", snap) is None
    # 快照里没有、库里有完赛比分的场次：只给对阵与比分
    mid, h, a, hg, ag = conn.execute("SELECT match_id, home_team, away_team, home_goals, away_goals "
                                     "FROM matches LIMIT 1").fetchone()
    old = services.read_match(conn, mid, snap)
    assert old["current"] is None and old["archived"] is None
    assert (old["match"]["home"], old["match"]["away"]) == (h, a)
    assert old["match"]["score"] == {"home": hg, "away": ag}


def test_read_recent_and_fotmob_score(league, tmp_path):
    """最近已开球场次：首次存档 + 比分；football-data 赛果没到时用 fotmob_results；对阵查不到的跳过。"""
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=2)).isoformat(), "C", "D")
    services.predict_upcoming(conn, now)
    assert services.read_recent(conn, now) == []                       # 都还没开球

    after = now + timedelta(hours=6)
    rec = services.read_recent(conn, after)
    assert [r["match"]["match_id"] for r in rec] == ["f1"]
    assert rec[0]["match"]["score"] is None and rec[0]["match"]["score_source"] is None
    assert rec[0]["archived"]["model_name"] == version.PRIMARY_MODEL[0]

    fotmob.attach(conn, str(tmp_path / "fm.db"))
    conn.execute("INSERT INTO fm.fotmob_results VALUES ('f1','99',2,1,'2026-01-01T00:00:00+00:00','t')")
    m = services.read_recent(conn, after)[0]["match"]
    assert m["score"] == {"home": 2, "away": 1} and m["score_source"] == "fotmob"
    assert services.read_match(conn, "f1", str(tmp_path / "none.json"))["match"]["score_source"] == "fotmob"

    later = now + timedelta(days=5)
    assert [r["match"]["match_id"] for r in services.read_recent(conn, later)] == ["late"]   # f1 超出 3 天
    assert len(services.read_recent(conn, later, days=7)) == 2
    conn.execute("DELETE FROM fixtures")                              # 赛程表刷新后换掉、赛果未到
    rec = services.read_recent(conn, later, days=7)
    assert [r["match"]["match_id"] for r in rec] == ["late", "f1"]   # 对阵改从存档里记下的取
    assert (rec[1]["match"]["home"], rec[1]["match"]["away"], rec[1]["match"]["league"]) == ("A", "F", "E0")
    assert rec[1]["match"]["kickoff_utc"] == (now + timedelta(hours=5)).isoformat()
    assert services.read_match(conn, "f1", str(tmp_path / "none.json"))["match"]["home"] == "A"
    conn.execute("UPDATE predictions SET extra_markets = json_remove(extra_markets, '$.match')")
    assert services.read_recent(conn, later, days=7) == []           # 记对阵之前的旧存档：查不到，跳过


def test_run_near_rewrites_snapshot_with_book_odds(league, tmp_path, monkeypatch):
    """临场档窗口内有场次时按最新赔率（多家中位数）重写快照，含窗口外的未开赛场次；窗口内没场次时不动快照。"""
    from tests.test_report_live import _books
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "near", (now + timedelta(hours=1)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=1)).isoformat(), "C", "D")
    _, snap = _round(conn, now, tmp_path, monkeypatch)
    before = json.loads(pathlib.Path(snap).read_text(encoding="utf-8"))
    assert before["matches"][0]["odds_source"].startswith("赛程表")

    t1 = now + timedelta(minutes=20)
    fake_odds = lambda c, leagues, t, hours: _books(c, "near", t) or 9
    assert services.run_near(conn, t1, fake_odds, lambda c, t, h: [], log=lambda s: None,
                             snapshot_path=snap) == 3
    after = json.loads(pathlib.Path(snap).read_text(encoding="utf-8"))
    assert after["generated_at"] == t1.isoformat()
    assert [m["match_id"] for m in after["matches"]] == ["near", "late"]
    assert after["matches"][0]["odds_source"].startswith("多家中位数（3 家")
    assert after["matches"][1]["odds_source"].startswith("赛程表")
    rec = services.read_recent(conn, now + timedelta(hours=2))[0]
    assert rec["match"]["home"] == "A"
    # 两份存档：赛前首次存档（赛程表赔率）+ 临场档（多家中位数）
    d = services.read_match(conn, "near", snap)
    na = d["near_archived"]
    assert (na["model_name"], na["horizon"], na["n_books"]) == (version.PRIMARY_MODEL[0] + "_t1", "t1", 3)
    assert na["hours_to_ko"] == pytest.approx(0.67, abs=0.01) and na["asian"]["line_source"] == "市场线"
    assert d["archived"]["horizon"] == "pre" and d["archived"]["n_books"] is None
    assert rec["near_archived"]["generated_at"] == na["generated_at"]
    assert services.read_match(conn, "late", snap)["near_archived"] is None
    conn.execute("UPDATE predictions SET generated_at=? WHERE model_name LIKE '%_t1'",
                 ((now + timedelta(hours=1, minutes=5)).isoformat(),))   # 修复前开球后才存的临场档
    assert services.read_match(conn, "near", snap)["near_archived"] is None

    far = now + timedelta(hours=3)                                  # 1.5 小时内没有开球的场次
    assert services.run_near(conn, far, fake_odds, lambda c, t, h: [], log=lambda s: None,
                             snapshot_path=snap) == 0
    assert json.loads(pathlib.Path(snap).read_text(encoding="utf-8"))["generated_at"] == t1.isoformat()


def test_open_readonly_attaches_fotmob(tmp_path):
    db, fm = tmp_path / "a.db", tmp_path / "fm.db"
    sqlite3.connect(db).close()
    fotmob.attach(sqlite3.connect(":memory:"), str(fm))
    conn = services.open_readonly(str(db), fotmob_path=str(fm))
    assert conn.execute("SELECT count(*) FROM fm.fotmob_results").fetchone() == (0,)
    with pytest.raises(sqlite3.OperationalError):                      # 挂上的库也是只读
        conn.execute("INSERT INTO fm.fotmob_results VALUES ('x','1',0,0,'t','t')")
    conn.close()
    assert "fm" not in {r[1] for r in services.open_readonly(
        str(db), fotmob_path=str(tmp_path / "none.db")).execute("PRAGMA database_list")}
    assert not (tmp_path / "none.db").exists()


def test_read_match_falls_back_to_dc_xg(league, tmp_path):
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "noodds", (now + timedelta(hours=5)).isoformat(), "B", "E",
             avg_h=None, avg_d=None, avg_a=None, avg_over25=None, avg_under25=None, ah_line=None)
    services.predict_upcoming(conn, now)
    ar = services.read_match(conn, "noodds", str(tmp_path / "none.json"))["archived"]
    assert ar["model_name"] == version.FALLBACK_MODEL[0]
    assert ar["asian"]["line_source"] == "公平线" and ar["asian"]["tier"] == "-"   # 无市场线不分档


def test_scorecard_rows_json_safe(tmp_path):
    rep = pd.DataFrame([{"model_name": "market_implied", "model_ver": "1.0.0", "matches": 12,
                         "log_loss": 0.98765, "brier": float("nan"), "ah_n": 10, "paired_n": float("nan")}])
    rows = live_round.scorecard_rows(rep)
    assert rows == [{"model_name": "market_implied", "model_ver": "1.0.0", "matches": 12,
                     "log_loss": 0.9877, "brier": None, "ah_n": 10, "paired_n": None}]
    assert live_round.scorecard_rows(pd.DataFrame()) == []
    p = str(tmp_path / "s.json")
    live_round.write_snapshot(p, datetime.now().astimezone(), [], rows)
    sc = services.read_scorecard(p)
    assert sc["scorecard"] == rows and sc["system_version"] == version.SYSTEM_VERSION
    assert not pathlib.Path(p + ".tmp").exists()                    # 原子替换后不留临时文件
    assert live_round._num(float("inf")) is None and live_round._num(math.nan) is None


def test_snapshot_replace_retries_when_locked(tmp_path, monkeypatch):
    """Windows 上接口正好读着旧快照时 os.replace 会被拒绝：短暂重试，多次失败才报错。"""
    real, calls = live_round.os.replace, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("locked")
        real(src, dst)

    monkeypatch.setattr(live_round.os, "replace", flaky)
    monkeypatch.setattr(live_round, "REPLACE_WAIT", 0)
    p = str(tmp_path / "s.json")
    live_round.write_snapshot(p, datetime.now().astimezone(), [], [])
    assert len(calls) == 3 and services.read_scorecard(p)["scorecard"] == []

    monkeypatch.setattr(live_round.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("x")))
    with pytest.raises(PermissionError):
        live_round.write_snapshot(p, datetime.now().astimezone(), [], [])


def test_domain_layers_do_not_import_services():
    """依赖方向 web → server → services → 领域包：领域包不反向依赖 services。"""
    bad = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py")
           if p.parts[len(PKG.parts)] not in ("services",)
           and p.name not in ("live.py", "explain.py", "main.py")
           and ("football_prediction.services" in (t := p.read_text(encoding="utf-8"))
                or "from ..services" in t or "from .services" in t)]
    assert bad == []
