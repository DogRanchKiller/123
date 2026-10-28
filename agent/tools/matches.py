"""
agent/tools/matches.py  比赛类只读工具（docs/agent-plan.md 第 6 节）。
每个工具是一个普通函数：类型注解 + 中文说明，MCP（agent/mcp_server.py）和以后的编排框架包装同一个函数。
返回 {as_of, blocks, note?}：只有 blocks 里的数可以引用；note 是给模型看的说明，不含数字。
全部只读：库用 services.open_readonly 打开；不调用 run_round、run_near、save_prediction、爬虫。
"""
from datetime import timedelta
from typing import Any

from agent import config
from agent.tools.blocks import (
    archive_block, grading_blocks, kickoff_of, match_block, result, score_block, scorecard_block,
    view_block,
)
from football_prediction import services

MAX_HOURS, MAX_DAYS = 336, 14


def _bounded(name: str, v: int, hi: int) -> int:
    if not 1 <= v <= hi:
        raise ValueError(f"{name} 超出范围（最小 1，最大 {hi}）")
    return v


def _one_team(conn, league: str, text: str) -> str:
    """队名 → 唯一的库内队名；查不到或有多个候选时抛 ValueError（带候选），不自动挑一个。"""
    hits = services.resolve_team_name(conn, text, league)
    if len(hits) == 1 and hits[0]["match"] in ("exact", "alias", "partial"):
        return hits[0]["team"]
    names = "、".join(h["team"] for h in hits)
    raise ValueError(f"找不到球队 {text}" + (f"；候选：{names}" if names else "") + "。可先用 resolve_team 查")


def _match_blocks(conn, mid: str, info: dict, archived, near, all_grading: bool = True) -> list:
    """存档、临场存档、比分、评分。all_grading=False 时评分只取这两份存档的模型（列表用，控制体积）。"""
    models = (services.GRADED_MODELS if all_grading
              else tuple(a["model_name"] for a in (archived, near) if a))
    rows = services.read_grading(conn, mid, models)
    return [archive_block(mid, archived, "first_archive", info),
            archive_block(mid, near, "near_archive", info),
            score_block(info), *grading_blocks(mid, rows, info)]


def list_upcoming(league: str | None = None, hours: int = 72) -> dict[str, Any]:
    """本轮快照里尚未开球、hours 小时内开球的场次和每场看法（亚盘在前）。
    league：联赛代码或中文名（如 E0 / 英超），不传为全部联赛。每块 kind=current，at 为快照生成时间。"""
    _bounded("hours", hours, MAX_HOURS)
    lg = services.league_code(league) if league else None
    cfg = config.current()
    now = cfg.clock()
    cur = services.read_current(now, cfg.snapshot_path)
    if cur is None:
        return result(now, [], "还没有本轮快照（实盘一轮还没跑过）")
    until = now + timedelta(hours=hours)
    blocks = [view_block(m, cur["generated_at"], now) for m in cur["matches"]
              if (lg is None or m["league"] == lg) and kickoff_of(m) <= until]
    blocks = [b for b in blocks if b and b["kind"] == "current"]
    return result(now, blocks, None if blocks else "这个范围里没有未开赛的场次")


def get_match(match_id: str) -> dict[str, Any]:
    """单场：本轮快照看法（开球前 current；开球后改标 last_pre_kickoff，表示开球前最后一轮看法）、
    首次存档 first_archive（dc_dyn，之前的场次用市场隐含或兜底）、临场存档 near_archive、比分 score、
    赛后评分 grading（主模型、市场隐含、兜底、市场基准 market_avg 及临场档）。找不到这场时报错。"""
    cfg = config.current()
    now = cfg.clock()
    with config.connect() as conn:
        d = services.read_match(conn, match_id, cfg.snapshot_path)
        if d is None:
            raise ValueError(f"找不到比赛 {match_id}")
        info = d["match"]
        view = view_block(d["current"], d["generated_at"], now, info) if d["current"] else None
        blocks = [view, *_match_blocks(conn, match_id, info, d["archived"], d["near_archived"])]
    return result(now, blocks)


def recent_results(league: str | None = None, days: int = 3) -> dict[str, Any]:
    """最近 days 天内已开球的场次：首次存档、临场存档、比分（football-data 优先，未到时 FotMob）和
    这两份存档的赛后评分（其他模型和市场基准的评分用 get_match 查）。
    league：联赛代码或中文名，不传为全部。开球时间倒序。"""
    _bounded("days", days, MAX_DAYS)
    lg = services.league_code(league) if league else None
    now = config.current().clock()
    blocks = []
    with config.connect() as conn:
        for r in services.read_recent(conn, now, days):
            info = r["match"]
            if lg is None or info["league"] == lg:
                blocks += _match_blocks(conn, info["match_id"], info, r["archived"], r["near_archived"],
                                        all_grading=False)
    return result(now, blocks, None if blocks else "这段时间里没有已开球、有存档的场次")


