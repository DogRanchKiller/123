"""
agent/tools/knowledge.py  kb_search（docs/agent-plan.md 第 6、7 节）。
P1 是假实现：签名与方案一致，返回一块固定的说明，用来打通工具调用和块的格式；P2 换成
Chroma + BM25 的混合检索，按 as_of / superseded_at 过滤。
as_of 的规则现在就按方案做：传 match_id 时由工具取 min(调用时刻, 该场开球)，不用模型填的值。
"""
from datetime import datetime, timezone
from typing import Any

from agent import config
from agent.tools.blocks import kickoff_of, parse_time, result
from football_prediction import services

SCOPES = ("default", "handoff")
MAX_K = 20
_FAKE_AT = datetime(2026, 10, 26, tzinfo=timezone.utc)   # 假块的 available_at（方案第 1 稿那天）
_FAKE = {"scope": "kb", "chunk_id": "fake-agents-md", "kind": "kb", "at": _FAKE_AT.isoformat(),
         "path": "AGENTS.md", "commit": None, "authority": "rule", "fake": True,
         "text": "知识库还没有建立（假实现），这里只有这一条固定说明。项目规则见 AGENTS.md。"}


def _as_of(as_of: str | None, match_id: str | None, now: datetime) -> datetime:
    if match_id:
        cfg = config.current()
        with config.connect() as conn:
            d = services.read_match(conn, match_id, cfg.snapshot_path)
        if d is None:
            raise ValueError(f"找不到比赛 {match_id}")
        return min(now, kickoff_of(d["match"]))
    return min(now, parse_time(as_of)) if as_of else now


def kb_search(query: str, k: int = 5, as_of: str | None = None, match_id: str | None = None,
              scope: str = "default") -> dict[str, Any]:
    """在项目知识库里检索（规则、进度、问题、研究结论）。只返回 as_of 时已经可以看到的资料。
    as_of：ISO 时间，不传为现在；传 match_id 时忽略 as_of，按该场开球前检索。
    scope：default（规则、进度、研究结论）或 handoff（交接记录）。现在是假实现，知识库还没有建立。"""
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k 超出范围（最小 1，最大 {MAX_K}）")
    if scope not in SCOPES:
        raise ValueError(f"未知 scope {scope}；可用：" + "、".join(SCOPES))
    now = config.current().clock()
    at = _as_of(as_of, match_id, now)
    blocks = [dict(_FAKE)] if scope == "default" and _FAKE_AT <= at else []
    return result(now, blocks, "知识库是假实现，下一阶段才建立", query=query, searched_as_of=at.isoformat())
