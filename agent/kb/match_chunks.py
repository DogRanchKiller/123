"""
agent/kb/match_chunks.py  比赛类的块（docs/agent-plan.md 第 7.1 节），全部经 services 的读函数从库里取，只读。
| family        | available_at（at_source）         | 一个 key 的版本                         |
| view          | 快照 generated_at                 | 新快照替代旧的（快照不早于开球的不收）   |
| first_archive / near_archive | predictions.generated_at | 不变（每个模型名 + 版本一块）           |
| score         | 各来源自己的 fetched_at           | FotMob 块在 football-data 块出现时被替代 |
| grading       | scored_at；只补算指标时取发现时刻 | 按指纹（result_src + scored_at + 指标）   |
| team_news     | lineups.fetched_at                | 新一批替代旧的                           |
event_time 都是开球。评分块只放指标和 score_used（按该行 result_src 从对应来源取，取不到不建块），
来源标签在检索时按 as_of 现定（index.py）。
"""
import hashlib
import json

from agent.kb.sources import Chunk
from agent.tools.blocks import archive_block, kickoff_of, match_block, parse_time, stored_only
from football_prediction import services

_SRC = {"fd": "football-data", "fotmob": "fotmob"}
_OUTCOME = {"home_win": "主胜", "draw": "平", "away_win": "客胜"}   # predictions.actual_outcome 的取值，同 output/analysis.py 的 LABEL
METRICS = ("actual_outcome", "log_loss", "brier", "ou25_log_loss", "score_log_loss", "ah_line",
           "ah_log_loss", "ah_hit")


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def _line(x) -> str:
    return "-" if x is None else ("0" if float(x) == 0 else f"{float(x):+.2f}")


def _head(info: dict) -> str:
    return f"{info.get('league_name') or info.get('league')} {info['home']} 对 {info['away']}（开球 {info.get('kickoff_utc') or info.get('match_date')}）"


def _opinion(v: dict) -> str:
    """快照看法带档位和稳妥线（快照生成时的规则）；存档块传进来的已去掉这些键，就不写。"""
    a = v.get("asian") or {}
    p = v.get("probabilities") or [None] * 3
    scores = "、".join(s["score"] for s in v.get("likely_scores") or [])
    parts = []
    if a:
        s = f"亚盘 主{_line(a.get('line'))}（{a.get('line_source')}）选{a.get('side')}，赢盘 {_pct(a.get('p_cover'))}"
        if "tier" in a:
            s += f"，信心{a.get('tier')}，稳妥线 {_line(a.get('safe_line'))}"
        parts.append(s)
    conf = f"，信心{v.get('confidence')}" if "confidence" in v else ""
    parts.append(f"胜平负倾向 {v.get('lean')}，双选 {v.get('double')}{conf}，"
                 f"概率 主{_pct(p[0])} 平{_pct(p[1])} 客{_pct(p[2])}")
    parts.append(f"大 2.5 概率 {_pct(v.get('over25'))}" + (f"，可能比分 {scores}" if scores else ""))
    return "；".join(parts)


def _chunk(family, cid, key, text, at, src, info, data, meta=None, superseded=None) -> Chunk:
    return Chunk(chunk_id=cid, family=family, key=key, authority="data", text=text,
                 available_at=parse_time(at), at_source=src, superseded_at=superseded,
                 event_time=kickoff_of(info), match_id=info["match_id"], meta={"data": data, **(meta or {})})


def fingerprint(row: dict) -> str:
    vals = [row.get("result_src") or "fd", row.get("scored_at")] + [row.get(k) for k in METRICS]
    return hashlib.sha1(json.dumps(vals, default=str).encode()).hexdigest()[:16]


def _view(info: dict, view: dict, gen: str) -> Chunk | None:
    if parse_time(gen) >= kickoff_of(info):
        return None
    note = view.get("recommendation_note")
    text = f"{_head(info)} 本轮看法（快照 {gen}）：{_opinion(view)}" + (f"。{note}" if note else "")
    return _chunk("view", f"view:{info['match_id']}:{gen}", f"view:{info['match_id']}", text, gen,
                  "snapshot.generated_at", info, match_block(info["match_id"], "view", gen, info, view))


def _archive(info: dict, arch: dict | None, family: str) -> Chunk | None:
    if not arch:
        return None
    arch = stored_only(arch)     # 现算的档位和稳妥线会让 as_of 早于规则的检索看到后来的规则
    label = "首次存档" if family == "first_archive" else "临场存档"
    cid = f"{family}:{info['match_id']}:{arch['model_name']}:{arch['model_version']}"
    text = (f"{_head(info)} {label}（{arch['model_name']} {arch['model_version']}，{arch['generated_at']}）："
            f"{_opinion(arch)}")
    return _chunk(family, cid, cid, text, arch["generated_at"], "predictions.generated_at", info,
                  archive_block(info["match_id"], arch, family, info))


