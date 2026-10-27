"""MCP 暴露（agent/mcp_server.py）：进程内客户端列工具、调工具；stdio 子进程能启动并按环境变量找库。
只在 .venv-ml 里跑（没有 mcp 时整个文件跳过）。"""
import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from agent.mcp_server import build_server  # noqa: E402
from agent.tools import TOOLS, list_upcoming  # noqa: E402
from tests.test_agent_tools import use, world  # noqa: E402,F401  world 是夹具


ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=60))


def test_in_process_tools_match_functions(world):
    async def go():
        async with Client(build_server()) as c:
            tools = (await c.list_tools()).tools
            ok = await c.call_tool("list_upcoming", {"hours": 72})
            bad = await c.call_tool("get_match", {"match_id": "nope"})
            oob = await c.call_tool("list_upcoming", {"hours": 9999})
            return tools, ok, bad, oob

    with use(world, world["now"]):
        tools, ok, bad, oob = _run(go())
        direct = list_upcoming(hours=72)
    assert [t.name for t in tools] == [f.__name__ for f in TOOLS]
    for t in tools:
        a = t.annotations
        assert a.read_only_hint is True and a.destructive_hint is False and a.open_world_hint is False
        assert t.description and t.output_schema and t.input_schema["type"] == "object"
    assert ok.is_error is False and ok.structured_content == direct          # 同一个函数
    assert [b["match_id"] for b in ok.structured_content["blocks"]] == ["soon", "late"]
    assert bad.is_error is True and "找不到比赛 nope" in bad.content[0].text     # 原因交给模型
    assert oob.is_error is True and "超出范围" in oob.content[0].text


def test_stdio_server_starts(world):
    """真实子进程：python -m agent.mcp_server，库路径走环境变量（真实时钟，合成比赛早已开球）。"""
    env = {"AGENT_DB_PATH": str(world["db"]), "AGENT_SNAPSHOT_PATH": str(world["snap"]),
           "AGENT_FOTMOB_PATH": str(world["fm"]), "PYTHONPATH": ROOT,
           "PYTHONIOENCODING": "utf-8"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent.mcp_server"],
                                   env=env, cwd=ROOT)

    async def go():
        async with Client(params) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            return names, await c.call_tool("get_match", {"match_id": "soon"})

    names, r = _run(go())
    assert names == [f.__name__ for f in TOOLS]
    kinds = [b["kind"] for b in r.structured_content["blocks"]]
    assert r.is_error is False and kinds == ["last_pre_kickoff", "first_archive"]
    assert world["soon_ko"] < datetime.now(timezone.utc) - timedelta(days=1)
