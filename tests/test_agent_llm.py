"""agent/llm.py：配置读取与摘要（不含密钥）、错误分类、一次模型调用的重试与逐请求预留 / 结算。
OpenAI 兼容接口用 httpx.MockTransport 模拟，不联网、不花钱。只在 .venv-ml 里跑（没有 langchain_openai 时跳过）。"""
import json

import pytest

pytest.importorskip("langchain_openai")

import httpx  # noqa: E402
import openai  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from agent import budget, config, llm  # noqa: E402
from tests.test_agent_budget import MON_NIGHT, ledger_paths  # noqa: E402

REQ = httpx.Request("POST", "http://relay.test/v1/chat/completions")
USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
SETTINGS = {"AGENT_PROVIDER": "openai_compat", "AGENT_MODEL": "m-test", "AGENT_BASE_URL": "http://relay.test/v1",
            "OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": ""}


def timeout() -> Exception:
    return openai.APITimeoutError(request=REQ)


def status(code: int) -> Exception:
    cls = {429: openai.RateLimitError, 500: openai.InternalServerError, 503: openai.InternalServerError,
           400: openai.BadRequestError, 401: openai.AuthenticationError}[code]
    return cls(f"http {code}", response=httpx.Response(code, request=REQ), body=None)


def refused() -> Exception:
    e = openai.APIConnectionError(request=REQ)
    e.__cause__ = httpx.ConnectError("refused")
    return e


class Scripted:
    """按顺序吐出消息或抛出异常；bind_tools 原样返回自己。图测试也用它。"""

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def bind_tools(self, tools, **kw):
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def fake_model(*steps) -> llm.Model:
    return llm.Model(Scripted(*steps))


@pytest.fixture
def ledger(tmp_path):
    """在临时目录记账（provider / model 都是 fake），时钟固定在非倍率时段。"""
    with config.override(**ledger_paths(tmp_path), clock=lambda: MON_NIGHT) as cfg:
        yield budget.Budget("fake", "fake", cfg=cfg)


def caller(model: llm.Model, ledger: budget.Budget) -> llm.Caller:
    def noop() -> str:
        """占位工具。"""
        return ""
    return llm.Caller(model, [noop], ledger)


def run(c: llm.Caller, turn: str = "t", call: int = 1) -> AIMessage:
    return c.call([HumanMessage("你好")], turn_id=turn, call_index=call)


def states(ledger: budget.Budget, turn: str = "t") -> list[tuple[str, str | None]]:
    return [(r["status"], r["reason"]) for r in ledger.turn_rows(turn)]


@pytest.mark.parametrize("err, expect", [
    (timeout(), ("usage_unknown", True, "timeout")),
    (status(429), ("failed", True, "429")),
    (status(500), ("usage_unknown", True, "500")),
    (status(503), ("usage_unknown", True, "503")),
    (status(400), ("failed", False, "400")),
    (status(401), ("failed", False, "401")),
    (refused(), ("failed", False, "connect")),
    (openai.APIConnectionError(request=REQ), ("usage_unknown", False, "connection")),
    (ValueError("parse"), ("usage_unknown", False, "ValueError")),
])
def test_classify(err, expect):
    assert llm.classify(err) == expect


def test_success_settles_actual(ledger):
    msg = run(caller(fake_model(AIMessage("ok", usage_metadata=USAGE)), ledger))
    assert msg.content == "ok"
    [row] = ledger.turn_rows("t")
    assert (row["status"], row["input_tokens"], row["output_tokens"]) == ("settled", 100, 20)
    assert row["cost_usd"] == pytest.approx((100 * 1.0 + 20 * 2.0) / 1e6)


def test_429_then_retry_ok(ledger):
    c = caller(fake_model(status(429), AIMessage("ok", usage_metadata=USAGE)), ledger)
    run(c)
    rows = ledger.turn_rows("t")
    assert [(r["attempt"], r["status"]) for r in rows] == [(1, "failed"), (2, "settled")]
    assert rows[0]["cost_usd"] == 0 and c.requests == 2


def test_two_timeouts_exhaust_the_call(ledger):
    c = caller(fake_model(timeout(), timeout()), ledger)
    with pytest.raises(llm.ModelError) as e:
        run(c)
    assert e.value.retryable and c.requests == 2
    rows = ledger.turn_rows("t")
    assert states(ledger) == [("usage_unknown", "timeout")] * 2
    assert all(r["cost_usd"] == r["reserved_usd"] > 0 for r in rows)


@pytest.mark.parametrize("err", [status(400), refused(), openai.APIConnectionError(request=REQ)])
def test_no_retry_on_other_errors(ledger, err):
    c = caller(fake_model(err, AIMessage("never")), ledger)
    with pytest.raises(llm.ModelError) as e:
        run(c)
    assert not e.value.retryable and c.requests == 1 and len(ledger.turn_rows("t")) == 1


