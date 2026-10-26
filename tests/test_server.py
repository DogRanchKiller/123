"""只读接口 server/：三个 GET（列表附带最近已开球场次）、无快照 503、未知比赛 404、只读连接、OpenAPI 与 web/openapi.json 一致。
离线：合成比赛跑一轮写临时快照，库是临时文件，不碰 football.db。"""
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from football_prediction import version  # noqa: E402
from server.app import create_app, openapi_text  # noqa: E402
from tests.test_report_live import _fixture  # noqa: E402
from tests.test_services import _round  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def served(league, tmp_path, monkeypatch):
    """(client, db 文件路径, 快照路径)：一轮实盘后把内存库存成文件，快照里的开球时间挪到未来。"""
    conn, cutoff = league
    now = datetime.fromisoformat(cutoff + "T10:00:00+00:00")
    _fixture(conn, "f1", (now + timedelta(hours=5)).isoformat())
    _fixture(conn, "noodds", (now + timedelta(days=1)).isoformat(), "B", "E",
             avg_h=None, avg_d=None, avg_a=None, avg_over25=None, avg_under25=None, ah_line=None)
    _, snap = _round(conn, now, tmp_path, monkeypatch)
    db = tmp_path / "served.db"
    out = sqlite3.connect(db)
    conn.backup(out)
    out.close()
    data = json.loads(pathlib.Path(snap).read_text(encoding="utf-8"))
    for m in data["matches"]:                    # 接口按真实当前时间剔除已开球场次
        m["kickoff_utc"] = "2099" + m["kickoff_utc"][4:]
    pathlib.Path(snap).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return TestClient(create_app(str(db), snap, fotmob_path=None)), db, snap


def test_list_matches(served):
    client, _, _ = served
    r = client.get("/api/matches")
    assert r.status_code == 200
    body = r.json()
    assert body["primary_model"]["name"] == version.PRIMARY_MODEL[0]
    assert [m["match_id"] for m in body["matches"]] == ["f1", "noodds"]
    f1, no = body["matches"]
    assert f1["asian"]["line_source"] == "市场线" and f1["model_name"] == version.PRIMARY_MODEL[0]
    assert no["asian"]["tier"] == "-" and no["model_name"] == version.FALLBACK_MODEL[0]


def test_list_recent_param(served):
    client, _, _ = served
    assert isinstance(client.get("/api/matches").json()["recent"], list)
    assert client.get("/api/matches?recent_days=0").json()["recent"] == []
    assert client.get("/api/matches?recent_days=99").status_code == 422     # 上限 14 天


def test_match_detail_and_404(served):
    client, _, _ = served
    d = client.get("/api/matches/f1").json()
    assert d["match"]["home"] == "A" and d["current"]["match_id"] == "f1"
    assert d["archived"]["model_name"] == version.PRIMARY_MODEL[0]
    assert d["archived"]["asian"]["line"] == -1.0 and d["archived"]["scored"] is False
    r = client.get("/api/matches/not-a-match")
    assert r.status_code == 404 and r.json()["detail"] == "找不到这场比赛"


def test_review(served):
    client, _, _ = served
    r = client.get("/api/review")
    assert r.status_code == 200 and r.json()["scorecard"] == []     # 合成库还没有评分


def test_no_snapshot_is_503(tmp_path, served):
    _, db, _ = served
    client = TestClient(create_app(str(db), str(tmp_path / "none.json")))
    assert client.get("/api/matches").status_code == 503
    assert client.get("/api/review").status_code == 503
    missing = TestClient(create_app(str(tmp_path / "none.db"), str(tmp_path / "none.json")))
    assert missing.get("/api/matches/f1").status_code == 503
    assert not (tmp_path / "none.db").exists()                   # 只读打开，不新建库


def test_routes_are_read_only(served):
    client, db, _ = served
    before = db.read_bytes()
    for path in ("/api/matches", "/api/matches/f1", "/api/review"):
        client.get(path)
    assert db.read_bytes() == before
    assert client.post("/api/matches").status_code == 405


def test_openapi_file_matches_app():
    """前端类型由 web/openapi.json 生成；改了接口要重新导出：python -m server --openapi web/openapi.json"""
    committed = (ROOT / "web" / "openapi.json").read_text(encoding="utf-8")
    assert committed == openapi_text(), "web/openapi.json 过期，运行 python -m server --openapi web/openapi.json"


def test_server_only_calls_services():
    for p in (ROOT / "server").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.startswith(("import ", "from ")) and "football_prediction" in line:
                assert line.startswith(("from football_prediction import services",
                                        "from football_prediction import services, version")), (p, line)
        assert "execute(" not in src, p                         # 路由不写 SQL
