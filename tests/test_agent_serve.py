"""agent/serve.py：网站对话服务（docs/agent-plan.md 第 10.4 节「共同」和 A 组里 Python 这边能测的项）。
FastAPI TestClient 直接调应用，不开端口；假模型按脚本吐消息，工具跑在 tests/test_agent_tools 的合成世界上；
用量库、状态库、访问库都在临时目录。不联网、不花钱。只在 .venv-ml 里跑。
网页那边的 Origin / Host / Cookie 属性在 web/ 的测试里（Vitest 与 e2e）。"""
import contextlib
import json
import sqlite3
from datetime import timedelta

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from agent import access, budget, config, graph, serve  # noqa: E402
from tests.test_agent_budget import Clock, ledger_paths  # noqa: E402
from tests.test_agent_graph import Script, bad, good, submit, tool  # noqa: E402
from tests.test_agent_llm import USAGE, status, timeout  # noqa: E402
from tests.test_agent_tools import world  # noqa: E402,F401  world 是夹具

TOKEN = "t" * 40
Q = "接下来 A 对 F 主队赢盘的概率是多少？"
PLAIN = submit("目前没有可以引用的数。", [])          # 没有数字的答案，一次就能通过


@pytest.fixture
def site(world, tmp_path):
    """make(*steps, **limits) → (client, model, cfg)。同一个测试里多次 make 共用同一组库（模拟重启）。"""
    clock = Clock(world["now"])
    paths = {"db_path": str(world["db"]), "snapshot_path": str(world["snap"]), "fotmob_path": str(world["fm"]),
             "kb_path": str(tmp_path / "kb-none"), "state_path": str(tmp_path / "state.db"),
             "access_path": str(tmp_path / "access.db"), **ledger_paths(tmp_path)}
    with contextlib.ExitStack() as stack:
        def make(*steps, token: str = TOKEN, **limits):
            cfg = stack.enter_context(config.override(**paths, limits=config.Limits(**limits), clock=clock))
            model = graph.Model(Script(*steps))
            app = serve.create_app(model, TOKEN, cfg, log=lambda m: None)
            client = stack.enter_context(TestClient(app, headers={"x-service-token": token}))
            return client, model.chat, cfg
        make.clock = clock
        yield make


def login(client, cfg, user: str = "alice") -> dict:
    code = access.add_user(user, cfg)
    r = client.post("/login", json={"code": code})
    assert r.status_code == 200
    return r.json()


def chat(client, who: dict, body: dict | None = None, **headers):
    h = {"x-session": who["session"], "x-csrf": who["csrf"], **headers}
    return client.post("/chat", json=body or {"question": Q}, headers=h)


def events(r) -> list[dict]:
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines()]


def rows(cfg, user: str | None = None) -> list[tuple]:
    try:
        with contextlib.closing(sqlite3.connect(cfg.usage_path)) as c:
            q = "SELECT tier, user, status, cost_usd FROM requests" + (" WHERE user = ?" if user else "")
            return c.execute(q, (user,) if user else ()).fetchall()
    except sqlite3.OperationalError:          # 还没建表：一笔都没有
        return []


def test_service_token_required(site):
    client, m, cfg = site(PLAIN)
    for token in ("", "x" * 40, TOKEN[:-1]):
        for method, path in (("post", "/chat"), ("post", "/login"), ("get", "/session"), ("post", "/logout")):
            r = getattr(client, method)(path, headers={"x-service-token": token})
            assert r.status_code == 401 and r.json()["reason"] == "service_token", (token, path)
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
    with pytest.raises(ValueError, match="32"):
        serve.create_app(graph.Model(Script()), "short", cfg)
    assert m.seen == [] and rows(cfg) == []


def test_user_id_in_body_is_ignored(site):
    client, _, cfg = site(PLAIN)
    alice = login(client, cfg)
    access.add_user("bob", cfg)
    ev = events(chat(client, alice, {"question": Q, "user": "bob", "user_id": "bob"}))
    assert ev[-1]["type"] == "done" and ev[-1]["outcome"] == "passed"
    assert rows(cfg, "bob") == [] and [r[:3] for r in rows(cfg)] == [("site", "alice", "settled")]


def test_binds_to_loopback_only(monkeypatch):
    """main() 只听 127.0.0.1，没有 --host 参数。"""
    import uvicorn
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setattr(serve.llm, "build", lambda s: graph.Model(Script()))
    monkeypatch.setattr(serve, "create_app", lambda *a, **k: object())
    monkeypatch.setattr(serve.budget.Budget, "worst_request", lambda self, est: 0.01)
    monkeypatch.setattr(serve.budget, "load_prices", lambda path: [])
    assert serve.main([]) == 0 and seen["host"] == "127.0.0.1" and seen["port"] == serve.PORT
    with pytest.raises(SystemExit):
        serve.main(["--host", "0.0.0.0"])


