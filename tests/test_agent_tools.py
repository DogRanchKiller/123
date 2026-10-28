"""Agent 工具层（agent/tools）：返回结构、块的四个键、开球前后改标与整块丢弃、只读（md5 不变）。
在临时目录用 conftest 的合成比赛建文件型 SQLite 和快照，config.override 换路径和时钟；不读 .env、不碰 football.db。
agent/tools 不 import mcp，所以 .venv 里也跑。"""
import hashlib
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

import pytest

from agent import config
from agent.tools import (TOOLS, explain_fixture, get_match, kb_search, list_upcoming, recent_results,
                         resolve_team, scorecard, team_news)
from football_prediction import services, version
from football_prediction.data import fotmob
from football_prediction.review.store import score_predictions
from tests.test_report_live import _fixture
from tests.test_services import _round

KINDS = {"current", "last_pre_kickoff", "live_calc", "first_archive", "near_archive", "score",
         "grading", "scorecard", "closing", "team_news", "kb"}
HEAD = {"match": ["scope", "match_id", "kind", "at"], "kb": ["scope", "chunk_id", "kind", "at"],
        "scorecard": ["scope", "model_name", "model_ver", "kind", "at"]}
PRIMARY = version.PRIMARY_MODEL[0]


def _save(conn, path: pathlib.Path) -> None:
    """内存库整库复制到文件（工具只读打开这个文件）。"""
    dst = sqlite3.connect(path)
    conn.backup(dst)
    dst.close()


def build_world(league, tmp_path, monkeypatch) -> dict:
    """两场未开球：soon（A–F，3 小时后）和 late（C–D，2 天后）；跑一轮实盘写快照和首次存档。"""
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "soon", (now + timedelta(hours=3)).isoformat())
    _fixture(conn, "late", (now + timedelta(days=2)).isoformat(), "C", "D")
    _, snap = _round(conn, now, tmp_path, monkeypatch)
    db = tmp_path / "agent.db"
    _save(conn, db)
    return {"conn": conn, "now": now, "db": db, "snap": pathlib.Path(snap), "fm": tmp_path / "fm.db",
            "soon_ko": now + timedelta(hours=3)}


@pytest.fixture
def world(league, tmp_path, monkeypatch):
    return build_world(league, tmp_path, monkeypatch)


def use(w: dict, at: datetime, **kw):
    """按世界 w 的库和快照、固定时钟 at 换配置；fotmob 库默认指向 w['fm']（不存在时不挂），
    知识库默认指向临时目录里还没建的索引（不碰 agent_data/kb）。"""
    paths = {"db_path": str(w["db"]), "snapshot_path": str(w["snap"]), "fotmob_path": str(w["fm"]),
             "kb_path": str(w["db"].parent / "kb-none")}
    return config.override(**{**paths, **kw}, clock=lambda: at)


def check(out: dict) -> list[dict]:
    """每个工具返回的公共结构：as_of、blocks；每块开头是 scope、主体键、kind、at；可直接 JSON 序列化。"""
    assert list(out)[:2] == ["as_of", "blocks"]
    json.dumps(out, ensure_ascii=False, allow_nan=False)
    for b in out["blocks"]:
        head = HEAD[b["scope"]]
        assert list(b)[:len(head)] == head and b["kind"] in KINDS and b["at"]
    return out["blocks"]


def test_list_upcoming_filters_and_kind(world):
    with use(world, world["now"]):
        bs = check(list_upcoming())
        assert [b["match_id"] for b in bs] == ["soon", "late"]
        b = bs[0]
        assert b["kind"] == "current" and b["at"] == world["now"].isoformat()
        assert (b["home"], b["away"], b["league"], b["league_name"]) == ("A", "F", "E0", "英超")
        assert b["asian"]["line"] == -1.0 and abs(sum(b["probabilities"]) - 1) < 1e-3
        assert [x["match_id"] for x in check(list_upcoming(hours=24))] == ["soon"]
        assert [x["match_id"] for x in check(list_upcoming("英超", 72))] == ["soon", "late"]
        assert check(list_upcoming("D1")) == [] and list_upcoming("D1")["note"]
        for bad in ({"hours": 0}, {"hours": 337}, {"league": "XX"}):
            with pytest.raises(ValueError):
                list_upcoming(**bad)
    with use(world, world["soon_ko"] + timedelta(minutes=1)):
        assert [b["match_id"] for b in check(list_upcoming())] == ["late"]     # 开球后不再列出


