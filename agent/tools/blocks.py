"""
agent/tools/blocks.py  把 services 的返回包成「块」（docs/agent-plan.md 第 6 节）。
每块开头四个键：scope、主体键（match → match_id；scorecard → model_name + model_ver；kb → chunk_id）、
kind、at；后面是该块的内容字段。第 8 节的校验按块核对「哪场 / 哪个模型 / 哪种看法 / 什么时候」，
所以一块里只放同一时点、同一来源的数：首次存档的概率和它赛后的评分分成两块（at 不同）。
开球后的快照看法按调用时刻改标（view_kind），不改 services.read_match。
"""
from datetime import datetime, timezone

from football_prediction import version

MATCH_KEYS = ("league", "league_name", "home", "away", "kickoff_utc", "match_date")
# 存档里属于赛后评分的字段：不放进存档块，评分单独成 grading 块（at = scored_at）
_GRADE_KEYS = ("scored", "actual_outcome", "log_loss", "brier", "ou25_log_loss", "score_log_loss",
               "ah_log_loss", "ah_hit", "result_src", "scored_at")
# services.read_match 给存档补的档位、历史命中率和稳妥线是按现在的规则现算的（存档行里没有），
# 放进 at = generated_at 的存档块会把后来的规则说成存档时的看法。存档块只留存档时就有的数和由它们直接算出的选择方。
_ARCHIVE_DERIVED = ("confidence", "historical_first_hit", "historical_double_hit")
_AH_DERIVED = ("tier", "historical_hit", "safe_line", "safe_cover")


def stored_only(archived: dict) -> dict:
    """存档去掉按现行规则现算的字段（_ARCHIVE_DERIVED、asian 里的 _AH_DERIVED）。"""
    out = {k: v for k, v in archived.items() if k not in _ARCHIVE_DERIVED}
    if out.get("asian"):
        out["asian"] = {k: v for k, v in out["asian"].items() if k not in _AH_DERIVED}
    return out


def parse_time(s: str) -> datetime:
    """ISO 时间 → 带时区的 datetime；没写时区的按 UTC。"""
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def kickoff_of(m: dict) -> datetime:
    """开球时间；没有 kickoff_utc 时取比赛日 00:00 UTC（偏早，只会多改标、多丢弃，不会把开球后的看法当成当前）。"""
    return parse_time(m["kickoff_utc"] if m.get("kickoff_utc") else m["match_date"] + "T00:00:00+00:00")


def view_kind(generated_at: str, kickoff: datetime, now: datetime) -> str | None:
    """快照看法的 kind：调用早于开球 → current；不早于开球、快照早于开球 → last_pre_kickoff；
    快照不早于开球 → None（整块丢弃，不交给模型）。"""
    if parse_time(generated_at) >= kickoff:
        return None
    return "current" if now < kickoff else "last_pre_kickoff"


def ident(m: dict) -> dict:
    return {k: m.get(k) for k in MATCH_KEYS}


def match_block(match_id: str, kind: str, at: str | None, info: dict, body: dict) -> dict:
    """scope=match 的块：四个键 + 对阵（league / home / away / 开球，第 8.3 节第 8 条对照队名用）+ 内容。"""
    skip = {"match_id", *MATCH_KEYS}
    return {"scope": "match", "match_id": match_id, "kind": kind, "at": at, **ident(info),
            **{k: v for k, v in body.items() if k not in skip}}


def view_block(view: dict, generated_at: str, now: datetime, info: dict | None = None) -> dict | None:
    """快照里一场的看法 → current / last_pre_kickoff 块；该丢弃时 None。"""
    info = info or view
    kind = view_kind(generated_at, kickoff_of(info), now)
    if kind is None:
        return None
    return match_block(view["match_id"], kind, generated_at, info, view)


def archive_block(match_id: str, archived: dict | None, kind: str, info: dict) -> dict | None:
    """首次存档（first_archive）或临场存档（near_archive），去掉评分字段和现算字段；没有存档时 None。"""
    if not archived:
        return None
    body = {k: v for k, v in stored_only(archived).items() if k not in _GRADE_KEYS}
    return match_block(match_id, kind, archived["generated_at"], info, body)


def score_block(info: dict) -> dict | None:
    """比分块：at 是采用的那个来源的获取时间；还没有比分时 None。"""
    if not info.get("score"):
        return None
    return match_block(info["match_id"], "score", info.get("score_fetched_at"), info,
                       {"score": info["score"], "score_source": info["score_source"]})


def grading_blocks(match_id: str, rows: list[dict], info: dict) -> list[dict]:
    """services.read_grading 的每行 → grading 块（at = scored_at）。来源标签到第 7.1 节（P2）按 as_of 现定。"""
    return [match_block(match_id, "grading", r["scored_at"], info, r) for r in rows]


def scorecard_block(row: dict, generated_at: str, kind: str = "scorecard") -> dict:
    """成绩单一行 → scope=scorecard 块（主体键 model_name + model_ver，at = 快照 generated_at）。
    kind：scorecard（对同档市场基准，live_report 的行）或 closing（对收盘参照，closing_report 的行）。
    is_primary 标出现在的主模型（version.PRIMARY_MODEL），模型不用靠知识库猜哪一行是主模型。"""
    return {"scope": "scorecard", "model_name": row["model_name"], "model_ver": row["model_ver"],
            "kind": kind, "at": generated_at, "generated_at": generated_at,
            "is_primary": row["model_name"] == version.PRIMARY_MODEL[0],
            **{k: v for k, v in row.items() if k not in ("model_name", "model_ver")}}


def result(now: datetime, blocks: list, note: str | None = None, **extra) -> dict:
    """工具返回：as_of（调用时刻）、blocks（只有块里的数可以引用）、可选的 note 和其他非数字字段。"""
    out = {"as_of": now.isoformat(), "blocks": [b for b in blocks if b is not None], **extra}
    if note:
        out["note"] = note
    return out
