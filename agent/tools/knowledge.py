"""
agent/tools/knowledge.py  kb_search（docs/agent-plan.md 第 6、7 节）。
在 Milvus Lite 索引（agent/kb）里做 bge-m3 向量 + BM25 的混合检索，只返回 as_of 时可见的块：
available_at <= as_of，且没被替代或替代时间晚于 as_of。default 除文档外也检索比赛类块（看法、存档、比分、
评分、阵容；评分块带按 as_of 现定的 source_label）。传 match_id 时 as_of 由工具取 min(调用时刻, 该场开球)，
不用模型填的值，比赛类块只要这一场。
pymilvus 只在 .venv-ml 里有；没有它、索引没建、或另一进程正在重建时返回空块和说明，不报错。
"""
from datetime import datetime
from typing import Any

from agent import config
from agent.tools.blocks import kickoff_of, parse_time, result
from football_prediction import services

SCOPES = ("default", "handoff")
MAX_K = 20


def _as_of(as_of: str | None, match_id: str | None, now: datetime) -> datetime:
    if match_id:
        cfg = config.current()
        with config.connect() as conn:
            d = services.read_match(conn, match_id, cfg.snapshot_path)
        if d is None:
            raise ValueError(f"找不到比赛 {match_id}")
        return min(now, kickoff_of(d["match"]))
    return min(now, parse_time(as_of)) if as_of else now


def _block(h: dict, from_us) -> dict:
    m = h["meta"]
    b = {"scope": "kb", "chunk_id": h["chunk_id"], "kind": "kb", "at": m["available_at"],
         "authority": h["authority"], "family": h["family"], "at_source": m["at_source"],
         "superseded_at": from_us(h["superseded_us"])}
    if h["family"] == "doc":
        b |= {"path": m["path"], "heading": m["heading"], "commit": m["commit"]}
    else:
        b |= {"match_id": h["match_id"], "event_time": m["event_time"], "data": m["data"]}
        if "source_label" in h:
            b["source_label"] = h["source_label"]
    return b | {"text": h["text"]}


def _search(query: str, k: int, at: datetime, scope: str, match_id: str | None) -> tuple[list, str | None]:
    try:
        from agent.kb import index
        from agent.kb.embed import get_embedder
    except ImportError:
        return [], "知识库只在 .venv-ml 环境里可用（缺 pymilvus）"
    cfg = config.current()
    if index.read_meta(cfg.kb_path) is None:
        return [], "知识库还没有建立，先运行 python -m agent.kb --rebuild"
    try:
        hits = index.search(cfg.kb_path, get_embedder(cfg), query, at, k, scope, match_id)
    except (index.KBUnavailable, index.KBBusy, FileNotFoundError) as e:
        return [], str(e)
    blocks = [_block(h, index.from_us) for h in hits]
    if not blocks:
        return [], "知识库里没有这个时点之前的相关资料"
    return blocks, "交接记录，未必是当前状态" if scope == "handoff" else None


def kb_search(query: str, k: int = 5, as_of: str | None = None, match_id: str | None = None,
              scope: str = "default") -> dict[str, Any]:
    """在项目知识库里检索规则、进度、问题和研究结论（每块带 authority：rule / status 优先于 research）。
    只返回 as_of 时已经可以看到的版本。as_of：ISO 时间，不传为现在；传 match_id 时忽略 as_of，按该场开球前
    检索，比赛类只要这一场开球前已有的看法和存档。scope：default（规则、进度、问题、研究结论和比赛类资料）
或 handoff（交接记录）。"""
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k 超出范围（最小 1，最大 {MAX_K}）")
    if scope not in SCOPES:
        raise ValueError(f"未知 scope {scope}；可用：" + "、".join(SCOPES))
    if not query.strip():
        raise ValueError("query 不能为空")
    now = config.current().clock()
    at = _as_of(as_of, match_id, now)
    blocks, note = _search(query, k, at, scope, match_id)
    return result(now, blocks, note, query=query, searched_as_of=at.isoformat())
