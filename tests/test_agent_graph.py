"""agent/graph.py：第 8.1 节流程和计数上限（docs/agent-plan.md 第 8.5、10.4 节的必测项）。
假模型按脚本吐出工具调用和答案（脚本步骤可以是函数，按本轮工具结果现拼答案）；工具真的跑在
tests/test_agent_tools 的合成世界上；记账在临时目录的 usage.db。不联网、不花钱。只在 .venv-ml 里跑。"""
import hashlib
import json
from datetime import timedelta

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from agent import budget, config, graph, prompts  # noqa: E402
from agent.facts import FAILED, OMITTED  # noqa: E402
from football_prediction import version  # noqa: E402
from tests.test_agent_budget import ledger_paths  # noqa: E402
from tests.test_agent_llm import USAGE, Scripted, status, timeout  # noqa: E402
from tests.test_agent_tools import world  # noqa: E402,F401  world 是夹具

Q = "接下来 A 对 F 主队赢盘的概率是多少？"


class Script(Scripted):
    """步骤是函数时，用本次收到的消息现拼返回。"""

    def invoke(self, messages):
        if self.steps and callable(self.steps[0]) and not isinstance(self.steps[0], Exception):
            self.seen.append(list(messages))
            return self.steps.pop(0)(messages)
        return super().invoke(messages)


def tool(name: str, args: dict, cid: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": cid, "type": "tool_call"}],
                     usage_metadata=USAGE)


def submit(text: str, facts: list, sid: str = "s1") -> AIMessage:
    return tool(graph.SUBMIT, {"text": text, "facts": facts}, sid)


def result(messages, cid: str) -> dict:
    return json.loads(next(m.content for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == cid))


def fact(messages, cid: str, i: int = 0, sub: str = "/asian/p_cover", fid: str = "f1", **kw) -> dict:
    b = result(messages, cid)["blocks"][i]
    v = b
    for k in sub.strip("/").split("/"):
        v = v[k]
    unit = "prob" if "cover" in sub else "line"
    return {"id": fid, "scope": "match", "subject": b["match_id"], "tool_call_id": cid,
            "path": f"/blocks/{i}{sub}", "value": v, "unit": unit, "kind": b["kind"], "at": b["at"]} | kw


def good(cid: str = "c1", sid: str = "s1"):
    return lambda ms: submit("A 对 F 主队赢盘概率 {f1}。", [fact(ms, cid)], sid)


def bad(sid: str = "s0") -> AIMessage:
    return submit("一共有 2 场。", [], sid)


@pytest.fixture
def env(world, tmp_path):
    """(run, ledger)：run(*steps, **limits) 跑一轮，返回 (状态, 假模型)。"""
    made = {}

    def run(*steps, checkpointer=None, question=Q, thread=None, clock=None, **limits):
        paths = {"db_path": str(world["db"]), "snapshot_path": str(world["snap"]), "fotmob_path": str(world["fm"]),
                 "kb_path": str(tmp_path / "kb-none"), **ledger_paths(tmp_path)}
        clock = clock or (lambda: world["now"])
        with config.override(**paths, limits=config.Limits(**limits), clock=clock) as cfg:
            m = graph.Model(Script(*steps))
            made["ledger"] = budget.Budget("fake", "fake", cfg=cfg)
            app = graph.build(m, made["ledger"], checkpointer)
            return graph.ask(app, question, cfg.clock(), thread), m.chat
    return run, lambda: made["ledger"]


def counts(s: dict) -> tuple:
    return s["model_calls"], s["tool_rounds"], s["answers"], s["http"]


