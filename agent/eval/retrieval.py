"""
agent/eval/retrieval.py  知识库检索评测（docs/agent-dev.md 第 7 节 P2 出口证据）。
评测集 agent/eval/retrieval.jsonl，一行一题：
  {"id", "query", "as_of", "gold": [{"path", "heading"}], "forbid": [...], "note"}
- gold：该时点应命中的文档块。heading 写完整标题路径或其后缀（" > " 分隔），空串表示该文件任一块。
  gold 为空的题只查泄漏，不进 recall / MRR。
- forbid：as_of 之后才出现（或之前已被改掉）的文字。核对两件事：这段文字确实在某一版里出现过，
  且 as_of 时可见的块里没有它；检索结果里也不能有。
- 每条结果另查 available_at <= as_of < superseded_at（泛化的泄漏检查）。
指标：recall@5（前 5 有任一 gold 块）、MRR@20、recall@1，按 dense / bm25 / hybrid 各算一遍。
没有下载重排模型，hybrid+rerank 记为未跑。
"""
import json
import pathlib
import time
from datetime import datetime

from agent import config
from agent.kb import index, whitelist
from agent.kb.embed import get_embedder
from agent.kb.sources import Chunk, all_doc_chunks

EVAL_FILE = pathlib.Path(__file__).with_name("retrieval.jsonl")
K = 20


def load(path: pathlib.Path = EVAL_FILE) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("评测集里有重复 id")
    for it in items:
        it["_t"] = datetime.fromisoformat(it["as_of"])
        if it["_t"].tzinfo is None:
            raise ValueError(f"{it['id']}：as_of 要带时区")
    return items


def _alive(ch: Chunk, t: datetime) -> bool:
    return ch.available_at <= t and (ch.superseded_at is None or t < ch.superseded_at)


def is_gold(path: str, heading: str, gold: list[dict]) -> bool:
    for g in gold:
        h = g.get("heading", "")
        if path == g["path"] and (not h or heading == h or heading.endswith(" > " + h)):
            return True
    return False


def check_items(items: list[dict], docs: list[Chunk]) -> list[str]:
    """评测集本身对不对：gold 在 as_of 时可见；forbid 出现过、但 as_of 时看不到。"""
    problems = []
    for it in items:
        t, alive = it["_t"], [ch for ch in docs if _alive(ch, it["_t"])]
        for g in it["gold"]:
            if not any(is_gold(ch.meta["path"], ch.meta["heading"], [g]) for ch in alive):
                problems.append(f"{it['id']}：gold {g['path']} > {g.get('heading', '')} 在 {t} 不可见")
        for f in it.get("forbid", []):
            if not any(f in ch.text for ch in docs):
                problems.append(f"{it['id']}：forbid「{f}」在任何一版里都没出现过，检查不出东西")
            if any(f in ch.text for ch in alive):
                problems.append(f"{it['id']}：forbid「{f}」在 {t} 本来就可见，不是泄漏用例")
    return problems


def _leaks(it: dict, hits: list[dict]) -> list[str]:
    t, out = index.to_us(it["_t"]), []
    for h in hits:
        if not (h["available_us"] <= t < h["superseded_us"]):
            out.append(f"{it['id']}：{h['chunk_id']} 在 as_of 时不可见")
        for f in it.get("forbid", []):
            if f in h["text"]:
                out.append(f"{it['id']}：{h['chunk_id']} 含 as_of 之后的「{f}」")
    return out


def _rank(hits: list[dict], gold: list[dict]) -> int | None:
    for r, h in enumerate(hits, 1):
        if h["family"] == "doc" and is_gold(h["meta"]["path"], h["meta"]["heading"], gold):
            return r
    return None


def run(path: str | None = None, modes: tuple[str, ...] = index.MODES) -> dict:
    """跑全部题；返回各方式的指标、泄漏条数与明细、hybrid 前 5 没命中的题。"""
    cfg = config.current()
    items = load(pathlib.Path(path) if path else EVAL_FILE)
    entries = [e for e in whitelist.load(whitelist.WHITELIST) if whitelist.searchable(e)]
    problems = check_items(items, all_doc_chunks(entries, config.ROOT))
    if problems:
        raise ValueError("评测集核对不通过：\n" + "\n".join(problems))
    embedder = get_embedder(cfg)
    graded = [it for it in items if it["gold"]]
    out = {"items": len(items), "graded": len(graded),
           "leak_items": sum(bool(it.get("forbid")) for it in items), "modes": {}}
    leaks, misses = [], []
    for mode in modes:
        t0, r5, r1, rr = time.perf_counter(), 0, 0, 0.0
        for it in items:
            hits = index.search(cfg.kb_path, embedder, it["query"], it["_t"], k=K, mode=mode)
            leaks += _leaks(it, hits)
            if not it["gold"]:
                continue
            r = _rank(hits, it["gold"])
            r5 += r is not None and r <= 5
            r1 += r == 1
            rr += 1 / r if r else 0.0
            if mode == "hybrid" and (r is None or r > 5):
                misses.append({"id": it["id"], "query": it["query"], "rank": r,
                               "top": [h["chunk_id"] for h in hits[:3]]})
        n = len(graded) or 1
        out["modes"][mode] = {"recall@5": round(r5 / n, 3), "recall@1": round(r1 / n, 3),
                              "mrr@20": round(rr / n, 3), "seconds": round(time.perf_counter() - t0, 1)}
    out["modes"]["hybrid+rerank"] = "未跑：没有下载重排模型"
    out["leaks"] = len(leaks)
    out["leak_detail"] = leaks
    out["hybrid_misses"] = misses
    return out
