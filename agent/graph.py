"""
agent/graph.py  Agent 图（docs/agent-plan.md 第 8.1 节），LangGraph：
  START → agent ─工具调用→ tools → agent …
            └─submit_answer→ verify ─通过→ render ─┐
                               ├─不通过且能重答→ agent（附逐条错误）
                               └─否则→ degrade ──┴→ finish → END
- 四个计数各自累加、各自判定：model_calls ≤ 6（每次调模型前先查；超限的工具提议、格式错误、重试用完的失败都算）、
  tool_rounds ≤ 4、answers ≤ 2（含首次）、HTTP ≤ 12（每次模型调用 ≤ 2）。budget.py 预留时另外自己查
  model_calls 和 HTTP，两边任一到上限就停。上限在 config.Limits（.env 可改）。
- 模型通过 submit_answer 工具交 {text, facts}，不依赖提供方的 response_format；verify / render / degrade 在 agent/facts。
- 系统提示每次调模型时现拼（agent/prompts.py，带当时的北京时间），不存进对话。
- 对话状态：同一 thread_id 由 checkpointer（SqliteSaver，agent_data/state.db）保存。每轮结束时 finish 把本轮的工具往来
  删掉，只留「问题 + 最终输出」，所以追问时之前的工具结果模型看不到，必须重新查（verify 也只认本轮的调用）。
- outcome：passed / passed_retry / degraded（校验没过或次数用完）/ error（模型调用失败）/ refused（额度或上限拒绝预留）
  / timeout（单轮总超时）。
"""
import contextlib
import json
import pathlib
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent import budget, facts, prompts
from agent.llm import ATTEMPTS, Caller, Model, ModelError
from agent.tools import TOOLS

SUBMIT = "submit_answer"
NO_MORE_TOOLS = "工具次数已用完，没有执行。请直接用 submit_answer 提交答案。"
NUDGE = "请用 submit_answer 工具提交答案，不要直接回复文字。"
BAD_ARGS = "submit_answer 的参数不是合法的 JSON 对象，请重新提交：{text: 字符串, facts: 列表}。"
NOT_RUN = "未执行：同一条消息里有 submit_answer，其他工具调用不执行。"
TRUNCATED = "上一次输出到了长度上限被截断，什么也没交上来。少想，直接用 submit_answer 提交简短的答案。"


class State(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    turn_id: str
    thread_id: str | None
    started: float                 # 本轮开始（UTC 时间戳）
    model_calls: int
    tool_rounds: int
    answers: int
    http: int                      # 本轮实际发出的 HTTP 请求（含失败）
    usage: dict[str, int]
    tool_log: dict[str, dict]      # 本轮 tool_call_id → 工具原始返回
    trace: list[dict]              # 本轮工具调用：名字和参数（评测用）
    answer: Any
    verify_log: list[list[dict]]   # 每次提交的校验结果（评测用）
    error: str
    output: str
    outcome: str
    route: str


def submit_answer(text: str, facts: list[dict[str, Any]]) -> str:
    """提交最终答案。text：给用户看的中文，所有数都写成 {f1} 这样的占位；facts：每个占位对应的事实。"""
    return "已提交"


def _tools() -> dict[str, StructuredTool]:
    return {t.name: t for t in (StructuredTool.from_function(f) for f in (*TOOLS, submit_answer))}


def _replies(msg: AIMessage, text: str, skip: str | None = None) -> list[ToolMessage]:
    """给一条 AI 消息里的每个工具调用补一条回复（接口要求一一对应），skip 是要另外回复的那个调用 id。"""
    return [ToolMessage(text, tool_call_id=c["id"]) for c in msg.tool_calls if c["id"] != skip]


def _usage(old: dict | None, msg: AIMessage) -> dict:
    u = dict(old or {"input_tokens": 0, "output_tokens": 0})
    for k in u:
        u[k] += int((msg.usage_metadata or {}).get(k) or 0)
    return u


def _turn_messages(messages: list[BaseMessage], turn_id: str) -> list[BaseMessage]:
    """本轮问题之后的消息（含问题）。"""
    start = next(i for i, m in enumerate(messages) if m.id == f"q-{turn_id}")
    return messages[start:]


def start(question: str, now: datetime, thread_id: str | None = None) -> dict:
    """一轮的初始输入：本轮计数清零；之前几轮的问题和输出由 checkpointer 带着。"""
    turn = uuid.uuid4().hex[:12]
    return {"messages": [HumanMessage(question, id=f"q-{turn}")], "turn_id": turn, "thread_id": thread_id,
            "started": now.timestamp(), "model_calls": 0, "tool_rounds": 0, "answers": 0, "http": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0}, "tool_log": {}, "trace": [], "answer": None,
            "verify_log": [], "error": "", "output": "", "outcome": ""}


