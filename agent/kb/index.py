"""
agent/kb/index.py  Milvus Lite 索引（docs/agent-plan.md 第 7 节）：建库、--rebuild / --update、按 as_of 检索。
- 目录 cfg.kb_path：milvus.db（Milvus Lite 数据目录，独占锁）+ meta.json（向量函数名、维数、建库时间）。
  meta.json 缺失表示没建好；--rebuild 先删它、建完再写，中途失败也只会是「没建好」，不会半新半旧。
- 每块：正文 text、预切词 terms（BM25 由 Milvus 的 BM25 函数从 terms 生成）、bge-m3 向量 dense、
  available_us / superseded_us（UTC 微秒；没被替代时 NEVER）、meta（JSON：路径、标题、提交、比赛数据、指纹）。
- 检索：两路各取前 ROUTE_K，在 Python 里做 RRF（k=RRF_K）取前 k；过滤 available_us <= as_of < superseded_us。
- 读写都按次打开、用完关闭。另一进程正在用索引时打不开，抛 KBBusy。
"""
import json
import os
import pathlib
import re
import shutil
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

os.environ.setdefault("GRPC_VERBOSITY", "ERROR")   # Milvus Lite 的 gRPC 每次 git 子进程都打一行 fork 提示
from pymilvus import DataType, Function, FunctionType, MilvusClient
from pymilvus.exceptions import MilvusException

from agent.kb.embed import get_embedder, terms
from agent.kb.sources import Chunk

LAYOUT = 2                   # 字段或切块规则变了就加一，旧索引要求 --rebuild
COLLECTION = "kb"
NEVER = 2 ** 62
ROUTE_K, RRF_K = 20, 60
MODES = ("dense", "bm25", "hybrid")
LATEST_WINS = ("view", "score", "team_news")   # 同一 key 出现新块时，旧块在新块的 available_at 被替代
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MATCH_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_FIELDS = ("chunk_id", "family", "key", "authority", "match_id", "text", "available_us", "superseded_us", "meta")


class KBUnavailable(RuntimeError):
    """索引没建、或建索引用的向量函数与现在的不一致。"""


class KBBusy(RuntimeError):
    """另一个进程正在用索引（Milvus Lite 数据目录被锁）。"""


def to_us(t: datetime | None) -> int:
    return NEVER if t is None else (t - _EPOCH) // timedelta(microseconds=1)


def from_us(us: int) -> str | None:
    return None if us >= NEVER else (_EPOCH + timedelta(microseconds=us)).isoformat()


def check_match_id(mid: str) -> str:
    if not _MATCH_ID.match(mid):
        raise ValueError(f"比赛 id 格式不对：{mid}")
    return mid


def _paths(kb_path: str) -> tuple[pathlib.Path, pathlib.Path]:
    root = pathlib.Path(kb_path)
    return root / "milvus.db", root / "meta.json"


def read_meta(kb_path: str) -> dict | None:
    p = _paths(kb_path)[1]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@contextmanager
