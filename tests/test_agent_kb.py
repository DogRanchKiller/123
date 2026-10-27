"""知识库索引与 kb_search（agent/kb/index.py、build.py，agent/tools/knowledge.py），需要 pymilvus（.venv-ml）。
临时目录里的 Milvus Lite + 假向量（HashEmbedder），不加载 bge-m3；库用 test_agent_tools 的合成世界，
文档用固定提交时间的临时 git 仓库。核对 docs/agent-plan.md 第 7.1 节：文档按提交时间可见、未提交与白名单之外
不收、开球前检索看不到赛果、评分块三种改法在 --update 后的结果、来源标签随 as_of 变化。"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pymilvus")

from pymilvus.exceptions import MilvusException  # noqa: E402

from agent.kb import build, index  # noqa: E402
from agent.kb.embed import HashEmbedder  # noqa: E402
from agent.tools import kb_search  # noqa: E402
from agent.tools.blocks import parse_time  # noqa: E402
from football_prediction import version  # noqa: E402
from football_prediction.data import fotmob  # noqa: E402
from tests.test_agent_kb_sources import commit, git  # noqa: E402
from tests.test_agent_tools import _md5, _save, build_world, check, use  # noqa: E402

EMB = HashEmbedder()
PRIMARY = version.PRIMARY_MODEL[0]
T1, T2, T3 = "2026-10-01T00:00:00+00:00", "2026-10-05T00:00:00+00:00", "2026-10-09T00:00:00+00:00"
LATER = datetime(2027, 1, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)


@pytest.fixture
def kbw(league, tmp_path, monkeypatch):
    w = build_world(league, tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, {"rules.md": "# 结算\n\n亚盘走盘退还本金，旧口径甲乙丙。\n",
                  "other.md": "# 外面\n\n口径在白名单之外壬癸。\n"}, T1)
    commit(repo, {"rules.md": "# 结算\n\n亚盘走盘退还本金，新口径丁戊己。\n"}, T2)
    (repo / "rules.md").write_text("# 结算\n\n口径工作区未提交庚辛。\n", encoding="utf-8")
    (repo / "wl.toml").write_text('[[file]]\npath = "rules.md"\nauthority = "rule"\n', encoding="utf-8")
    return w | {"repo": repo, "wl": repo / "wl.toml", "kb": str(tmp_path / "kb")}


def kb(w, at, **kw):
    return use(w, at, **{"kb_path": w["kb"], "embedder": EMB, **kw})


def run(w, at, action):
    with kb(w, at):
        return build.run(action, w["repo"], w["wl"])


def visible(out: dict) -> list[dict]:
    """check + 泄漏检查：每块 available_at <= searched_as_of，且没被替代或替代晚于它。"""
    bs, t = check(out), parse_time(out["searched_as_of"])
    for b in bs:
        assert parse_time(b["at"]) <= t, b["chunk_id"]
        assert b["superseded_at"] is None or parse_time(b["superseded_at"]) > t, b["chunk_id"]
    return bs


def rows(w) -> dict[str, dict]:
    with index._client(w["kb"]) as c:
        return {r["chunk_id"]: r for r in index._all_rows(c, list(index._FIELDS), page=7)}


def test_doc_versions_whitelist_and_leaks(kbw):
    before = {p: _md5(kbw[p]) for p in ("db", "snap")}
    out = run(kbw, LATER, "rebuild")
    assert out["inserted"] == out["chunks"] > 0
    assert {p: _md5(kbw[p]) for p in ("db", "snap")} == before                 # 建索引只读库

    def docs(as_of=None):
        with kb(kbw, LATER):
            return " ".join(b["text"] for b in visible(kb_search("口径", k=20, as_of=as_of)) if b["family"] == "doc")
    assert docs("2026-09-30") == ""                                             # 第一次提交之前
    assert "甲乙丙" in docs("2026-10-03") and "丁戊己" not in docs("2026-10-03")
    assert "丁戊己" in docs() and "甲乙丙" not in docs()
    assert not any(w in docs() + docs("2026-10-03") for w in ("庚辛", "壬癸"))  # 未提交、白名单之外
    assert {r["meta"]["path"] for r in rows(kbw).values() if r["family"] == "doc"} == {"rules.md"}
    with kb(kbw, LATER):
        b = next(b for b in visible(kb_search("口径", k=20)) if b["family"] == "doc")
    assert (b["authority"], b["path"], b["heading"], b["at"]) == ("rule", "rules.md", "结算", T2)
    assert b["at_source"] == "git_commit" and len(b["commit"]) == 12

    assert run(kbw, LATER, "update")["inserted"] == 0                          # 没变化就不加
    commit(kbw["repo"], {"rules.md": "# 结算\n\n第三版口径子丑。\n"}, T3)
    out = run(kbw, LATER, "update")
    assert (out["inserted"], out["superseded"], out["deleted"]) == (1, 1, 0)
    assert "子丑" in docs() and "丁戊己" in docs("2026-10-06")
    total = len(rows(kbw))
    assert total == index.stats(kbw["kb"])["rows"] == len({*rows(kbw)})         # 分页取全、不重复

    kbw["wl"].write_text('[[file]]\npath = "rules.md"\nauthority = "rule"\n[[file]]\npath = "nope.md"\n'
                         'authority = "rule"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="nope.md"):
        run(kbw, LATER, "update")                                               # 白名单不通过不动索引
    assert len(rows(kbw)) == total
    kbw["wl"].write_text("", encoding="utf-8")
    assert run(kbw, LATER, "update")["deleted"] == 3                           # 移出白名单：文档块删掉


def _fm_result(w, mid: str, hg: int, ag: int, at: datetime) -> None:
    c = fotmob.attach(sqlite3.connect(":memory:"), str(w["fm"]))
    c.execute("INSERT INTO fm.fotmob_results VALUES (?,?,?,?,?,?)", (mid, 1, hg, ag, at.isoformat(), "t"))
    c.commit()
    c.close()


def _fd_result(w, mid: str, home: str, away: str, hg: int, ag: int, at: datetime) -> None:
    w["conn"].execute("INSERT INTO matches VALUES (?,'E0','2425',?,?,?,?,?,'test',?,'t')",
                      (mid, at.date().isoformat(), home, away, hg, ag, at.isoformat()))
    w["conn"].commit()
    _save(w["conn"], w["db"])


def _grade(w, mid: str, at: datetime | None = None, **cols) -> None:
    """直接改 predictions 的评分列（模拟 score_predictions / reconcile_results / _backfill_ah）。"""
    if at is not None:
        cols["scored_at"] = at.isoformat()
    sets = ", ".join(f"{k}=?" for k in cols)
    w["conn"].execute(f"UPDATE predictions SET {sets} WHERE match_id=?", (*cols.values(), mid))
    w["conn"].commit()
    _save(w["conn"], w["db"])


def grading(w, at, mid="soon") -> list[dict]:
    with kb(w, at):
        return [b for b in visible(kb_search("赛后评分 log loss", k=20)) if b["family"] == "grading"
                and b["match_id"] == mid and b["data"]["model_name"] == PRIMARY]


def test_match_chunks_and_pre_kickoff_search(kbw):
    ko = kbw["soon_ko"]
    _fm_result(kbw, "soon", 2, 1, ko + 2 * H)
    _grade(kbw, "soon", ko + 2.5 * H, result_src="fotmob", actual_outcome="home_win", log_loss=0.8, brier=0.5)
    run(kbw, ko + 3 * H, "rebuild")
    got = [r for r in rows(kbw).values() if r["match_id"] == "soon"]
    assert {"view", "first_archive", "score", "grading"} <= {r["family"] for r in got}
    for r in got:                    # 存档块不带按现在的规则现算的档位和稳妥线（存档行里没有）
        if r["family"] == "first_archive":
            body = r["meta"]["data"]
            assert "confidence" not in body and "稳妥线" not in r["text"] and "信心" not in r["text"]
            assert not body.get("asian") or "safe_line" not in body["asian"]
    with kb(kbw, ko + 3 * H):
        out = kb_search("比分 赛后评分 存档", k=20, match_id="soon")
        assert out["searched_as_of"] == ko.isoformat()
        bs = visible(out)
        assert {b["family"] for b in bs if b["family"] != "doc"} <= {"view", "first_archive", "near_archive"}
        assert {b["match_id"] for b in bs if b["family"] != "doc"} == {"soon"}
        assert all(parse_time(b["event_time"]) == ko for b in bs if b["family"] != "doc")
        later = visible(kb_search("比分 赛后评分", k=20))
        assert {"score", "grading"} <= {b["family"] for b in later}             # 不传 match_id：赛后可见
    with kb(kbw, ko + 3 * H, fotmob_path=str(kbw["fm"]) + ".missing"):
        assert [c for c in build.collect(kbw["repo"], kbw["wl"]) if c.family in ("score", "grading")] == []


def test_grading_result_src_only_and_backfill(kbw):
    ko = kbw["soon_ko"]
    _fm_result(kbw, "soon", 2, 1, ko + 2 * H)
    _grade(kbw, "soon", ko + 2.5 * H, result_src="fotmob", actual_outcome="home_win", log_loss=0.8, brier=0.5)
    run(kbw, ko + 3 * H, "rebuild")
    assert grading(kbw, ko + 2 * H) == []                                       # 评分之前看不到
    [g] = grading(kbw, ko + 3 * H)
    assert g["at"] == (ko + 2.5 * H).isoformat() and g["at_source"] == "predictions.scored_at"
    assert g["source_label"] == "FotMob，待 football-data 核对"
    assert g["data"]["score_used"] == {"home": 2, "away": 1} and "result_src" not in g["data"]
    assert "赛果 主胜" in g["text"]                                             # 正文用中文赛果，不是「赛果 -」

    # reconcile_results，两边比分相同：只改 result_src，scored_at 不变 → 不加评分块，只改元数据
    fd_at = ko + 24 * H
    _fd_result(kbw, "soon", "A", "F", 2, 1, fd_at)
    _grade(kbw, "soon", result_src="fd")
    gid = g["chunk_id"]
    out = run(kbw, fd_at + H, "update")
    assert out["inserted"] == 1 and out["superseded"] == 1 and out["updated"] >= 1   # fd 比分块；FotMob 块被替代
    r = rows(kbw)
    assert r[gid]["meta"]["result_src"] == "fd" and r[gid]["superseded_us"] == index.NEVER
    assert [x for x in r if x.startswith(f"grading:soon:{PRIMARY}:")] == [gid]
    fm_score = next(x for x in r.values() if x["family"] == "score" and x["meta"]["source"] == "fotmob")
    assert fm_score["superseded_us"] == index.to_us(fd_at)
    assert grading(kbw, ko + 3 * H)[0]["source_label"] == "FotMob，待 football-data 核对"
    assert grading(kbw, fd_at + H)[0]["source_label"] == "football-data"     # 同一块，标签按 as_of 现定

    # _backfill_ah：只补亚盘三列，scored_at 不变 → 新块，available_at 取发现时刻（index_detected）
    found = ko + 48 * H
    _grade(kbw, "soon", ah_line=-1.0, ah_log_loss=0.6, ah_hit=1.0)
    out = run(kbw, found, "update")
    assert out["inserted"] >= 1 and out["superseded"] >= 1
    [old] = grading(kbw, found - H)
    [new] = grading(kbw, found)
    assert old["chunk_id"] == gid and old["data"]["ah_line"] is None
    assert new["chunk_id"] != gid and new["data"]["ah_line"] == -1.0
    assert new["at"] == found.isoformat() and new["at_source"] == "index_detected"
    assert rows(kbw)[gid]["superseded_us"] == index.to_us(found)


def test_grading_rescored_when_scores_differ(kbw):
    ko = kbw["soon_ko"]
    _fm_result(kbw, "soon", 0, 0, ko + 2 * H)
    _grade(kbw, "soon", ko + 2.5 * H, result_src="fotmob", actual_outcome="draw", log_loss=1.2, brier=0.7)
    run(kbw, ko + 3 * H, "rebuild")
    fd_at, rescored = ko + 24 * H, ko + 30 * H
    _fd_result(kbw, "soon", "A", "F", 1, 0, fd_at)
    run(kbw, fd_at + H, "update")                                               # 重评之前
    assert grading(kbw, fd_at + H)[0]["source_label"] == "按 FotMob 比分评分，football-data 比分不同，待重评"
    assert grading(kbw, ko + 3 * H)[0]["source_label"] == "FotMob，待 football-data 核对"
    _grade(kbw, "soon", rescored, result_src="fd", actual_outcome="home_win", log_loss=0.6, brier=0.3)
    out = run(kbw, rescored + H, "update")
    assert out["inserted"] >= 1 and out["superseded"] >= 1
    [before] = grading(kbw, rescored - H)
    [after] = grading(kbw, rescored)
    assert before["data"]["actual_outcome"] == "draw" and after["data"]["actual_outcome"] == "home_win"
    assert "赛果 平" in before["text"] and "赛果 主胜" in after["text"]
    assert after["at"] == rescored.isoformat() and after["at_source"] == "predictions.scored_at"
    assert after["source_label"] == "football-data" and after["data"]["score_used"] == {"home": 1, "away": 0}


def test_kb_search_unavailable_busy_and_bad_ids(kbw, monkeypatch):
    with kb(kbw, LATER):
        out = kb_search("口径")
        assert check(out) == [] and "--rebuild" in out["note"]                  # 还没建
    run(kbw, LATER, "rebuild")
    with kb(kbw, LATER, embedder=HashEmbedder(32)):
        out = kb_search("口径")
        assert check(out) == [] and "--rebuild" in out["note"]                  # 向量函数不一致
    with pytest.raises(ValueError):
        index.check_match_id('x" or authority == "record')
    from pymilvus import MilvusClient
    c = MilvusClient(str(index._paths(kbw["kb"])[0]))
    c.release_collection(index.COLLECTION)                                       # 新进程打开时就是这个状态
    c.close()
    with kb(kbw, LATER):
        assert visible(kb_search("口径")) and index.stats(kbw["kb"])["rows"]

    monkeypatch.setattr(index, "OPEN_WAIT", 0)
    real, opened = index.MilvusClient, []

    def flaky(*a, **k):                     # 第一次打开失败（P3 评测里 gRPC too_many_pings），重试成功
        opened.append(1)
        if len(opened) == 1:
            raise MilvusException(message="Fail connecting to server")
        return real(*a, **k)
    monkeypatch.setattr(index, "MilvusClient", flaky)
    with kb(kbw, LATER):
        assert visible(kb_search("口径")) and len(opened) == 2

    def locked(*a, **k):
        raise MilvusException(message="Open local milvus failed")
    monkeypatch.setattr(index, "MilvusClient", locked)
    with kb(kbw, LATER):
        out = kb_search("口径")
        assert check(out) == [] and "另一个进程" in out["note"]
        with pytest.raises(index.KBBusy):
            build.run("update", kbw["repo"], kbw["wl"])