def build(model: Model, ledger: budget.Budget, checkpointer=None):
    """编译图。ledger 决定记账库、价格表、上限和时钟（ledger.cfg）。"""
    cfg, lim = ledger.cfg, ledger.cfg.limits
    tools = _tools()
    caller = Caller(model, list(tools.values()), ledger)

    def agent(s: State) -> dict:
        now = cfg.clock()
        if s["model_calls"] >= lim.model_calls or s["http"] >= lim.http:
            return {"route": "degrade"}
        if now.timestamp() - s["started"] > lim.turn_timeout:
            return {"route": "degrade", "outcome": "timeout"}
        calls, before = s["model_calls"] + 1, caller.requests
        prompt = [SystemMessage(prompts.system(now)), *s["messages"]]
        try:
            msg = caller.call(prompt, turn_id=s["turn_id"], call_index=calls, thread_id=s.get("thread_id"),
                              attempts=min(ATTEMPTS, lim.http - s["http"]))
        except budget.Refused as e:
            out = {"model_calls": calls if caller.requests > before else s["model_calls"]}
            return out | {"http": s["http"] + caller.requests - before, "route": "degrade", "outcome": "refused",
                          "error": str(e)}
        except ModelError as e:
            out = {"model_calls": calls, "http": s["http"] + caller.requests - before, "error": str(e)}
            if e.retryable:                      # 这次调用的 2 次都失败了：算一次调用，回到 agent 再判上限
                return out | {"route": "agent"}
            return out | {"route": "degrade", "outcome": "error"}
        out: dict = {"model_calls": calls, "http": s["http"] + caller.requests - before,
                     "usage": _usage(s.get("usage"), msg), "messages": [msg]}
        if any(c.get("name") == SUBMIT for c in msg.invalid_tool_calls):
            fixed = AIMessage(msg.content or "", id=msg.id)          # 坏掉的调用不发回给提供方
            return out | {"messages": [fixed, HumanMessage(BAD_ARGS)], "route": "agent"}
        if subs := [c for c in msg.tool_calls if c["name"] == SUBMIT]:
            return out | {"answer": subs[-1]["args"], "answers": s["answers"] + 1, "route": "verify"}
        if msg.tool_calls:
            if s["tool_rounds"] >= lim.tool_rounds:
                return out | {"messages": [msg, *_replies(msg, NO_MORE_TOOLS)], "route": "agent"}
            return out | {"route": "tools"}
        meta = msg.response_metadata or {}
        cut = meta.get("finish_reason") == "length" or meta.get("stop_reason") == "max_tokens"
        return out | {"messages": [msg, HumanMessage(TRUNCATED if cut else NUDGE)], "route": "agent"}

    def run_tools(s: State) -> dict:
        """执行这一轮的工具。返回总量超过 lim.tool_tokens 的调用不交给模型（也不进 tool_log），让它缩小范围。"""
        msg: AIMessage = s["messages"][-1]
        log, trace, replies, used = dict(s["tool_log"]), list(s["trace"]), [], 0
        for c in msg.tool_calls:
            trace.append({"name": c["name"], "args": c["args"]})
            tool = tools.get(c["name"])
            try:
                if tool is None:
                    raise ValueError(f"没有这个工具：{c['name']}")
                res = tool.func(**c["args"])
                text = json.dumps({"tool_call_id": c["id"], **res}, ensure_ascii=False, separators=(",", ":"))
                if used + (n := budget.tokens(text)) > lim.tool_tokens:
                    text = (f"工具出错：返回太大（约 {n} token，本轮还剩 {lim.tool_tokens - used}），没有交给你。"
                            "请缩小范围再查：加 league 参数，或减少 days / hours。")
                else:
                    used += n
                    log[c["id"]] = res
            except (ValueError, TypeError, KeyError, LookupError) as e:      # 参数错：原因交给模型
                text = f"工具出错：{e}"
            replies.append(ToolMessage(text, tool_call_id=c["id"]))
        return {"messages": replies, "tool_log": log, "trace": trace, "tool_rounds": s["tool_rounds"] + 1}

    def verify(s: State) -> dict:
        issues = facts.verify(s["answer"], s["tool_log"])
        vlog = [*s["verify_log"], [{"rule": i.rule, "fact": i.fact, "message": i.message} for i in issues]]
        if not issues:
            return {"verify_log": vlog, "route": "render"}
        msg: AIMessage = s["messages"][-1]
        sub_id = [c for c in msg.tool_calls if c["name"] == SUBMIT][-1]["id"]
        if s["answers"] < lim.answers and s["model_calls"] < lim.model_calls and s["http"] < lim.http:
            note = "答案没有通过校验，请改正后重新提交：\n" + "\n".join(
                f"- 第 {i.rule} 条{f'（{i.fact}）' if i.fact else ''}：{i.message}" for i in issues)
            return {"verify_log": vlog, "route": "agent",
                    "messages": [*_replies(msg, NOT_RUN, sub_id), ToolMessage(note, tool_call_id=sub_id)]}
        return {"verify_log": vlog, "route": "degrade"}

    def render(s: State) -> dict:
        return {"output": facts.render(s["answer"], s["tool_log"], cfg.clock()),
                "outcome": "passed" if s["answers"] == 1 else "passed_retry"}

    def degrade(s: State) -> dict:
        outcome = s.get("outcome") or ("error" if s.get("error") and not s["answers"] else "degraded")
        return {"output": facts.degrade(s.get("answer"), s["tool_log"], cfg.clock()), "outcome": outcome}

    def finish(s: State) -> dict:
        """本轮只留问题和最终输出（工具往来、催促、打回说明都删掉）。"""
        drop = [RemoveMessage(id=m.id) for m in _turn_messages(s["messages"], s["turn_id"])[1:]]
        return {"messages": [*drop, AIMessage(s["output"], id=f"a-{s['turn_id']}")]}

    g = StateGraph(State)
    for name, fn in (("agent", agent), ("tools", run_tools), ("verify", verify), ("render", render),
                     ("degrade", degrade), ("finish", finish)):
        g.add_node(name, fn)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", lambda s: s["route"], ["agent", "tools", "verify", "degrade"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("verify", lambda s: s["route"], ["agent", "render", "degrade"])
    g.add_edge("render", "finish")
    g.add_edge("degrade", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


def max_input(lim) -> int:
    """单次请求输入的上界估计：系统提示 + 工具说明 + 各轮工具返回的上限 + 历次提交与打回说明。
    不含之前几轮对话（每轮只留问题和输出）和问题本身，调用方另加。"""
    from langchain_core.utils.function_calling import convert_to_openai_tool
    schemas = json.dumps([convert_to_openai_tool(t) for t in _tools().values()], ensure_ascii=False)
    base = budget.tokens(prompts.system(datetime.now())) + budget.tokens(schemas)
    return base + lim.tool_rounds * lim.tool_tokens + lim.answers * lim.max_tokens * 2


def ask(app, question: str, now: datetime, thread_id: str | None = None) -> dict:
    """跑一轮，返回结束时的状态。没有 checkpointer 时 thread_id 只记进用量库。"""
    conf = {"configurable": {"thread_id": thread_id or "-"}, "recursion_limit": 60}
    return app.invoke(start(question, now, thread_id), conf)


@contextlib.contextmanager
def saver(path: str) -> Iterator[Any]:
    """对话状态库（SqliteSaver）；用完关闭。"""
    from langgraph.checkpoint.sqlite import SqliteSaver
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()
