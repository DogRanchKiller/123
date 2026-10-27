"""
agent/kb/sources.py  白名单文件 → 块（docs/agent-plan.md 第 7.1、7.2 节）。
- 内容一律用 git show <提交>:<路径> 取，工作区里未提交的改动不收。
- 沿 git log --first-parent 从旧到新逐个提交切块：同一段内容（路径 + 标题路径 + 正文的哈希）从出现的提交起
  可见（available_at = 该提交的提交时间，at_source = git_commit），到它被改掉或删掉的提交为止
  （superseded_at = 那个提交的时间）。所以 as_of 落在哪一版，就只看到那一版的内容。
- Markdown 按标题切节，每节约 1000 字以内（超长的按段落再分）；.txt / .log 按空行分段后同样打包。
Chunk 也是比赛类块（match_chunks.py）的格式，index.py 只认 Chunk。
"""
import hashlib
import pathlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.kb.whitelist import Entry

MAX_CHARS = 1000
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    chunk_id: str
    family: str                 # doc / view / first_archive / near_archive / score / grading / team_news
    key: str                    # 同一个东西的不同版本共用一个 key（文档：路径；评分：场次 + 模型 + 版本）
    authority: str              # rule / status / research / record；比赛类为 data
    text: str                   # 检索用的正文（向量和 BM25 都用它）
    available_at: datetime
    at_source: str
    superseded_at: datetime | None = None
    event_time: datetime | None = None
    match_id: str = ""
    meta: dict = field(default_factory=dict)


def _git(root: pathlib.Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True,
                       encoding="utf-8", errors="replace")
    return r.stdout


def history(root: pathlib.Path, path: str) -> list[tuple[str, datetime, str | None]]:
    """[(提交, 提交时间, 该提交时的内容；删掉时 None)]，从旧到新；只走第一父链（合并进来的分支按合并时刻算）。"""
    out, last = [], None
    for line in reversed(_git(root, "log", "--first-parent", "--format=%H %cI", "--", path).splitlines()):
        sha, ts = line.split(" ", 1)
        t = datetime.fromisoformat(ts).astimezone(timezone.utc)
        t = max(t, last) if last else t          # 提交时间偶有倒序（改写过的提交），按顺序取不早于上一个
        last = t
        try:
            body = _git(root, "show", f"{sha}:{path}")
        except subprocess.CalledProcessError:    # 这个提交里删掉了
            body = None
        out.append((sha, t, body))
    return out


def _pack(blocks: list[str]) -> list[str]:
    """段落按顺序拼成不超过 MAX_CHARS 的片；单段超长时按行切。"""
    parts, cur = [], ""
    for b in blocks:
        pieces = [b] if len(b) <= MAX_CHARS else _split_lines(b)
        for p in pieces:
            if cur and len(cur) + len(p) + 2 > MAX_CHARS:
                parts.append(cur)
                cur = ""
            cur = f"{cur}\n\n{p}" if cur else p
    return parts + ([cur] if cur else [])


def _split_lines(b: str) -> list[str]:
    """按行切；单行也超长时（如没有换行的长段）按 MAX_CHARS 硬切。"""
    out, cur = [], ""
    lines = [ln[i:i + MAX_CHARS] for ln in b.splitlines() for i in range(0, max(len(ln), 1), MAX_CHARS)]
    for ln in lines:
        if cur and len(cur) + len(ln) + 1 > MAX_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{ln}" if cur else ln
    return out + ([cur] if cur else [])


def _paragraphs(lines: list[str]) -> list[str]:
    """按空行分段；代码块里的空行不分。"""
    out, cur, fence = [], [], False
    for ln in lines:
        if _FENCE.match(ln):
            fence = not fence
        if not ln.strip() and not fence:
            if cur:
                out.append("\n".join(cur))
            cur = []
        else:
            cur.append(ln)
    return out + (["\n".join(cur)] if cur else [])


def split_markdown(text: str) -> list[tuple[str, str]]:
    """[(标题路径, 正文片)]；标题路径用 ' > ' 连各级标题，文件开头没有标题的部分为空串。只有标题的节不出块。"""
    out, stack, body, fence = [], [], [], False

    def flush():
        paras = _paragraphs(body)
        if paras:
            out.extend((" > ".join(t for _, t in stack), p) for p in _pack(paras))
        body.clear()

    for ln in text.splitlines():
        if _FENCE.match(ln):
            fence = not fence
        m = None if fence else _HEADING.match(ln)
        if m:
            flush()
            level = len(m.group(1))
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, m.group(2))]
        else:
            body.append(ln)
    flush()
    return out


def split_plain(text: str) -> list[tuple[str, str]]:
    return [("", p) for p in _pack(_paragraphs(text.splitlines()))]


def split(path: str, text: str) -> list[tuple[str, str]]:
    return split_markdown(text) if path.endswith(".md") else split_plain(text)


def _render(path: str, heading: str, body: str) -> str:
    return f"{path}" + (f" > {heading}" if heading else "") + f"\n{body}"


def doc_chunks(entry: Entry, root: pathlib.Path) -> list[Chunk]:
    """一个白名单文件全部版本的块。同一内容在一版里出现多次时按出现次序区分；内容删掉后又加回来算新的一段。"""
    out: list[Chunk] = []
    active: dict[str, Chunk] = {}                # 内容身份 → 当前还没被替代的块
    revived: dict[str, int] = {}
    for sha, t, body in history(root, entry.path):
        seen: dict[str, int] = {}
        now: dict[str, tuple[str, str, int]] = {}
        for i, (heading, piece) in enumerate(split(entry.path, body or "")):
            h = hashlib.sha1(f"{heading}\n{piece}".encode()).hexdigest()[:16]
            n = seen[h] = seen.get(h, -1) + 1
            now[f"{h}.{n}"] = (heading, piece, i)
        for ident in [k for k in active if k not in now]:
            active.pop(ident).superseded_at = t
        for ident, (heading, piece, i) in now.items():
            if ident in active:
                continue
            gen = revived[ident] = revived.get(ident, -1) + 1
            c = Chunk(chunk_id=f"doc:{entry.path}:{ident}" + (f".r{gen}" if gen else ""), family="doc",
                      key=entry.path, authority=entry.authority, text=_render(entry.path, heading, piece),
                      available_at=t, at_source="git_commit",
                      meta={"path": entry.path, "heading": heading, "commit": sha[:12], "order": i})
            active[ident] = c
            out.append(c)
    return out


def all_doc_chunks(entries: list[Entry], root: pathlib.Path) -> list[Chunk]:
    return [c for e in entries for c in doc_chunks(e, root)]