def test_no_snapshot_gives_note(world, tmp_path):
    with use(world, world["now"], snapshot_path=str(tmp_path / "none.json")):
        for out in (list_upcoming(), scorecard()):
            assert check(out) == [] and "快照" in out["note"]


def test_get_match_relabels_after_kickoff(world):
    with use(world, world["now"]):
        bs = check(get_match("soon"))
        assert [b["kind"] for b in bs] == ["current", "first_archive"]          # 还没有比分和评分
        ar = bs[1]
        assert ar["model_name"] == PRIMARY and ar["at"] == ar["generated_at"]
        assert "log_loss" not in ar and "scored" not in ar                    # 评分单独成块
        assert ar["asian"]["line"] == -1.0 and ar["home"] == "A"
        # 档位、历史命中率、稳妥线是按现行规则现算的，存档块里不给
        assert not {"confidence", "historical_first_hit", "historical_double_hit"} & ar.keys()
        assert not {"tier", "historical_hit", "safe_line", "safe_cover"} & ar["asian"].keys()
        with pytest.raises(ValueError, match="找不到比赛"):
            get_match("nope")
    with use(world, world["soon_ko"]):                                         # 开球那一刻起改标
        assert [b["kind"] for b in check(get_match("soon"))] == ["last_pre_kickoff", "first_archive"]

    # 快照在开球之后重写（这场仍在快照里）：看法整块丢弃，存档照常
    snap = json.loads(world["snap"].read_text(encoding="utf-8"))
    snap["generated_at"] = (world["soon_ko"] + timedelta(minutes=5)).isoformat()
    world["snap"].write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    with use(world, world["soon_ko"] + timedelta(hours=1)):
        assert [b["kind"] for b in check(get_match("soon"))] == ["first_archive"]
        assert [b["match_id"] for b in check(list_upcoming())] == ["late"]


def test_score_and_grading_blocks(world):
    conn = world["conn"]
    conn.execute("INSERT INTO matches VALUES ('soon','E0','2425',?,'A','F',2,1,'test',?,'t')",
                 (world["soon_ko"].date().isoformat(), "2030-01-01T00:00:00+00:00"))
    conn.commit()
    assert score_predictions(conn) > 0
    _save(conn, world["db"])
    with use(world, world["soon_ko"] + timedelta(hours=3)):
        bs = check(get_match("soon"))
        kinds = [b["kind"] for b in bs]
        assert kinds[:3] == ["last_pre_kickoff", "first_archive", "score"] and "grading" in kinds
        sc = bs[2]
        assert sc["score"] == {"home": 2, "away": 1} and sc["score_source"] == "football-data"
        assert sc["at"] == "2030-01-01T00:00:00+00:00"
        gr = [b for b in bs if b["kind"] == "grading"]
        assert gr[0]["model_name"] == PRIMARY and {b["model_name"] for b in gr} <= set(services.GRADED_MODELS)
        assert all(b["at"] == b["scored_at"] and b["result_src"] == "fd" and b["log_loss"] > 0 for b in gr)
        assert gr[0]["actual_outcome"] == "home_win"

        rec = check(recent_results())                                         # 列表：只评这两份存档的模型
        assert {b["match_id"] for b in rec} == {"soon"}
        assert [b["model_name"] for b in rec if b["kind"] == "grading"] == [PRIMARY]
        assert check(recent_results("D1")) == []
        with pytest.raises(ValueError):
            recent_results(days=15)


def test_explain_fixture(world):
    with use(world, world["now"]):
        bs = check(explain_fixture("E0", "A", "F"))
        assert len(bs) == 1 and bs[0]["kind"] == "live_calc" and bs[0]["match_id"] == "soon"
        b = bs[0]
        assert b["at"] == world["now"].isoformat() and b["odds_fetched_at"] == "now"   # 赛程表快照
        assert b["asian"]["line"] == -1.0 and b["odds_source"].startswith("赛程表")
        out = explain_fixture("英超", "A", "C")                                # 赛程表里没有这场
        assert check(out) == [] and "赛程表里没有" in out["note"]
        with pytest.raises(ValueError, match="找不到球队"):
            explain_fixture("E0", "Zebra", "F")
    with use(world, world["soon_ko"] + timedelta(minutes=1)):
        out = explain_fixture("E0", "A", "F")
        assert check(out) == [] and "get_match" in out["note"]                 # 开球后不现算


