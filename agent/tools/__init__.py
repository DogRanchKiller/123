"""agent/tools/  只读工具（docs/agent-plan.md 第 6 节）。TOOLS 是对外暴露的全部工具，
MCP（agent/mcp_server.py）和以后的编排框架都包装这同一组函数，不写两份。"""
from agent.tools.knowledge import kb_search
from agent.tools.matches import (
    explain_fixture, get_match, list_upcoming, recent_results, resolve_team, scorecard, team_news,
)

TOOLS = (list_upcoming, get_match, recent_results, explain_fixture, scorecard, resolve_team,
         team_news, kb_search)

__all__ = ["TOOLS", *(f.__name__ for f in TOOLS)]
