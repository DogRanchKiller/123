"""Agent 的模块边界（docs/modules.md、docs/agent-dev.md 第 5 节），用 AST 扫描：
- football_prediction/ 和 server/ 不 import agent；
- agent/ 只 import 标准库、football_prediction.services / version、agent 自己、mcp、dotenv，不 import 领域包；
- agent/ 里没有 SQL 字符串，也不调用 .execute 系列（读库一律走 services）。"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_THIRD_PARTY = {"mcp", "dotenv"}
SQL_WORDS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "DROP ", "ATTACH ", "PRAGMA ")
EXEC_CALLS = {"execute", "executemany", "executescript"}


def _files(*dirs: str) -> list[pathlib.Path]:
    out = [p for d in dirs for p in (ROOT / d).rglob("*.py")]
    assert out, dirs
    return out


def _imports(tree: ast.AST) -> list[tuple[str, list[str], int]]:
    """(模块名, from 导入的名字, 相对层级)；import x 的名字列表为空。"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, [], 0) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append((n.module or "", [a.name for a in n.names], n.level))
    return out


def agent_import_ok(module: str, names: list[str], level: int) -> bool:
    top = module.split(".")[0]
    if level:                                           # 不用相对导入，边界一眼可查
        return False
    if module == "football_prediction":
        return bool(names) and set(names) <= {"services", "version"}
    if top == "football_prediction":
        return module in ("football_prediction.services", "football_prediction.version")
    return top in sys.stdlib_module_names or top == "agent" or top in AGENT_THIRD_PARTY


def sql_hits(tree: ast.AST) -> list[str]:
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if any(w in n.value.upper() for w in SQL_WORDS):
                hits.append(n.value[:40])
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in EXEC_CALLS:
            hits.append(f".{n.func.attr}()")
    return hits


def test_core_and_server_do_not_import_agent():
    bad = [f"{p.relative_to(ROOT)}: {m}" for p in _files("football_prediction", "server")
           for m, _, lvl in _imports(ast.parse(p.read_text(encoding="utf-8")))
           if lvl == 0 and m.split(".")[0] == "agent"]
    assert bad == []


def test_agent_imports_only_services_and_version():
    bad = [f"{p.relative_to(ROOT)}: {m} {names}" for p in _files("agent")
           for m, names, lvl in _imports(ast.parse(p.read_text(encoding="utf-8")))
           if not agent_import_ok(m, names, lvl)]
    assert bad == []


def test_agent_has_no_sql():
    bad = {str(p.relative_to(ROOT)): h for p in _files("agent")
           if (h := sql_hits(ast.parse(p.read_text(encoding="utf-8"))))}
    assert bad == {}


def test_scanners_catch_violations():
    """扫描器自己会报：领域包、整包 import、相对导入、SQL 字符串、execute 调用。"""
    assert not agent_import_ok("football_prediction.model_dc", ["fit"], 0)
    assert not agent_import_ok("football_prediction", ["review"], 0)
    assert not agent_import_ok("football_prediction.services.match_read", ["_PRE_KO"], 0)
    assert not agent_import_ok("pandas", [], 0) and not agent_import_ok("tools", ["x"], 1)
    assert agent_import_ok("football_prediction", ["services", "version"], 0)
    assert agent_import_ok("agent.tools.blocks", ["result"], 0) and agent_import_ok("datetime", [], 0)
    src = 'q = "select * from fixtures"\nconn.execute(q)\n'
    assert sql_hits(ast.parse(src)) == ["select * from fixtures", ".execute()"]
    assert sql_hits(ast.parse('note = "找不到比赛"\n')) == []