def test_scorecard_blocks(world):
    with use(world, world["now"]):
        out = scorecard()
        assert check(out) == [] and out["note"]                               # 还没有评分
    snap = json.loads(world["snap"].read_text(encoding="utf-8"))
    snap["scorecard"] = [{"model_name": PRIMARY, "model_ver": "9.9.9", "matches": 12, "log_loss": 0.98,
                          "brier": None, "diff_vs_base": -0.01, "se": 0.004}]
    world["snap"].write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    with use(world, world["now"]):
        bs = check(scorecard())
        assert len(bs) == 1 and bs[0]["scope"] == "scorecard" and bs[0]["kind"] == "scorecard"
        assert (bs[0]["model_name"], bs[0]["model_ver"], bs[0]["matches"]) == (PRIMARY, "9.9.9", 12)
        assert bs[0]["at"] == snap["generated_at"] and bs[0]["diff_vs_base"] == -0.01
        assert bs[0]["is_primary"] is True
        out = scorecard(closing=True)
        assert check(out) == [] and out["note"]                               # 快照里还没有对收盘的行
    snap["scorecard"].append({"model_name": version.MARKET_MODEL[0], "model_ver": "1.0.0", "matches": 12})
    snap["closing"] = [{"model_name": "closing_avg", "model_ver": "", "paired_n": 12, "log_loss": 0.95,
                        "diff_vs_close": 0.0, "se": 0.0},
                       {"model_name": PRIMARY, "model_ver": "9.9.9", "paired_n": 12, "log_loss": 0.98,
                        "diff_vs_close": 0.03, "se": 0.01}]
    world["snap"].write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    with use(world, world["now"]):
        assert [b["is_primary"] for b in check(scorecard())] == [True, False]
        cs = check(scorecard(closing=True))
        assert [b["kind"] for b in cs] == ["closing", "closing"] and cs[1]["diff_vs_close"] == 0.03
        assert [b["is_primary"] for b in cs] == [False, True]


def test_resolve_team_tiers(world):
    conn, now = world["conn"], world["now"]
    _fixture(conn, "ars", (now + timedelta(days=4)).isoformat(), "Arsenal", "Manchester Utd")
    _save(conn, world["db"])
    with use(world, now):
        def first(text, league=None):
            out = resolve_team(text, league)
            assert check(out) == []
            return [(c["team"], c["match"]) for c in out["candidates"]]
        assert first("Arsenal") == [("Arsenal", "exact")]
        assert first("man utd") == [("Manchester Utd", "alias")]               # 别名表，不分大小写
        assert first("arsen") == [("Arsenal", "partial")]
        assert first("Arsnal") == [("Arsenal", "close")]
        assert first("Arsenal", "D1") == []
        out = resolve_team("阿森纳")                                           # 中文名表未接入
        assert out["candidates"] == [] and "中文" in out["note"]
        assert resolve_team("A")["candidates"][0] == {"team": "A", "league": "E0", "league_name": "英超",
                                                      "match": "exact"}


