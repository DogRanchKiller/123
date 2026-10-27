"""
agent/kb/whitelist.py  读 whitelist.toml 并按 docs/agent-plan.md 第 7.2 节核对（不依赖 pymilvus）。
check(entries, root) 返回问题列表，空表示通过；tests/test_agent_kb_sources.py 和重建、增量更新之前都调它，
有问题时不建索引。
"""
import pathlib
import re
import subprocess
import tomllib
from dataclasses import dataclass, field

WHITELIST = pathlib.Path(__file__).with_name("whitelist.toml")
AUTHORITIES = ("rule", "status", "research", "record")
BASES = ("path", "dir", "script")
# 不收：密钥类、源代码、逐场 CSV / JSON、缓存和日志目录（第 7.2 节）
_DENY_NAMES = re.compile(r"^(\.env.*|servers\.txt)$|\.(pem|key|py|ts|tsx|js|mjs|cjs|bat|ps1|sh|sql|csv|json|db)$")
_DENY_DIRS = ("_cache/", "logs/", "node_modules/", ".venv", "checkpoints/", "agent_data/")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


@dataclass(frozen=True)
class Entry:
    path: str
    authority: str
    superseded: bool = False
    cited_in: str | None = None
    basis: str | None = None
    generated_by: str | None = None
    redirect: bool = False
    anchors: tuple[str, ...] = ()
    anchors_waived: str | None = None
    extra: dict = field(default_factory=dict, compare=False)


_FIELDS = {"path", "authority", "superseded", "cited_in", "basis", "generated_by", "redirect",
           "anchors", "anchors_waived"}


def load(path: pathlib.Path = WHITELIST) -> list[Entry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out = []
    for d in data.get("file", []):
        known = {k: (tuple(v) if k == "anchors" else v) for k, v in d.items() if k in _FIELDS}
        out.append(Entry(**known, extra={k: v for k, v in d.items() if k not in _FIELDS}))
    return out


def searchable(e: Entry) -> bool:
    """默认检索收不收这一条（record 只在 scope=handoff 时用，superseded 的研究结论跳过）。"""
    return not (e.authority == "research" and e.superseded)


def section(text: str, title: str) -> list[str]:
    """标题全文等于 title 的小节正文（到同级或更高级标题为止）；有几个就返回几个。"""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        m = _HEADING.match(lines[i])
        if m and m.group(2) == title:
            level, body, i = len(m.group(1)), [], i + 1
            while i < len(lines) and not ((h := _HEADING.match(lines[i])) and len(h.group(1)) <= level):
                body.append(lines[i])
                i += 1
            out.append("\n".join(body))
        else:
            i += 1
    return out


def _norm(s: str) -> str:
    return s.replace("−", "-")


def anchor_in(anchor: str, text: str) -> bool:
    """锚点原样出现（− 与 - 视为同一字符），前后不能紧挨数字或小数点（0.540 不算 0.5400 的一部分）。"""
    a = re.escape(_norm(anchor))
    return re.search(rf"(?<![\d.]){a}(?![\d])", _norm(text)) is not None


def committed(root: pathlib.Path, path: str) -> bool:
    r = subprocess.run(["git", "log", "-1", "--format=%H", "--", path], cwd=root,
                       capture_output=True, text=True, check=False)
    return r.returncode == 0 and bool(r.stdout.strip())


def denied(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return bool(_DENY_NAMES.search(name)) or path.startswith("web/.env") or any(
        path.startswith(d) or f"/{d}" in path for d in _DENY_DIRS)


def _check_research(e: Entry, root: pathlib.Path) -> list[str]:
    p = []
    for k in ("cited_in", "basis", "generated_by"):
        if not getattr(e, k):
            p.append(f"{e.path}: research 缺 {k}")
    if p:
        return p
    if e.basis not in BASES:
        return [f"{e.path}: basis 只能是 {'/'.join(BASES)}"]
    doc, _, title = e.cited_in.partition("#")
    if not title or not (root / doc).is_file():
        return [f"{e.path}: cited_in 要写成 文档路径#小节标题，且文档存在"]
    hits = section((root / doc).read_text(encoding="utf-8"), title)
    if len(hits) != 1:
        return [f"{e.path}: {doc} 里标题为「{title}」的小节有 {len(hits)} 个，要正好一个"]
    sec, fname = hits[0], e.path.rsplit("/", 1)[-1]
    gen_name = e.generated_by.rsplit("/", 1)[-1]
    folder = e.path.rsplit("/", 1)[0] + "/"
    ok = {"path": e.path in sec,
          "dir": folder in sec and (fname in sec or gen_name in sec),
          "script": gen_name in sec}[e.basis]
    if not ok:
        p.append(f"{e.path}: basis={e.basis} 在小节「{title}」里核对不通过")
    gen = root / e.generated_by
    if not gen.is_file():
        p.append(f"{e.path}: generated_by {e.generated_by} 不存在")
    elif not e.redirect and fname not in gen.read_text(encoding="utf-8", errors="replace"):
        p.append(f"{e.path}: 脚本 {e.generated_by} 里没有出现 {fname}（重定向输出要写 redirect = true）")
    if (root / e.path).is_file():
        body = (root / e.path).read_text(encoding="utf-8", errors="replace")
        miss = [a for a in e.anchors if not (anchor_in(a, sec) and anchor_in(a, body))]
        if miss:
            p.append(f"{e.path}: 锚点 {miss} 没有同时出现在小节和文件里")
        if len(e.anchors) - len(miss) < 2 and not e.anchors_waived:
            p.append(f"{e.path}: 有效锚点少于两个，也没有 anchors_waived")
    return p


def check(entries: list[Entry], root: pathlib.Path) -> list[str]:
    """五条核对（第 7.2 节）；返回问题列表，空表示通过。"""
    problems, seen = [], set()
    for e in entries:
        if e.path in seen:
            problems.append(f"{e.path}: 重复")
        seen.add(e.path)
        if any(c in e.path for c in "*?[") or e.path.startswith("/") or ".." in e.path.split("/"):
            problems.append(f"{e.path}: 要写完整相对路径，不能有通配符")
            continue
        if e.authority not in AUTHORITIES:
            problems.append(f"{e.path}: authority 只能是 {'/'.join(AUTHORITIES)}")
        if denied(e.path):
            problems.append(f"{e.path}: 在「不收」名单里")
        if not (root / e.path).is_file():
            problems.append(f"{e.path}: 不存在或不是文件")
        elif not committed(root, e.path):
            problems.append(f"{e.path}: git 里没有提交")
        if e.authority == "research":
            problems += _check_research(e, root)
    return problems