def explain_fixture(league: str, home: str, away: str) -> dict[str, Any]:
    """按最新赔率现算一场未开球比赛的判断（不存档）：24 小时内有多家中位数时用它，否则用赛程表快照。
    返回 kind=live_calc 的块，at 为计算时刻，odds_fetched_at 为赔率获取时间。
    队名要能唯一对上库里的队名；比赛要在赛程表里且尚未开球（已开球的用 get_match）。"""
    code = services.league_code(league)
    now = config.current().clock()
    with config.connect() as conn:
        h, a = _one_team(conn, code, home), _one_team(conn, code, away)
        d = services.explain_detail(conn, code, h, a, None, now)
    fx = d["fixture"]
    if fx is None:
        return result(now, [], f"赛程表里没有 {h} 对 {a}，不现算")
    if kickoff_of(fx) <= now:
        return result(now, [], "这场已经开球，不再按赔率现算；用 get_match 查开球前的看法和存档")
    view = services.match_view(fx, d["analysis"], d["odds_source"])
    info = {**view, "odds_fetched_at": d["odds_fetched_at"]}
    return result(now, [match_block(fx["match_id"], "live_calc", now.isoformat(), view, info)])


def scorecard(closing: bool = False) -> dict[str, Any]:
    """实盘成绩单：每个模型（名 + 版本）一块，含已评分场数、log loss、Brier、命中率、亚盘指标，
    以及与同一档市场基准 base（赛前档 market_avg，临场档 market_avg_t24 / _t1 / _t2）的同场 log loss 差值
    diff_vs_base（负数表示比市场好）和标准误 se；is_primary 为 true 的那行是现在的主模型。
    模型名结尾 _t24 / _t1 / _t2 是临场档（开球前 23–25 小时 / 1.5 小时内 / 0.6 小时内存的），没有后缀是赛前首次存档。
    closing=true 时改为返回对收盘参照（kind=closing）：每个模型与收盘平均赔率在同一批场次上的 log loss 差
    diff_vs_close（负数表示比收盘好）和 se；closing_avg 那行是收盘自身。收盘在存档时还看不到，只作参照。"""
    cfg = config.current()
    now = cfg.clock()
    sc = services.read_scorecard(cfg.snapshot_path)
    if sc is None:
        return result(now, [], "还没有本轮快照（实盘一轮还没跑过）")
    rows, kind = (sc.get("closing") or [], "closing") if closing else (sc["scorecard"], "scorecard")
    blocks = [scorecard_block(r, sc["generated_at"], kind) for r in rows]
    if blocks:
        return result(now, blocks)
    return result(now, [], "还没有可与收盘配对的已评分场次（旧快照没有这一项）" if closing else "还没有已评分的场次")


def resolve_team(text: str, league: str | None = None) -> dict[str, Any]:
    """队名 / 别名 → 库里的队名和联赛候选（match：exact 原样、alias 别名表、partial 部分匹配、close 近似拼写）。
    只认库里的英文写法和别名表；中文队名表还没接入，中文名请换成英文再查。"""
    now = config.current().clock()
    with config.connect() as conn:
        hits = services.resolve_team_name(conn, text, services.league_code(league) if league else None)
    note = None if hits else "没有候选；中文队名表还没接入，请换成英文队名再查"
    return result(now, [], note, candidates=hits)


def team_news(league: str, team: str) -> dict[str, Any]:
    """某队下一场未开球比赛的阵容与伤停（FotMob，最新一批）：lineups.home / lineups.away 各有首发、替补、缺阵名单。
    lineup_type 为 predicted（预测首发）或 standard（正式首发）；at 为抓取时间。FotMob 只在临近开球时抓阵容。"""
    code = services.league_code(league)
    now = config.current().clock()
    with config.connect() as conn:
        t = _one_team(conn, code, team)
        fx = services.read_next_fixture(conn, code, t, now)
        lu = services.read_lineups(conn, fx["match_id"]) if fx else None
    if fx is None:
        return result(now, [], f"赛程表里没有 {t} 尚未开球的比赛")
    if lu is None:
        return result(now, [], "这场还没有阵容数据（没有 FotMob 库，或还没到抓阵容的时候）")
    # 阵容的 home / away 与块头的对阵键同名，放进 lineups 里，不覆盖队名
    body = {"team": t, "team_side": "home" if fx["home"] == t else "away", "fetched_at": lu["fetched_at"],
            "lineup_type": lu["lineup_type"], "lineups": {"home": lu["home"], "away": lu["away"]}}
    return result(now, [match_block(fx["match_id"], "team_news", lu["fetched_at"], fx, body)])