def _lineups(path: pathlib.Path, now: datetime) -> None:
    """临时 fotmob 库：soon 两批阵容（旧批预测首发、新批正式首发 + 一名伤停）。"""
    c = fotmob.attach(sqlite3.connect(":memory:"), str(path))
    old, new = (now - timedelta(hours=2)).isoformat(), (now - timedelta(minutes=30)).isoformat()
    rows = [("soon", old, "predicted", "home", 1, "Old Keeper", "starter", 11, None, None),
            ("soon", new, "standard", "home", 2, "Home Keeper", "starter", 11, None, None),
            ("soon", new, "standard", "home", 3, "Home Sub", "sub", None, None, None),
            ("soon", new, "standard", "home", 4, "Home Injured", "unavailable", None, None, "knee"),
            ("soon", new, "standard", "away", 5, "Away Keeper", "starter", 11, None, None)]
    c.executemany("INSERT INTO fm.lineups VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()


def test_team_news(world):
    now = world["now"]
    with use(world, now):
        out = team_news("E0", "A")                                            # 没有 fotmob 库
        assert check(out) == [] and "阵容" in out["note"]
    _lineups(world["fm"], now)
    with use(world, now):
        bs = check(team_news("英超", "F"))
        assert len(bs) == 1 and bs[0]["kind"] == "team_news" and bs[0]["match_id"] == "soon"
        b = bs[0]
        assert (b["team"], b["team_side"], b["lineup_type"]) == ("F", "away", "standard")
        assert (b["home"], b["away"]) == ("A", "F")                             # 块头的对阵没被阵容覆盖
        assert b["at"] == b["fetched_at"] == (now - timedelta(minutes=30)).isoformat()   # 只取最新一批
        assert [p["name"] for p in b["lineups"]["home"]["starters"]] == ["Home Keeper"]
        assert b["lineups"]["home"]["unavailable"] == [{"name": "Home Injured", "position_id": None, "detail": "knee"}]
        assert [p["name"] for p in b["lineups"]["away"]["starters"]] == ["Away Keeper"]
        out = team_news("E0", "C")                                            # late 还没抓阵容
        assert check(out) == [] and out["note"]
        with pytest.raises(ValueError, match="找不到球队"):
            team_news("E0", "Zebra")
    with use(world, world["soon_ko"] + timedelta(minutes=1)):
        out = team_news("E0", "A")                                            # A 没有下一场了
        assert check(out) == [] and "尚未开球" in out["note"]


def test_kb_search_without_index_and_as_of(world):
    """索引没建（或 .venv 里没有 pymilvus）时返回空块和说明；as_of 规则与参数校验不依赖索引。
    真实检索、时点过滤和泄漏用例在 tests/test_agent_kb.py（需要 pymilvus）。"""
    later = datetime.fromisoformat("2026-11-01T00:00:00+00:00")
    with use(world, later):
        out = kb_search("亚盘怎么结算")
        assert check(out) == [] and out["note"] and out["query"] == "亚盘怎么结算"
        assert out["searched_as_of"] == later.isoformat()
        assert kb_search("x", as_of="2026-01-01")["searched_as_of"] == "2026-01-01T00:00:00+00:00"
        assert kb_search("x", as_of="2030-01-01")["searched_as_of"] == later.isoformat()   # 不超过调用时刻
        out = kb_search("x", match_id="soon", as_of="2030-01-01")             # 传 match_id：按开球前检索
        assert out["searched_as_of"] == world["soon_ko"].isoformat() and check(out) == []
        for bad in ({"k": 0}, {"k": 21}, {"scope": "all"}, {"match_id": "nope"}, {"query": " "}):
            with pytest.raises(ValueError):
                kb_search(**{"query": "x", **bad})
    with use(world, world["now"]):
        assert kb_search("x", match_id="soon")["searched_as_of"] == world["now"].isoformat()


def _md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


CALLS = {"list_upcoming": {}, "get_match": {"match_id": "soon"}, "recent_results": {"days": 14},
         "explain_fixture": {"league": "E0", "home": "A", "away": "F"}, "scorecard": {},
         "resolve_team": {"text": "A"}, "team_news": {"league": "E0", "team": "F"},
         "kb_search": {"query": "亚盘", "match_id": "soon"}}


def test_all_tools_read_only(world, tmp_path):
    """跑一遍全部工具（开球前、开球后各一次），库、快照、fotmob 库的 md5 都不变，也不留 -journal / -wal。"""
    _lineups(world["fm"], world["now"])
    files = (world["db"], world["snap"], world["fm"])
    before = {p.name: _md5(p) for p in files}
    assert set(CALLS) == {f.__name__ for f in TOOLS}
    for at in (world["now"], world["soon_ko"] + timedelta(hours=2)):
        with use(world, at):
            for f in TOOLS:
                check(f(**CALLS[f.__name__]))
            with config.connect() as conn, pytest.raises(sqlite3.OperationalError):
                conn.execute("DELETE FROM fixtures")                          # 连接本身就是只读
    after = {p.name: _md5(p) for p in files}
    assert after == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(("-journal", "-wal"))) == []
    print("md5", before)
