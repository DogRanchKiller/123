"""
agent/facts/render.py  渲染与降级（docs/agent-plan.md 第 8.4 节）。
通过校验后，每个占位换成**工具结果里的值**（不用模型写的 value），按单位格式化，后面按 kind 加来源标签，
如「主-0.75（本轮看法，10-26 22:43）」「53%（首次存档，10-25 18:07）」「2-1（比分，FotMob，待 football-data 核对）」。
同一句里连着的同来源数只在最后一个后面标一次；时间字段的值就是块的 at 时，标签不再重复时间。
知识库的数原样照抄 quote 里的写法，标「项目文档 <路径>，<提交日期>」「研究结论 <路径>」或「交接记录 …，未必是当前状态」。
时间一律北京时间，有事实时文末注明一次。
降级：不输出模型的成段文字，只把能单独通过核对的事实渲染成表格，加一句「部分内容没有通过核对，已省略」；
一条也没有时列出查到的对阵（名字取自工具结果，不含数）；什么都没查到时只回「这次没能完成查询」。
"""
import re
from datetime import datetime

from agent.facts import units
from agent.facts.verify import FACT_KEYS, PLACEHOLDER, check_fact, locate, pointer

FAILED = "这次没能完成查询。"
OMITTED = "部分内容没有通过核对，已省略。"
BJ_NOTE = "（时间均为北京时间）"
_KIND = {"current": "本轮看法", "last_pre_kickoff": "开球前最后一轮看法", "first_archive": "首次存档",
         "near_archive": "临场存档", "scorecard": "实盘成绩单", "closing": "对收盘参照",
         "team_news": "阵容，FotMob"}
_KB_DATA = {"view": "当时的看法", "first_archive": "首次存档", "near_archive": "临场存档", "score": "比分",
            "grading": "赛后评分", "team_news": "阵容"}


def _score_src(src) -> str:
    return "FotMob，待 football-data 核对" if src == "fotmob" else "football-data"


def label(block: dict, now: datetime | None = None) -> str:
    """来源标签（不含括号）。时间取块的 at（这份数据本身的时间）。"""
    kind, at = block.get("kind"), units.fmt_dt(block.get("at"), now)
    if kind == "live_calc":
        odds = block.get("odds_fetched_at")
        return "按最新赔率现算" + (f"，赔率 {units.fmt_dt(odds, now)} 获取" if odds else "")
    if kind == "score":
        return "比分，" + _score_src(block.get("score_source"))
    if kind == "grading":
        return f"赛后评分，{_score_src(block.get('result_src'))}，{at}"
    if kind == "kb":
        auth, day = block.get("authority"), units.parse_dt(block.get("at"))
        if auth in ("rule", "status"):
            return f"项目文档 {block.get('path')}" + (f"，{day.astimezone(units.BJ):%Y-%m-%d}" if day else "")
        if auth == "research":
            return f"研究结论 {block.get('path')}"
        if auth == "record":
            return f"交接记录 {block.get('path')}，未必是当前状态"
        return f"{_KB_DATA.get(block.get('family'), '比赛资料')}，知识库，{at}"
    return f"{_KIND.get(kind, kind)}，{at}"


def value_text(f: dict, tool_log: dict, now: datetime | None = None) -> tuple[str, str, str]:
    """(格式化后的值, 中文字段名, 来源标签)：值一律取工具结果；知识库取 quote 里的原文写法。
    只对通过 check_fact 的事实调用。"""
    block, sub = locate(f, tool_log)
    unit, name = units.field(block["scope"], sub)
    if unit == "kb_number":
        return units.kb_literal(f["quote"], f["value"]), name, label(block, now)
    return units.fmt(unit, pointer(block, sub), now), name, label(block, now)


_SENTENCE_END = re.compile(r"[。；;！!？?\n]")


def _own_label(f: dict, tool_log: dict, now: datetime | None) -> tuple[str, str]:
    """(格式化后的值, 来源标签)。时间字段的值就是块自己的 at 时，标签里的时间重复，只留来源名。"""
    v, _, lab = value_text(f, tool_log, now)
    block, sub = locate(f, tool_log)
    unit = units.field(block["scope"], sub)[0]
    if unit == "datetime" and units.same("datetime", pointer(block, sub), block.get("at")):
        lab = lab.removesuffix("，" + units.fmt_dt(block.get("at"), now))
    return v, lab


def render(answer: dict, tool_log: dict, now: datetime | None = None) -> str:
    """通过校验的答案 → 给用户看的文字。同一句里连着几个同一来源的数（中间没有句末标点），
    来源标签只写在最后一个后面，如「主-0.75、赢盘 53%（本轮看法，10-26 22:43）」。"""
    by_id = {f["id"]: f for f in answer["facts"]}
    text = answer["text"]
    spots = list(PLACEHOLDER.finditer(text))
    vals = [_own_label(by_id[m.group(1)], tool_log, now) for m in spots]
    out, pos = [], 0
    for i, (m, (v, lab)) in enumerate(zip(spots, vals)):
        nxt = spots[i + 1] if i + 1 < len(spots) else None
        shared = (nxt is not None and vals[i + 1][1] == lab
                  and not _SENTENCE_END.search(text, m.end(), nxt.start()))
        out += [text[pos:m.start()], v if shared else f"{v}（{lab}）"]
        pos = m.end()
    return "".join(out) + text[pos:] + (BJ_NOTE if by_id else "")


def _subject(block: dict) -> str:
    if block.get("scope") == "match":
        return f"{block.get('home')} 对 {block.get('away')}"
    if block.get("scope") == "scorecard":
        return f"{block.get('model_name')} {block.get('model_ver')}"
    return str(block.get("path") or block.get("chunk_id"))


def checked_facts(answer, tool_log: dict) -> list[dict]:
    """答案里能单独通过第 3–7 条的事实（降级时只展示这些）。"""
    facts = answer.get("facts") if isinstance(answer, dict) else None
    if not isinstance(facts, list):
        return []
    return [f for f in facts if isinstance(f, dict) and all(k in f for k in FACT_KEYS)
            and not check_fact(f, tool_log)]


def degrade(answer, tool_log: dict, now: datetime | None = None) -> str:
    """降级输出：不含模型的成段文字，也不含任何没核对过的数。"""
    good = checked_facts(answer, tool_log)
    if good:
        rows = ["| 对象 | 项目 | 值 | 来源 |", "|---|---|---|---|"]
        for f in good:
            v, name, lab = value_text(f, tool_log, now)
            rows.append(f"| {_subject(locate(f, tool_log)[0])} | {name} | {v} | {lab} |")
        return "\n".join([OMITTED, "", *rows, "", BJ_NOTE])
    pairs = [f"- {b.get('home')} 对 {b.get('away')}" for res in tool_log.values()
             for b in res.get("blocks", []) if b.get("scope") == "match"]
    if pairs:
        return "\n".join([FAILED + "查到的场次：", *dict.fromkeys(pairs)])
    return FAILED
