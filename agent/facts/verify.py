"""
agent/facts/verify.py  结构化答案的校验（docs/agent-plan.md 第 8.3 节第 1–8 条）。
模型提交 {text, facts}：text 里的数一律写成占位 {f1}…；每条事实给出 id、scope、subject、tool_call_id、
path（该次工具返回里的 JSON Pointer，指向某一块里的字段）、value、unit、kind、at；scope=kb 另带 quote。
tool_log 是本轮 tools 节点真实记录过的调用：{tool_call_id: 工具返回}。
verify() 返回 Issue 列表（空 = 通过），message 是给模型看的中文，打回时附上让它改。
"""
import re
from dataclasses import dataclass

from agent.facts import numbers, units

FACT_KEYS = ("id", "scope", "subject", "tool_call_id", "path", "value", "unit", "kind", "at")
PLACEHOLDER = re.compile(r"\{(f\d+)\}")
_BLOCK_PATH = re.compile(r"/blocks/(\d+)(/.+)")
_ENTITY_KEYS = {"home", "away", "team", "league", "league_name", "model_name", "name"}


@dataclass(frozen=True)
class Issue:
    rule: int                 # 第 8.3 节的条目号
    fact: str | None          # 相关事实的 id；整段文字的问题为 None
    message: str


def pointer(doc, path: str):
    """按 JSON Pointer 取值；取不到时抛 LookupError。"""
    if not path.startswith("/"):
        raise LookupError(path)
    cur = doc
    for raw in path[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            if not tok.isdigit() or int(tok) >= len(cur):
                raise LookupError(path)
            cur = cur[int(tok)]
        elif isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        else:
            raise LookupError(path)
    return cur


def subject_of(block: dict) -> str | None:
    """块的主体键，写成事实的 subject：match → match_id；scorecard → 模型名@版本；kb → chunk_id。"""
    if block.get("scope") == "match":
        return block.get("match_id")
    if block.get("scope") == "scorecard":
        return f"{block.get('model_name')}@{block.get('model_ver')}"
    if block.get("scope") == "kb":
        return block.get("chunk_id")
    return None


def _walk(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _ENTITY_KEYS and isinstance(v, str):
                out.add(v)
            else:
                _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def entities(tool_log: dict) -> set[str]:
    """工具结果里原样出现的实体名（队名、联赛、模型名、球员名，含 resolve_team 的候选）：第 1 条放行用。"""
    out: set[str] = set()
    _walk(tool_log, out)
    return out


def _match_blocks(tool_log: dict):
    """所有带对阵的块：scope=match 的块，以及知识库里比赛类块的 data。"""
    for res in tool_log.values():
        for b in res.get("blocks", []):
            if b.get("scope") == "match":
                yield b
            elif b.get("scope") == "kb" and isinstance(b.get("data"), dict):
                yield b["data"]


def teams_in(text: str, names: set[str]) -> set[str]:
    """text 里出现的队名（长的先认，认过的位置遮掉，免得 Sp Lisbon 里再认出 Lisbon）。"""
    found = set()
    for n in sorted((n for n in names if n), key=len, reverse=True):
        pat = re.escape(n)
        if n[0].isascii() and n[0].isalnum():
            pat = r"(?<![A-Za-z0-9])" + pat
        if n[-1].isascii() and n[-1].isalnum():
            pat += r"(?![A-Za-z0-9])"
        if re.search(pat, text):
            found.add(n)
            text = re.sub(pat, numbers.MASK, text)
    return found


def locate(fact: dict, tool_log: dict) -> tuple[dict, str] | None:
    """事实指向的块和块内路径；path 不是 /blocks/<i>/… 或块不存在时 None。"""
    m = _BLOCK_PATH.fullmatch(str(fact.get("path", "")))
    res = tool_log.get(fact.get("tool_call_id"))
    if not m or res is None:
        return None
    blocks = res.get("blocks", [])
    i = int(m[1])
    return (blocks[i], m[2]) if i < len(blocks) else None


def check_fact(f: dict, tool_log: dict) -> list[Issue]:
    """单条事实的第 3–7 条。降级输出也用它挑出能核对的事实。"""
    fid = f.get("id")
    if f["tool_call_id"] not in tool_log:
        avail = "、".join(sorted(tool_log)) or "无"
        return [Issue(3, fid, f"事实 {fid} 的 tool_call_id {f['tool_call_id']} 不是本轮调用过的工具（可用：{avail}）")]
    loc = locate(f, tool_log)
    if loc is None:
        n = len(tool_log[f["tool_call_id"]].get("blocks", []))
        return [Issue(5, fid, f"事实 {fid} 的 path {f['path']} 要落在某一块里，写成 JSON Pointer "
                              f"/blocks/<序号>/<字段>（如 /blocks/0/asian/line，不用 blocks[0].x），"
                              f"这次工具返回的序号只有 0–{n - 1}" if n else
                              f"事实 {fid} 的 path {f['path']} 指向的工具返回里没有块，不能引用")]
    block, sub = loc
    out = []
    if block.get("scope") != f["scope"] or subject_of(block) != f["subject"]:
        out.append(Issue(5, fid, f"事实 {fid} 的 scope / subject 与该块不符（该块是 {block.get('scope')} "
                                 f"{subject_of(block)}）"))
    if block.get("kind") != f["kind"]:
        out.append(Issue(5, fid, f"事实 {fid} 的 kind 写成 {f['kind']}，该块是 {block.get('kind')}"))
    if units.parse_dt(f["at"]) is None or units.parse_dt(f["at"]) != units.parse_dt(block.get("at")):
        out.append(Issue(5, fid, f"事实 {fid} 的 at 与该块的 at 不符（该块是 {block.get('at')}）"))
    reg = units.field(str(block.get("scope")), sub)
    if reg is None:
        return out + [Issue(6, fid, f"事实 {fid} 的字段 {sub} 不在单位对照表里，不能引用；换一个可引用的字段")]
    unit, _ = reg
    if f["unit"] != unit:
        out.append(Issue(6, fid, f"事实 {fid} 的单位写成 {f['unit']}，字段 {sub} 的单位是 {unit}"))
    try:
        tool_value = pointer(block, sub)
    except LookupError:
        return out + [Issue(4, fid, f"事实 {fid} 的 path {f['path']} 在工具结果里取不到值")]
    if unit == "kb_number":
        quote = f.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            out.append(Issue(7, fid, f"知识库事实 {fid} 要带 quote（片段原文里的一句）"))
        elif quote not in str(tool_value):
            out.append(Issue(7, fid, f"知识库事实 {fid} 的 quote 不在该片段原文里，要原样照抄"))
        elif units.kb_literal(quote, f["value"]) is None:
            out.append(Issue(7, fid, f"知识库事实 {fid} 的 value {f['value']} 不在 quote 里"))
    elif not units.same(unit, tool_value, f["value"]):
        out.append(Issue(4, fid, f"事实 {fid} 的 value 是 {f['value']}，工具结果里是 {tool_value}；原样照抄"))
    return out


def _shape(answer) -> tuple[str, list] | Issue:
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        return Issue(2, None, "答案要有 text（字符串）和 facts（列表）")
    facts = answer.get("facts")
    if facts is None:
        facts = []
    if not isinstance(facts, list):
        return Issue(2, None, "facts 要是列表")
    return answer["text"], facts


def verify(answer, tool_log: dict) -> list[Issue]:
    shape = _shape(answer)
    if isinstance(shape, Issue):
        return [shape]
    text, facts = shape
    out: list[Issue] = []
    bare = PLACEHOLDER.sub(numbers.MASK, text)
    if stray := re.findall(r"[{｛][^{}｛｝]*[}｝]", bare):
        out.append(Issue(2, None, "text 里有不合格式的占位：" + "、".join(stray) + "（只能写 {f1}、{f2}…）"))
    if hits := numbers.find_numbers(bare, entities(tool_log)):
        out.append(Issue(1, None, "text 里出现了数字或数字写法：" + "、".join(hits)
                         + "。所有数（含中文数字、英文数词、盘口名）都写成占位 {fN}，值放进 facts"))
    if re.search(r"\{f\d+\}\s*[%％]", text):
        out.append(Issue(2, None, "占位后面不要写 %：概率由系统按工具结果格式化"))
    good = [f for f in facts if isinstance(f, dict)]
    if len(good) != len(facts):
        out.append(Issue(2, None, "facts 的每一项都要是对象"))
    ids = [f.get("id") for f in good]
    used = PLACEHOLDER.findall(text)
    if dup := sorted({str(i) for i in ids if ids.count(i) > 1}):
        out.append(Issue(2, None, "facts 的 id 重复：" + "、".join(dup)))
    if missing := sorted(set(used) - set(ids)):
        out.append(Issue(2, None, "text 里的占位没有对应的事实：" + "、".join(missing)))
    if unused := sorted({str(i) for i in ids} - set(used)):
        out.append(Issue(2, None, "这些事实没有在 text 里引用：" + "、".join(unused)))
    allowed = set()
    for f in good:
        if lack := [k for k in FACT_KEYS if k not in f]:
            out.append(Issue(2, f.get("id"), f"事实 {f.get('id')} 缺字段：" + "、".join(lack)))
            continue
        issues = check_fact(f, tool_log)
        out += issues
        if not issues and f["scope"] == "match" and (loc := locate(f, tool_log)):
            allowed |= {loc[0].get("home"), loc[0].get("away")}
    names = {t for b in _match_blocks(tool_log) for t in (b.get("home"), b.get("away")) if t}
    if wrong := teams_in(bare, names) - allowed:
        out.append(Issue(8, None, "text 里的队名不属于任何一条比赛事实的那场：" + "、".join(sorted(wrong))))
    return out