def test_refused_before_any_call_when_balance_short(site):
    client, m, cfg = site(PLAIN, budget_user_daily=1e-9)
    ev = events(chat(client, login(client, cfg)))
    assert ev[-1]["outcome"] == "refused" and m.seen == [] and rows(cfg) == []


def test_concurrency_429(site):
    client, m, cfg = site(PLAIN, PLAIN, concurrency=2)
    alice, bob, carol = (login(client, cfg, u) for u in ("alice", "bob", "carol"))
    hold = budget.Budget("fake", "fake", "alice", cfg, tier=budget.SITE)
    hold.acquire("held-a")
    r = chat(client, alice)
    assert r.status_code == 429 and r.json()["scope"] == "user"
    budget.Budget("fake", "fake", "bob", cfg, tier=budget.SITE).acquire("held-b")
    r = chat(client, carol)
    assert r.status_code == 429 and r.json()["scope"] == "site"
    assert m.seen == [] and rows(cfg) == []
    hold.release("held-a")
    assert events(chat(client, carol))[-1]["outcome"] == "passed"
    assert events(chat(client, carol))[-1]["outcome"] == "passed"        # 上一轮结束已释放
    assert chat(client, bob).status_code == 429


def test_slot_released_after_crash(site, monkeypatch):
    client, _, cfg = site(PLAIN)
    alice = login(client, cfg)
    real = graph.build
    monkeypatch.setattr(graph, "build", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    ev = events(chat(client, alice))
    assert ev == [{"type": "error", "thread_id": ev[0]["thread_id"], "error": "服务出错，这一轮没有完成"}]
    monkeypatch.setattr(graph, "build", real)
    assert events(chat(client, alice))[-1]["outcome"] == "passed"


def test_used_amount_survives_restart(site):
    client, _, cfg = site(PLAIN)
    alice = login(client, cfg)
    done = events(chat(client, alice))[-1]
    assert done["cost"] > 0 and done["quota"][0]["used"] == pytest.approx(done["cost"], abs=1e-4)
    client2, _, _ = site()
    after = client2.get("/session", headers={"x-session": alice["session"]}).json()
    assert after["quota"] == done["quota"] and after["user"] == "alice"


def test_twelve_timeouts_all_unknown(site):
    client, m, cfg = site(*[timeout() for _ in range(20)])
    done = events(chat(client, login(client, cfg)))[-1]
    got = rows(cfg)
    assert done["outcome"] == "error" and len(got) == 12 and {r[2] for r in got} == {"usage_unknown"}
    assert {r[0] for r in got} == {"site"} and len(m.seen) == 12


def test_429_then_retry_two_rows(site):
    client, _, cfg = site(status(429), PLAIN)
    done = events(chat(client, login(client, cfg)))[-1]
    assert done["outcome"] == "passed"
    assert [(r[2], r[3] == 0) for r in rows(cfg)] == [("failed", True), ("settled", False)]


def test_always_tools_six_calls(site):
    client, m, cfg = site(*[tool("list_upcoming", {}, f"c{i}") for i in range(1, 9)])
    ev = events(chat(client, login(client, cfg)))
    assert ev[-1]["outcome"] == "degraded" and len(m.seen) == 6 and len(rows(cfg)) == 6
    assert sum(len(e.get("tools", [])) for e in ev if e.get("node") == "tools") == 4 * 1


def test_second_bad_answer_degrades(site):
    client, m, cfg = site(bad("s1"), bad("s2"), PLAIN)
    done = events(chat(client, login(client, cfg)))[-1]
    assert done["outcome"] == "degraded" and len(m.seen) == 2 and len(m.steps) == 1


def test_csrf_and_format_rejected_without_reservation(site):
    client, m, cfg = site(PLAIN)
    alice, bob = login(client, cfg), login(client, cfg, "bob")
    h = {"x-session": alice["session"], "x-csrf": alice["csrf"]}
    assert chat(client, alice, **{"x-csrf": ""}).status_code == 403
    assert chat(client, alice, **{"x-csrf": bob["csrf"]}).status_code == 403            # 别的会话的令牌
    assert client.post("/chat", content=json.dumps({"question": Q}), headers={**h, "content-type": "text/plain"}
                       ).status_code == 415
    assert client.post("/chat", data={"question": Q}, headers=h).status_code == 415      # 表单
    assert client.post("/chat", json=[Q], headers=h).status_code == 415
    assert client.get("/chat", headers=h).status_code == 405
    site.clock.t += timedelta(seconds=access.CSRF_TTL + 1)
    fresh = client.get("/session", headers={"x-session": alice["session"]}).json()
    assert chat(client, alice).status_code == 403                                       # 过期令牌
    assert m.seen == [] and rows(cfg) == []
    assert events(chat(client, {**alice, "csrf": fresh["csrf"]}))[-1]["outcome"] == "passed"


def test_session_rejections(site):
    client, m, cfg = site(PLAIN)
    alice = login(client, cfg)
    assert client.post("/chat", json={"question": Q}, headers={"x-csrf": alice["csrf"]}).status_code == 401
    assert client.post("/login", json={"code": "wrong"}).status_code == 401
    assert client.post("/login", data={"code": "x"}).status_code == 415
    assert client.post("/logout", headers={"x-session": alice["session"]}).status_code == 204
    assert chat(client, alice).status_code == 401
    assert client.get("/session", headers={"x-session": alice["session"]}).status_code == 401
    bob = login(client, cfg, "bob")
    access.revoke_user("bob", cfg)
    assert chat(client, bob).status_code == 401
    carol = login(client, cfg, "carol")
    site.clock.t += timedelta(seconds=access.SESSION_TTL)
    assert chat(client, carol).status_code == 401
    assert m.seen == [] and rows(cfg) == []


def test_threads_are_per_user(site):
    client, m, cfg = site(PLAIN, PLAIN, PLAIN)
    alice, bob = login(client, cfg), login(client, cfg, "bob")
    tid = events(chat(client, alice))[-1]["thread_id"]
    assert events(chat(client, bob, {"question": "B 问", "thread_id": tid}))[-1]["thread_id"] == tid
    assert [x.content for x in m.seen[1][1:]] == ["B 问"]                               # 看不到 alice 的
    events(chat(client, alice, {"question": "追问", "thread_id": tid}))
    assert [x.content for x in m.seen[2][1:]][0] == Q and m.seen[2][-1].content == "追问"


def test_bad_input(site):
    client, m, cfg = site(PLAIN)
    alice = login(client, cfg)
    for body in ({"question": ""}, {"question": "x" * (serve.MAX_QUESTION + 1)}, {"question": Q, "thread_id": "../x"},
                 {"question": Q, "thread_id": 5}):
        assert chat(client, alice, body).status_code == 400, body
    assert m.seen == [] and rows(cfg) == []


def test_stream_and_session_shape(site):
    client, _, cfg = site(tool("list_upcoming", {"hours": 72}, "c1"), good())
    alice = login(client, cfg)
    assert set(alice) == {"session", "user", "expires", "csrf"}
    ev = events(chat(client, alice))
    assert [e["node"] for e in ev if e["type"] == "step"] == ["agent", "tools", "agent", "verify", "render"]
    assert ev[1]["tools"] == ["list_upcoming"] and ev[1]["label"] == "查数据"
    done = ev[-1]
    assert done["type"] == "done" and done["outcome"] == "passed" and "（时间均为北京时间）" in done["output"]
    assert [q["name"] for q in done["quota"]] == ["你今日的额度", "全站今日额度", "全站本月额度"]
    s = client.get("/session", headers={"x-session": alice["session"]}).json()
    assert s["user"] == "alice" and s["csrf"] and len(s["quota"]) == 3


def test_text_reply_is_not_an_answer(site):
    """模型直接回文字（不走 submit_answer）也不会把原文发给浏览器：只有 verify 过的或降级后的输出。"""
    client, _, cfg = site(*[AIMessage("秘密原文 123", usage_metadata=USAGE) for _ in range(8)])
    done = events(chat(client, login(client, cfg)))[-1]
    assert done["outcome"] == "degraded" and "秘密原文" not in done["output"]


def test_drain_sends_ping_when_idle(monkeypatch):
    """久无进度时插一行 ping，最后的 None 结束流。"""
    import queue as q
    monkeypatch.setattr(serve, "HEARTBEAT", 0.01)
    events_q: q.Queue = q.Queue()
    out = serve._drain(events_q)
    assert json.loads(next(out)) == {"type": "ping"}
    events_q.put({"type": "done"})
    events_q.put(None)
    assert json.loads(next(out)) == {"type": "done"}
    assert list(out) == []