def test_pass_first_try(env, world):
    run, ledger = env
    s, m = run(tool("list_upcoming", {"hours": 72}, "c1"), good())
    assert s["outcome"] == "passed" and counts(s) == (2, 1, 1, 2)
    assert s["output"].startswith("A 对 F 主队赢盘概率 ") and "（本轮看法，" in s["output"]
    assert s["output"].endswith("（时间均为北京时间）")
    assert [b["match_id"] for b in s["tool_log"]["c1"]["blocks"]] == ["soon", "late"]     # 工具真的跑了
    assert s["trace"] == [{"name": "list_upcoming", "args": {"hours": 72}}]
    assert "北京时间" in m.seen[0][0].content and m.seen[0][1].content == Q                # 系统提示现拼
    assert result(m.seen[1], "c1")["tool_call_id"] == "c1"
    rows = ledger().turn_rows(s["turn_id"])
    assert [(r["call_index"], r["attempt"], r["status"]) for r in rows] == [(1, 1, "settled"), (2, 1, "settled")]
    assert s["usage"] == {"input_tokens": 200, "output_tokens": 40}


def test_retry_then_pass(env):
    run, _ = env
    s, m = run(tool("list_upcoming", {}, "c1"), bad(), good(sid="s2"))
    assert s["outcome"] == "passed_retry" and counts(s)[:3] == (3, 1, 2)
    note = next(x.content for x in m.seen[2] if isinstance(x, ToolMessage) and x.tool_call_id == "s0")
    assert "没有通过校验" in note and "第 1 条" in note
    assert [[i["rule"] for i in v] for v in s["verify_log"]] == [[1], []]


def test_degrade_after_two_bad_answers(env):
    run, _ = env
    s, _ = run(tool("list_upcoming", {}, "c1"), bad("s0"), bad("s1"))
    assert s["outcome"] == "degraded" and s["answers"] == 2 and s["model_calls"] == 3
    assert s["output"].startswith(FAILED) and "A 对 F" in s["output"] and "2" not in s["output"]


def test_degrade_keeps_only_checked_facts(env):
    """第 2 次提交里一条事实对、一条编造：降级表只有对的那条，没有模型的成段文字。"""
    run, _ = env

    def mixed(ms):
        return submit("赢盘 {f1}，另外 {f2}。", [fact(ms, "c1"), fact(ms, "c1", fid="f2", value=0.99)], "s1")
    s, _ = run(tool("list_upcoming", {}, "c1"), bad("s0"), mixed)
    assert s["outcome"] == "degraded"
    assert s["output"].startswith(OMITTED) and "| A 对 F |" in s["output"]
    assert "99" not in s["output"] and "另外" not in s["output"]


def test_tool_round_cap(env):
    """第 5 次提议工具不执行，回一句「工具次数已用完」；第 6 次调用提交答案。"""
    run, _ = env
    s, m = run(*[tool("list_upcoming", {}, f"c{i}") for i in range(1, 6)], good("c1"))
    assert s["outcome"] == "passed" and counts(s)[:3] == (6, 4, 1)
    assert "c5" not in s["tool_log"] and len(s["tool_log"]) == 4
    assert any(isinstance(x, ToolMessage) and x.content == graph.NO_MORE_TOOLS for x in m.seen[5])


def test_always_tools_stops_at_six_calls(env):
    """假模型一直要工具：执行 4 轮，第 5、6 次的提议不执行，第 6 次之后不再调用；用量库正好 6 笔。"""
    run, ledger = env
    s, m = run(*[tool("list_upcoming", {}, f"c{i}") for i in range(1, 9)])
    assert counts(s) == (6, 4, 0, 6) and s["outcome"] == "degraded"
    assert len(m.seen) == 6 and len(m.steps) == 2
    assert len(ledger().turn_rows(s["turn_id"])) == 6
    assert s["output"].startswith(FAILED)


def test_format_errors_count_as_calls(env):
    """一直直接回文字：每次补一句催它用 submit_answer，6 次后降级；没有工具结果时只回一句。"""
    run, _ = env
    s, m = run(*[AIMessage("好的", usage_metadata=USAGE) for _ in range(8)])
    assert counts(s) == (6, 0, 0, 6) and s["output"] == FAILED and s["outcome"] == "degraded"
    assert m.seen[1][-1].content == graph.NUDGE


def test_truncated_reply_gets_its_own_nudge(env):
    """输出到长度上限被截断成空（思考占满 max_tokens）：回一句「被截断，少想直接提交」，不是普通的催促。"""
    run, _ = env
    cut = AIMessage("", usage_metadata=USAGE, response_metadata={"finish_reason": "length"})
    s, m = run(tool("list_upcoming", {}, "c1"), cut, good())
    assert s["outcome"] == "passed" and counts(s)[:3] == (3, 1, 1)
    assert m.seen[2][-1].content == graph.TRUNCATED