def _client(kb_path: str) -> Iterator[MilvusClient]:
    db, _ = _paths(kb_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        c = MilvusClient(str(db))
    except MilvusException as e:
        raise KBBusy("知识库正在被另一个进程使用（多半是正在 --rebuild / --update），稍后再试") from e
    try:
        # 新进程打开时集合是 released 状态，要先 load 才能查（同一进程里建完是已加载的）
        if c.has_collection(COLLECTION) and "Loaded" not in str(c.get_load_state(COLLECTION)["state"]):
            c.load_collection(COLLECTION)
        yield c
    finally:
        c.close()


def _create(c: MilvusClient, dim: int) -> None:
    if c.has_collection(COLLECTION):
        c.drop_collection(COLLECTION)
    s = c.create_schema(auto_id=False, enable_dynamic_field=False)
    s.add_field("chunk_id", DataType.VARCHAR, max_length=512, is_primary=True)
    for name, n in (("family", 32), ("key", 512), ("authority", 16), ("match_id", 64)):
        s.add_field(name, DataType.VARCHAR, max_length=n)
    s.add_field("text", DataType.VARCHAR, max_length=65535)
    s.add_field("terms", DataType.VARCHAR, max_length=65535, enable_analyzer=True,
                analyzer_params={"tokenizer": "standard"})
    s.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    s.add_field("dense", DataType.FLOAT_VECTOR, dim=dim)
    s.add_field("available_us", DataType.INT64)
    s.add_field("superseded_us", DataType.INT64)
    s.add_field("meta", DataType.JSON)
    s.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                            input_field_names=["terms"], output_field_names=["sparse"]))
    ip = c.prepare_index_params()
    ip.add_index("dense", index_type="FLAT", metric_type="COSINE")
    ip.add_index("sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    c.create_collection(COLLECTION, schema=s, index_params=ip)


def _row(ch: Chunk, vec: list[float]) -> dict:
    meta = {**ch.meta, "at_source": ch.at_source, "available_at": ch.available_at.isoformat(),
            "event_time": ch.event_time.isoformat() if ch.event_time else None}
    return {"chunk_id": ch.chunk_id, "family": ch.family, "key": ch.key, "authority": ch.authority,
            "match_id": ch.match_id, "text": ch.text, "terms": terms(ch.text), "dense": vec,
            "available_us": to_us(ch.available_at), "superseded_us": to_us(ch.superseded_at), "meta": meta}


def _insert(c: MilvusClient, embedder, chunks: list[Chunk], batch: int = 256) -> None:
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        vecs = embedder.encode([ch.text for ch in part])
        c.insert(COLLECTION, [_row(ch, v) for ch, v in zip(part, vecs)])


def _all_rows(c: MilvusClient, fields: list[str], page: int = 2000) -> list[dict]:
    out, offset = [], 0
    while True:
        got = c.query(COLLECTION, filter='chunk_id != ""', output_fields=fields, limit=page, offset=offset)
        out += got
        if len(got) < page:
            return out
        offset += page


def _write_meta(kb_path: str, embedder, n: int, built_at: str, updated_at: str) -> None:
    meta = {"layout": LAYOUT, "embedder": embedder.name, "dim": embedder.dim, "chunks": n,
            "built_at": built_at, "updated_at": updated_at}
    _paths(kb_path)[1].write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _usable(kb_path: str, embedder) -> dict:
    meta = read_meta(kb_path)
    if meta is None:
        raise KBUnavailable("知识库还没有建立：先运行 python -m agent.kb --rebuild")
    if (meta.get("layout"), meta.get("embedder"), meta.get("dim")) != (LAYOUT, embedder.name, embedder.dim):
        raise KBUnavailable("知识库的建库方式或向量函数与现在的不一致：运行 python -m agent.kb --rebuild")
    return meta


def rebuild(kb_path: str, chunks: list[Chunk], embedder, now: datetime) -> dict:
    """删掉旧索引，按 chunks 全部重建（旧块不保留，第 7.1 节）。"""
    _paths(kb_path)[1].unlink(missing_ok=True)
    with _client(kb_path) as c:
        _create(c, embedder.dim)
        _insert(c, embedder, chunks)
    _write_meta(kb_path, embedder, len(chunks), now.isoformat(), now.isoformat())
    return {"inserted": len(chunks), "superseded": 0, "updated": 0, "deleted": 0}


def _plan(old: dict[str, dict], chunks: list[Chunk], now: datetime) -> tuple[list[Chunk], dict, list[str]]:
    """增量：(要加的新块, {chunk_id: 要改的字段}, 要删的 chunk_id)。
    - 文档：生存期每次按 git 历史重算，superseded 有变就改；白名单里没有了的块删掉。
    - 评分：id 由 scored_at + 指标定。新 id → 新块，旧块在新块的 available_at 被替代；scored_at 没变而指标变了
      （_backfill_ah）时新块的 available_at 取这次发现的时刻（index_detected）。id 不变、指纹变了
      （只改了 result_src）→ 只改元数据里的 result_src 和指纹。
    - 看法、比分、阵容：同一 key 出现新块，旧块在新块的 available_at 被替代；FotMob 比分块按新算的 superseded 改。
    - 存档：只加不改。库里没有了的比赛类块保留（库只补不改，消失多半是没挂 fotmob.db 之类）。"""
    active: dict[str, list[dict]] = {}
    for r in old.values():
        if r["superseded_us"] == NEVER and r["family"] != "doc":
            active.setdefault(r["key"], []).append(r)
    fresh_ids = {ch.chunk_id for ch in chunks}
    new, change = [], {}
    for ch in chunks:
        o = old.get(ch.chunk_id)
        if o is None:
            if ch.family == "grading" and any(a["meta"].get("scored_at") == ch.meta.get("scored_at")
                                              for a in active.get(ch.key, [])):
                ch.available_at, ch.at_source = now, "index_detected"
            new.append(ch)
            continue
        want, sup = {}, to_us(ch.superseded_at)
        if sup != o["superseded_us"] and (ch.family == "doc" or o["superseded_us"] == NEVER):
            want["superseded_us"] = sup
        if ch.family == "grading" and o["meta"].get("fingerprint") != ch.meta.get("fingerprint"):
            want["meta"] = {**o["meta"], "fingerprint": ch.meta["fingerprint"], "result_src": ch.meta["result_src"]}
        if want:
            change[ch.chunk_id] = want
    for ch in new:
        if ch.family in (*LATEST_WINS, "grading"):
            at = to_us(ch.available_at)
            for a in active.get(ch.key, []):
                if a["chunk_id"] not in fresh_ids and a["available_us"] < at:
                    change.setdefault(a["chunk_id"], {})["superseded_us"] = at
    gone = [i for i, r in old.items() if r["family"] == "doc" and i not in fresh_ids]
    return new, change, gone


def update(kb_path: str, chunks: list[Chunk], embedder, now: datetime) -> dict:
    """只加新块、改替代时间和评分元数据（第 7.1 节）；向量只给新块算。"""
    meta = _usable(kb_path, embedder)
    with _client(kb_path) as c:
        old = {r["chunk_id"]: r for r in _all_rows(
            c, ["chunk_id", "family", "key", "available_us", "superseded_us", "meta"])}
        new, change, gone = _plan(old, chunks, now)
        if change:
            ids = list(change)
            full = c.get(COLLECTION, ids=ids, output_fields=[*_FIELDS, "terms", "dense"])
            c.upsert(COLLECTION, [{**r, **change[r["chunk_id"]]} for r in full])
        _insert(c, embedder, new)
        if gone:
            c.delete(COLLECTION, ids=gone)
        n = len(old) + len(new) - len(gone)
    _write_meta(kb_path, embedder, n, meta["built_at"], now.isoformat())
    sup = sum("superseded_us" in v for v in change.values())
    return {"inserted": len(new), "superseded": sup, "updated": len(change) - sup, "deleted": len(gone)}


def _visible(t: int) -> str:
    return f"available_us <= {t} and superseded_us > {t}"


def _scope_filter(scope: str, match_id: str | None) -> str:
    """default：文档三级 + 比赛类（传 match_id 时比赛类只要这一场）；handoff：只要交接记录。"""
    if scope == "handoff":
        return 'authority == "record"'
    if match_id:
        return f'(authority in ["rule", "status", "research"] or match_id == "{check_match_id(match_id)}")'
    return 'authority in ["rule", "status", "research", "data"]'


def _rrf(routes: dict[str, list[dict]]) -> list[dict]:
    score, rows, ranks = {}, {}, {}
    for name, hits in routes.items():
        for rank, h in enumerate(hits, 1):
            cid = h["entity"]["chunk_id"]
            rows.setdefault(cid, h["entity"])
            score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank)
            ranks.setdefault(cid, {})[name] = rank
    order = sorted(score, key=lambda i: (-score[i], i))
    return [{**rows[i], "score": round(score[i], 6), "ranks": ranks[i]} for i in order]


