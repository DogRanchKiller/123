"""
agent/mcp_server.py  用 MCP（stdio）暴露 agent/tools 的只读工具，给 Claude Code / Claude Desktop 用。
注册的就是 agent.tools.TOOLS 里的函数本身（工具名、参数和说明取自函数签名与 docstring），不另写一份；
只在外面包一层：工具的 ValueError（参数越界、找不到比赛 / 球队）转成 ToolError，让模型看到原因并改参数，
其他异常仍按崩溃处理（原文只留在服务端日志）。
本身不调大模型、不需要密钥；库只读打开。库路径见 agent/config.py（.env 的 AGENT_DB_PATH 等，默认仓库根目录）。

  .venv-ml/bin/python -m agent.mcp_server      # 在仓库根目录；stdout 是协议通道，不打印别的
"""
import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from agent.tools import TOOLS
from football_prediction import version

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _as_tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise ToolError(str(e)) from e
    return wrapper


def build_server() -> MCPServer:
    server = MCPServer(name="football-prediction", version=version.SYSTEM_VERSION,
                       instructions="足球预测系统的只读工具：本轮看法（亚盘为主）、存档、赛果、成绩单、阵容。"
                                    "概率和盘口只来自这些工具，不要自己估算。")
    for fn in TOOLS:
        server.add_tool(_as_tool(fn), annotations=READ_ONLY, structured_output=True)
    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