def test_invalid_submit_args_then_pass(env):
    run, _ = env
    broken = AIMessage("", invalid_tool_calls=[{"name": graph.SUBMIT, "args": "{text:", "id": "s0",
                                                "error": "bad json", "type": "invalid_tool_call"}],
                       usage_metadata=USAGE)
    s, m = run(tool("list_upcoming", {}, "c1"), broken, good())
    assert s["outcome"] == "passed" and counts(s)[:3] == (3, 1, 1)
    assert m.seen[2][-1].content == graph.BAD_ARGS
    assert not any(getattr(x, "invalid_tool_calls", None) for x in m.seen[2])


def test_bad_answer_on_sixth_call_degrades(env):
    """4 轮工具 + 1 次超限提议 + 第 6 次才交答案且没通过：不再重答，直接降级。"""
    run, _ = env
    s, m = run(*[tool("list_upcoming", {}, f"c{i}") for i in range(1, 6)], bad(), good())
    assert counts(s)[:3] == (6, 4, 1) and s["outcome"] == "degraded" and len(m.steps) == 1


def test_all_timeouts_twelve_unknown(env):
    """每个请求都超时：6 次调用 × 2 个请求 = 12 笔预留，全部 usage_unknown 记全额。"""
    run, ledger = env
    s, m = run(*[timeout() for _ in range(20)])
    assert counts(s) == (6, 0, 0, 12) and s["outcome"] == "error" and s["output"] == FAILED
    rows = ledger().turn_rows(s["turn_id"])
    assert len(rows) == 12 and {r["status"] for r in rows} == {"usage_unknown"}
    assert all(r["cost_usd"] == r["reserved_usd"] > 0 for r in rows) and len(m.steps) == 8


def test_429_then_retry_two_rows(env):
    run, ledger = env
    s, _ = run(status(429), tool("list_upcoming", {}, "c1"), good())
    assert s["outcome"] == "passed" and counts(s) == (2, 1, 1, 3)
    rows = ledger().turn_rows(s["turn_id"])
    assert [(r["call_index"], r["attempt"], r["status"], r["cost_usd"] == 0) for r in rows][:2] == [
        (1, 1, "failed", True), (1, 2, "settled", False)]


def test_http_cap_limits_retries(env):
    """HTTP 上限 3：第 2 次调用首发超时后只剩 1 个请求，用完就停。"""
    run, ledger = env
    s, _ = run(tool("list_upcoming", {}, "c1"), timeout(), timeout(), good(), http=3)
    assert s["http"] == 3 and s["model_calls"] == 2 and s["outcome"] == "error"
    assert len(ledger().turn_rows(s["turn_id"])) == 3


def test_refused_reservation_degrades_without_calling(env):
    run, ledger = env
    s, m = run(good(), budget_personal_daily=1e-9)
    assert s["outcome"] == "refused" and counts(s) == (0, 0, 0, 0) and m.seen == []
    assert "额度" in s["error"] and ledger().turn_rows(s["turn_id"]) == []


def test_non_retryable_error(env):
    run, _ = env
    s, _ = run(status(400))
    assert s["outcome"] == "error" and counts(s) == (1, 0, 0, 1)


def test_snapshot_after_kickoff_cannot_be_current(env, world):
    """开球后快照看法改标 last_pre_kickoff：照抄成 current 被打回，按块里的 kind 重交才通过。"""
    run, _ = env
    after = world["soon_ko"] + timedelta(minutes=5)

    def wrong(ms):
        return submit("A 对 F 赢盘 {f1}。", [fact(ms, "c1", kind="current")], "s0")
    s, _ = run(tool("get_match", {"match_id": "soon"}, "c1"), wrong, good(), clock=lambda: after)
    assert s["outcome"] == "passed_retry" and 5 in [i["rule"] for i in s["verify_log"][0]]
    assert "开球前最后一轮看法" in s["output"]