def source_label(score_used: dict, scores: list[dict]) -> str:
    """评分块的来源标签，按 as_of 时可见的比分块现定（第 7.1 节）。"""
    used = [score_used["home"], score_used["away"]]
    fd = [s for s in scores if s["meta"].get("source") == "football-data"]
    if fd:
        return "football-data" if fd[0]["meta"]["score"] == used else "按 FotMob 比分评分，football-data 比分不同，待重评"
    if any(s["meta"].get("source") == "fotmob" for s in scores):
        return "FotMob，待 football-data 核对"
    return "比分来源在这个时点还不可见"


def search(kb_path: str, embedder, query: str, as_of: datetime, k: int = 5, scope: str = "default",
           match_id: str | None = None, mode: str = "hybrid") -> list[dict]:
    """按 as_of 过滤后检索；返回块的字段 + score（RRF）+ ranks（各路名次）+ 评分块的 source_label。"""
    if mode not in MODES:
        raise ValueError(f"mode 只能是 {'/'.join(MODES)}")
    _usable(kb_path, embedder)
    t = to_us(as_of)
    flt = f"{_visible(t)} and {_scope_filter(scope, match_id)}"
    routes = {}
    with _client(kb_path) as c:
        if mode in ("dense", "hybrid"):
            routes["dense"] = c.search(COLLECTION, data=embedder.encode([query]), anns_field="dense",
                                       limit=ROUTE_K, filter=flt, output_fields=list(_FIELDS))[0]
        q = terms(query)
        if mode in ("bm25", "hybrid") and q:
            routes["bm25"] = c.search(COLLECTION, data=[q], anns_field="sparse", limit=ROUTE_K, filter=flt,
                                      output_fields=list(_FIELDS), search_params={"metric_type": "BM25"})[0]
        hits = _rrf(routes)[:k]
        for h in hits:
            if h["family"] == "grading":
                sc = c.query(COLLECTION, output_fields=["meta"], filter=(
                    f'{_visible(t)} and family == "score" and match_id == "{check_match_id(h["match_id"])}"'))
                h["source_label"] = source_label(h["meta"]["data"]["score_used"], sc)
    return hits


def stats(kb_path: str) -> dict:
    meta = read_meta(kb_path)
    if meta is None:
        return {"built": False}
    with _client(kb_path) as c:
        rows = _all_rows(c, ["family", "authority", "superseded_us"])
    db = _paths(kb_path)[0]
    size = sum(p.stat().st_size for p in db.rglob("*") if p.is_file()) if db.exists() else 0
    return {"built": True, **meta, "rows": len(rows),
            "active": sum(r["superseded_us"] == NEVER for r in rows),
            "by_family": dict(Counter(r["family"] for r in rows)),
            "by_authority": dict(Counter(r["authority"] for r in rows)), "bytes": size}


def drop(kb_path: str) -> None:
    """删掉整个索引目录（测试和 --rebuild 出错后清理用）。"""
    shutil.rmtree(kb_path, ignore_errors=True)