def test_missing_usage_is_unknown(ledger):
    run(caller(fake_model(AIMessage("ok")), ledger))
    [row] = ledger.turn_rows("t")
    assert (row["status"], row["reason"], row["cost_usd"]) == ("usage_unknown", "no usage", row["reserved_usd"])


def test_refused_reservation_sends_nothing(tmp_path):
    lim = config.Limits(budget_personal_daily=1e-9)
    with config.override(**ledger_paths(tmp_path), limits=lim, clock=lambda: MON_NIGHT) as cfg:
        model = fake_model(AIMessage("never"))
        c = caller(model, budget.Budget("fake", "fake", cfg=cfg))
        with pytest.raises(budget.Refused):
            run(c)
        assert model.chat.seen == [] and c.requests == 0


def test_estimate_counts_tools_and_calls():
    msgs = [HumanMessage("主队"), AIMessage("", tool_calls=[{"name": "x", "args": {"q": "abcd" * 10}, "id": "1"}])]
    assert llm.estimate(msgs, []) > llm.estimate(msgs[:1], [])
    assert llm.estimate(msgs, [{"name": "y" * 400}]) > llm.estimate(msgs, [])


def completion(text: str) -> dict:
    return {"id": "x", "object": "chat.completion", "created": 0, "model": "m-test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                      "prompt_tokens_details": {"cached_tokens": 40}}}


def mock(script: list) -> tuple[list, httpx.MockTransport]:
    """script 每项：int 状态码（错误响应）、'timeout'（传输层超时）或 dict（正常响应）。"""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        step = script[len(seen) - 1]
        if step == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        if isinstance(step, int):
            return httpx.Response(step, json={"error": {"message": "x"}})
        return httpx.Response(200, json=step)
    return seen, httpx.MockTransport(handler)


def test_openai_compat_over_mock_transport(tmp_path):
    """真的走 ChatOpenAI → openai SDK → httpx，只换传输层：首个请求 429，重试成功；SDK 自己不重试。"""
    seen, transport = mock([429, completion("好")])
    with config.override(**ledger_paths(tmp_path), clock=lambda: MON_NIGHT) as cfg:
        m = llm.build(SETTINGS, transport)
        ledger = budget.Budget(m.provider, m.name, cfg=cfg)
        msg = run(caller(m, ledger))
    assert msg.content == "好" and m.http.n == len(seen) == 2
    rows = ledger.turn_rows("t")
    assert [(r["status"], r["cost_usd"]) for r in rows][0] == ("failed", 0)
    assert (rows[1]["status"], rows[1]["input_tokens"], rows[1]["cache_read_tokens"]) == ("settled", 100, 40)
    body = json.loads(seen[-1].content)
    assert body["model"] == "m-test" and body["temperature"] == 0
    assert (body.get("max_completion_tokens") or body.get("max_tokens")) == cfg.limits.max_tokens
    assert seen[-1].headers["authorization"] == "Bearer sk-test"


def test_openai_compat_timeouts_over_mock_transport(tmp_path):
    seen, transport = mock(["timeout", "timeout", completion("never")])
    with config.override(**ledger_paths(tmp_path), clock=lambda: MON_NIGHT) as cfg:
        m = llm.build(SETTINGS, transport)
        ledger = budget.Budget(m.provider, m.name, cfg=cfg)
        with pytest.raises(llm.ModelError):
            run(caller(m, ledger))
    assert len(seen) == 2 and states(ledger) == [("usage_unknown", "timeout")] * 2


def test_settings_env_over_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AGENT_PROVIDER=openai_compat\nAGENT_MODEL=from-file\nOPENAI_API_KEY=sk-file\nOTHER=x\n",
                   encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)
    for k in llm.KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENT_MODEL", "from-env")
    s = llm.settings()
    assert (s["AGENT_MODEL"], s["OPENAI_API_KEY"], s["AGENT_BASE_URL"]) == ("from-env", "sk-file", "")
    assert "OTHER" not in s
    d = llm.describe(s)
    assert d["key_set"] is True and "sk-file" not in json.dumps(d)
    for bad in ({**SETTINGS, "AGENT_BASE_URL": ""}, {**SETTINGS, "AGENT_PROVIDER": "x"},
                {**SETTINGS, "AGENT_MODEL": ""}, {**SETTINGS, "AGENT_PROVIDER": "anthropic"}):
        with pytest.raises(ValueError):
            llm.build(bad, limits=config.Limits())


def test_limits_from_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AGENT_MAX_MODEL_CALLS=4\nAGENT_BUDGET_PERSONAL_DAILY=0.5\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MAX_HTTP", "8")
    lim = config.load_config(env).limits
    assert (lim.model_calls, lim.http, lim.budget_personal_daily, lim.tool_rounds) == (4, 8, 0.5, 4)
    for bad in ("0", "-1", "x"):
        monkeypatch.setenv("AGENT_MAX_HTTP", bad)
        with pytest.raises(ValueError, match="AGENT_MAX_HTTP"):
            config.load_config(env)
