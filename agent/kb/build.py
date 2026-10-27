"""
agent/kb/build.py  把白名单文件和库里的比赛类资料收齐，交给 index 重建或增量更新。
白名单核对不通过时不动索引（抛 ValueError，列出全部问题）。库只读打开（config.connect）。
"""
import pathlib
import time

from agent import config
from agent.kb import index, whitelist
from agent.kb.embed import get_embedder
from agent.kb.match_chunks import match_chunks
from agent.kb.sources import Chunk, all_doc_chunks


def collect(root: pathlib.Path = config.ROOT, wl: pathlib.Path = whitelist.WHITELIST) -> list[Chunk]:
    entries = whitelist.load(wl)
    problems = whitelist.check(entries, root)
    if problems:
        raise ValueError("白名单核对不通过：\n" + "\n".join(problems))
    cfg = config.current()
    chunks = all_doc_chunks([e for e in entries if whitelist.searchable(e)], root)
    with config.connect() as conn:
        chunks += match_chunks(conn, cfg.snapshot_path)
    return chunks


def run(action: str, root: pathlib.Path = config.ROOT, wl: pathlib.Path = whitelist.WHITELIST) -> dict:
    """action：rebuild / update。返回各类块的数量和用时（秒）。"""
    cfg = config.current()
    t0 = time.perf_counter()
    chunks = collect(root, wl)
    embedder = get_embedder(cfg)
    t1 = time.perf_counter()
    fn = index.rebuild if action == "rebuild" else index.update
    out = fn(cfg.kb_path, chunks, embedder, cfg.clock())
    return {**out, "chunks": len(chunks), "collect_s": round(t1 - t0, 1),
            "index_s": round(time.perf_counter() - t1, 1)}