def _scores(info: dict, rows: list[dict]) -> list[Chunk]:
    out = {}
    for r in rows:
        src = r["source"]
        at = "matches.fetched_at" if src == "football-data" else "fotmob_results.fetched_at"
        text = f"{_head(info)} 比分 {r['home']}-{r['away']}，来源 {src}，获取于 {r['fetched_at']}"
        data = match_block(info["match_id"], "score", r["fetched_at"], info,
                           {"score": {"home": r["home"], "away": r["away"]}, "score_source": src})
        out[src] = _chunk("score", f"score:{info['match_id']}:{src}:{r['fetched_at']}",
                          f"score:{info['match_id']}:{src}", text, r["fetched_at"], at, info, data,
                          meta={"source": src, "score": [r["home"], r["away"]]})
    if "fotmob" in out and "football-data" in out:
        out["fotmob"].superseded_at = out["football-data"].available_at
    return list(out.values())


def _grading(info: dict, rows: list[dict], scores: list[dict]) -> list[Chunk]:
    by_src = {s["source"]: s for s in scores}
    out = []
    for r in rows:
        src = r.get("result_src") or "fd"
        used = by_src.get(_SRC.get(src, src))
        if used is None:                          # 取不到评分时用的比分（如 fotmob 但没挂 fotmob.db）
            continue
        fp = fingerprint(r)
        body = {"model_name": r["model_name"], "model_ver": r["model_ver"], "generated_at": r["generated_at"],
                "scored_at": r["scored_at"], **{k: r.get(k) for k in METRICS},
                "score_used": {"home": used["home"], "away": used["away"]}}
        hit = {1.0: "赢盘", 0.5: "赢半", 0.0: "未赢盘"}.get(r.get("ah_hit"), "走盘或无亚盘")
        text = (f"{_head(info)} 赛后评分：{r['model_name']} {r['model_ver']}（存档于 {r['generated_at']}），"
                f"评分比分 {used['home']}-{used['away']}，赛果 {_OUTCOME.get(r.get('actual_outcome'), '-')}，"
                f"胜平负 log loss {r.get('log_loss')}，Brier {r.get('brier')}，大小 2.5 log loss {r.get('ou25_log_loss')}，"
                f"比分 log loss {r.get('score_log_loss')}，亚盘 主{_line(r.get('ah_line'))} log loss {r.get('ah_log_loss')}，{hit}")
        h = hashlib.sha1(json.dumps([r["scored_at"]] + [r.get(k) for k in METRICS], default=str).encode()).hexdigest()[:10]
        key = f"grading:{info['match_id']}:{r['model_name']}:{r['model_ver']}"
        out.append(_chunk("grading", f"{key}:{h}", key, text, r["scored_at"], "predictions.scored_at", info,
                          match_block(info["match_id"], "grading", r["scored_at"], info, body),
                          meta={"fingerprint": fp, "result_src": src, "scored_at": r["scored_at"]}))
    return out


def _news(info: dict, lu: dict | None) -> Chunk | None:
    if lu is None:
        return None
    names = []
    for side in ("home", "away"):
        team = info[side]
        st = "、".join(p["name"] for p in lu[side]["starters"])
        out = "、".join(p["name"] + (f"（{p['detail']}）" if p.get("detail") else "") for p in lu[side]["unavailable"])
        names.append(f"{team} 首发：{st or '-'}；缺阵：{out or '无'}")
    kind = "正式首发" if lu["lineup_type"] == "standard" else "预测首发"
    text = f"{_head(info)} 阵容与伤停（FotMob {kind}，抓取于 {lu['fetched_at']}）：" + "。".join(names)
    body = {"fetched_at": lu["fetched_at"], "lineup_type": lu["lineup_type"],
            "lineups": {"home": lu["home"], "away": lu["away"]}}
    return _chunk("team_news", f"team_news:{info['match_id']}:{lu['fetched_at']}", f"team_news:{info['match_id']}",
                  text, lu["fetched_at"], "lineups.fetched_at", info,
                  match_block(info["match_id"], "team_news", lu["fetched_at"], info, body))


def match_chunks(conn, snapshot_path: str) -> list[Chunk]:
    """快照里的场次和有存档的场次，每场按 family 建块。不知道对阵的场次跳过。"""
    snap = services.read_snapshot(snapshot_path) or {}
    ids = list(dict.fromkeys([m["match_id"] for m in snap.get("matches", [])] + services.read_archived_ids(conn)))
    out: list[Chunk] = []
    for mid in ids:
        d = services.read_match(conn, mid, snapshot_path)
        if d is None:
            continue
        info = d["match"]
        scores = services.read_scores(conn, mid)
        out += [c for c in (
            _view(info, d["current"], d["generated_at"]) if d["current"] else None,
            _archive(info, d["archived"], "first_archive"),
            _archive(info, d["near_archived"], "near_archive"),
            *_scores(info, scores),
            *_grading(info, services.read_grading(conn, mid), scores),
            _news(info, services.read_lineups(conn, mid)),
        ) if c is not None]
    return out