def test_turn_timeout(env, world):
    t = [world["now"]]

    def tick():
        t[0] += timedelta(seconds=100)
        return t[0]
    run, _ = env
    s, _ = run(*[tool("list_upcoming", {}, f"c{i}") for i in range(1, 9)], clock=tick, turn_timeout=250)
    assert s["outcome"] == "timeout" and s["model_calls"] < 6


def test_thread_follow_up_requires_new_query(env, tmp_path):
    """同一 thread 追问：上一轮只留问题和输出；引用上一轮的 tool_call_id 被打回，重新查才通过。"""
    run, _ = env
    with graph.saver(str(tmp_path / "state.db")) as ck:
        s1, _ = run(tool("list_upcoming", {}, "c1"), good(), checkpointer=ck, thread="t1")
        stale = submit("A 对 F 主队赢盘概率 {f1}。", [{**s1["answer"]["facts"][0]}], "s0")
        s2, m = run(stale, tool("list_upcoming", {}, "c2"), good("c2", "s2"), checkpointer=ck, thread="t1",
                    question="再说一遍？")
    assert s1["outcome"] == "passed" and s2["outcome"] == "passed_retry"
    assert 3 in [i["rule"] for i in s2["verify_log"][0]]
    first = m.seen[0]
    assert [type(x).__name__ for x in first[1:]] == ["HumanMessage", "AIMessage", "HumanMessage"]
    assert first[2].content == s1["output"] and first[3].content == "再说一遍？"
    assert [type(x).__name__ for x in s2["messages"]] == ["HumanMessage", "AIMessage"] * 2


def test_tools_are_read_only(env, world):
    before = hashlib.md5(world["db"].read_bytes()).hexdigest()
    run, _ = env
    run(tool("list_upcoming", {}, "c1"), tool("get_match", {"match_id": "soon"}, "c2"),
        tool("scorecard", {}, "c3"), good())
    assert hashlib.md5(world["db"].read_bytes()).hexdigest() == before


def test_unknown_tool_and_bad_args_go_back_to_model(env):
    run, _ = env
    s, m = run(tool("drop_table", {}, "c0"), tool("get_match", {"match_id": "nope"}, "c1"),
               tool("list_upcoming", {}, "c2"), good("c2"))
    assert s["outcome"] == "passed" and s["tool_rounds"] == 3
    replies = [x.content for x in m.seen[3] if isinstance(x, ToolMessage)]
    assert replies[0].startswith("工具出错：没有这个工具") and "找不到比赛" in replies[1]


def test_oversized_tool_result_is_withheld(env):
    """一轮工具返回超过 tool_tokens：那次调用不交给模型、不进 tool_log，模型缩小范围再查。"""
    run, _ = env
    s, m = run(tool("list_upcoming", {}, "c1"), tool("list_upcoming", {"hours": 24}, "c2"), good("c2"),
               tool_tokens=700)                           # 合成世界里 72 小时约 900，24 小时约 500
    reply = next(x.content for x in m.seen[1] if isinstance(x, ToolMessage) and x.tool_call_id == "c1")
    assert reply.startswith("工具出错：返回太大") and "c1" not in s["tool_log"]
    assert s["outcome"] == "passed" and s["tool_log"]["c2"]["blocks"][0]["match_id"] == "soon"


def test_max_input_bound():
    lim = config.Limits()
    assert graph.max_input(lim) > lim.tool_rounds * lim.tool_tokens


def test_system_prompt_lists_fields():
    from datetime import datetime, timezone
    p = prompts.system(datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc))
    assert "北京时间 2026-10-27 09:00" in p and "/asian/line line" in p and "kb_number" in p
    assert "FIELD_TABLE" not in p and "ALLOW_WORDS" not in p and "上半场" in p
    # 主模型名从 version 现拼，不写死；对收盘参照的字段在表里
    assert "PRIMARY_" not in p and f"主模型是 {version.PRIMARY_MODEL[0]}" in p and "/diff_vs_close ll_diff" in p
    assert isinstance(HumanMessage(p), HumanMessage)
