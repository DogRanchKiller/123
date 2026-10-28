"""
services/team_read.py  按队名的只读用例（中间层）
给 Agent 工具层（agent/tools）读，以后接口也可以用：队名解析、某队最近几场赛果、下一场赛程、
某场阵容 / 伤停（只读挂上的 fotmob.db）、某场的赛后评分行。不拟合模型、不写库、不联网。
- 队名解析只用库里出现过的队名、data/loader.TEAM_ALIASES 和中文队名表 data/team_zh.json
  （库里队名 → 中文名；网站 web/src/features/match/team-zh.json 是它的副本，tests/test_team_zh.py 检查一致）。
- 比分与 match_read 同一顺序：football-data（matches）优先，没到时用 fotmob_results。
- 评分行只取开球前存的行（与首次存档同一条件），result_src 为空的旧行按 fd（与 review/store 一致）。
- 知识库建块（agent/kb）用的两个读法：有存档的场次 id、某场按来源分开的比分（不合并，各带获取时间）。
"""
import difflib
import functools
import json
import pathlib
import sqlite3
from datetime import datetime

from football_prediction import version
from football_prediction.data.loader import TEAM_ALIASES
from football_prediction.services.live_round import LEAGUES, _num
from football_prediction.services.match_read import _PRE_KO, _fotmob_score, _match_info, _started

MARKET_NAME = "market_avg"
# 单场评分默认取的模型：主模型 dc_dyn、市场隐含（v2.0.0 前的主模型）及其临场档、兜底、市场基准及其临场档
GRADED_MODELS = (version.PRIMARY_MODEL[0], version.MARKET_MODEL[0], version.MARKET_MODEL[0] + "_t1",
                 version.FALLBACK_MODEL[0], MARKET_NAME, MARKET_NAME + "_t1")
GRADING_COLS = ("actual_outcome", "log_loss", "brier", "ou25_log_loss", "score_log_loss",
                "ah_line", "ah_log_loss", "ah_hit")
TEAM_ZH_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "team_zh.json"


@functools.cache
def team_zh() -> dict[str, str]:
    """中文队名表：库里队名 → 中文名（只读，进程内缓存）。"""
    return json.loads(TEAM_ZH_PATH.read_text(encoding="utf-8"))


def league_code(text: str) -> str:
    """联赛代码或中文名 → football-data 代码；不认识时抛 ValueError（带可用列表）。"""
    for code, name in LEAGUES.items():
        if text.strip() in (code, name):
            return code
    raise ValueError(f"未知联赛 {text}；可用：" + "、".join(f"{c}/{n}" for c, n in LEAGUES.items()))


def _teams(conn: sqlite3.Connection, league: str | None) -> list[tuple[str, str]]:
    """库里出现过的 (队名, 联赛)：完赛表与赛程表。"""
    where, args = ("WHERE league=?", (league,)) if league else ("", ())
    return sorted({(t, lg) for t, lg in conn.execute(
        f"SELECT home_team, league FROM matches {where} UNION SELECT away_team, league FROM matches {where} "
        f"UNION SELECT home_team, league FROM fixtures {where} UNION SELECT away_team, league FROM fixtures {where}",
        args * 4)})


def resolve_team_name(conn: sqlite3.Connection, text: str, league: str | None = None) -> list[dict]:
    """队名 → 库里的队名候选 [{team, league, match}]，按下面的顺序取第一层有结果的：
    exact（原样）→ alias（不分大小写，原样或 TEAM_ALIASES 两边任一写法）→ partial（不区分大小写的子串，至少 3 个字符）
    → zh（中文名原样）→ zh_partial（中文名的子串，至少 2 个字，如「马德里」得到两队）
    → close（difflib 近似拼写）。"""
    s = text.strip()
    teams = _teams(conn, league)
    if not s:
        return []
    zh = team_zh()
    low = s.lower()
    aliases = {k.lower(): v for k, v in TEAM_ALIASES.items()}
    std = aliases.get(low, s).lower()
    same = {std} | {k for k, v in aliases.items() if v.lower() == std}   # 别名表两边任一写法，不分大小写
    tiers = (
        ("exact", [x for x in teams if x[0] == s]),
        ("alias", [x for x in teams if x[0].lower() in same]),
        ("partial", [x for x in teams if len(low) >= 3 and low in x[0].lower()]),
        ("zh", [x for x in teams if zh.get(x[0]) == s]),
        ("zh_partial", [x for x in teams if len(s) >= 2 and s in zh.get(x[0], "")]),
        ("close", [x for x in teams if x[0] in difflib.get_close_matches(
            s, [t for t, _ in teams], n=5, cutoff=0.6)]),
    )
    for how, hits in tiers:
        if hits:
            return [{"team": t, "league": lg, "league_name": LEAGUES.get(lg, lg), "match": how}
                    for t, lg in hits]
    return []


def read_team_recent(conn: sqlite3.Connection, league: str, team: str, n: int = 5) -> list[dict]:
    """某队最近 n 场完赛（对阵与比分，开球倒序）。football-data 赛果优先；
    只有 FotMob 比分、football-data 还没到的场次也算（对阵按 match_read 的顺序找）。"""
    rows = conn.execute(
        "SELECT match_id FROM matches WHERE league=? AND (home_team=? OR away_team=?) "
        "AND home_goals IS NOT NULL ORDER BY match_date DESC LIMIT ?", (league, team, team, n)).fetchall()
    ids = [r[0] for r in rows]
    try:
        pending = [r[0] for r in conn.execute(
            "SELECT match_id FROM fm.fotmob_results WHERE match_id NOT IN (SELECT match_id FROM matches)")]
    except sqlite3.OperationalError:          # 没挂 fotmob.db
        pending = []
    out = []
    for mid in ids + pending:
        info = _match_info(conn, mid)
        if info and info["score"] and info["league"] == league and team in (info["home"], info["away"]):
            out.append(info)
    out.sort(key=lambda m: (m["match_date"], m["kickoff_utc"] or ""), reverse=True)
    return out[:n]


def read_next_fixture(conn: sqlite3.Connection, league: str, team: str, now: datetime) -> dict | None:
    """某队在赛程表里尚未开球的下一场（对阵、开球时间）；没有时 None。"""
    rows = conn.execute(
        "SELECT match_id, league, match_date, kickoff_utc, home_team, away_team FROM fixtures "
        "WHERE league=? AND (home_team=? OR away_team=?) ORDER BY COALESCE(kickoff_utc, match_date)",
        (league, team, team)).fetchall()
    for mid, lg, d, ko, home, away in rows:
        m = {"match_id": mid, "league": lg, "league_name": LEAGUES.get(lg, lg), "home": home,
             "away": away, "match_date": d, "kickoff_utc": ko}
        if not _started(m, now):
            return m
    return None


def read_lineups(conn: sqlite3.Connection, match_id: str) -> dict | None:
    """某场最新一批阵容 / 伤停（fm.lineups）：{fetched_at, lineup_type, home/away: {starters, subs,
    unavailable}}。lineup_type 为 predicted（预测首发）或 standard（正式首发）。
    没挂 fotmob.db 或还没抓到时 None。"""
    try:
        last = conn.execute("SELECT MAX(fetched_at) FROM fm.lineups WHERE match_id=?",
                            (match_id,)).fetchone()[0]
    except sqlite3.OperationalError:          # 没挂 fotmob.db
        return None
    if last is None:
        return None
    rows = conn.execute(
        "SELECT lineup_type, side, name, role, position_id, detail FROM fm.lineups "
        "WHERE match_id=? AND fetched_at=? ORDER BY side, role, position_id, name",
        (match_id, last)).fetchall()
    keys = {"starter": "starters", "sub": "subs", "unavailable": "unavailable"}
    out = {"fetched_at": last, "lineup_type": rows[0][0],
           **{s: {k: [] for k in keys.values()} for s in ("home", "away")}}
    for _, side, name, role, pos, detail in rows:
        if side in ("home", "away") and role in keys:
            out[side][keys[role]].append({"name": name, "position_id": pos, "detail": detail})
    return out


def read_grading(conn: sqlite3.Connection, match_id: str,
                 models: tuple[str, ...] | None = GRADED_MODELS) -> list[dict]:
    """某场已评分的存档行（开球前存的），每个模型名 + 版本一行，按 models 的顺序；models=None 时取全部。
    每行：model_name、model_ver、generated_at、scored_at、result_src（空的旧行按 fd）和指标列。"""
    try:
        rows = conn.execute(
            f"SELECT model_name, model_ver, generated_at, scored_at, result_src, {','.join(GRADING_COLS)} "
            f"FROM predictions WHERE match_id=? AND scored_at IS NOT NULL AND {_PRE_KO} "
            f"ORDER BY generated_at", (match_id,)).fetchall()
    except sqlite3.OperationalError:          # 库里还没有 predictions 表
        return []
    out, seen = [], set()
    for name, ver, gen, scored, src, *vals in rows:
        if (models is not None and name not in models) or (name, ver) in seen:
            continue
        seen.add((name, ver))
        metrics = {k: (v if k == "actual_outcome" else _num(v)) for k, v in zip(GRADING_COLS, vals)}
        out.append({"model_name": name, "model_ver": ver, "generated_at": gen, "scored_at": scored,
                    "result_src": src or "fd", **metrics})
    order = {m: i for i, m in enumerate(models or ())}
    return sorted(out, key=lambda r: order.get(r["model_name"], len(order)))


def read_archived_ids(conn: sqlite3.Connection) -> list[str]:
    """有开球前存档的全部场次 id（按最早存档时间排序），知识库建比赛块时逐场读。没有 predictions 表时 []。"""
    try:
        return [r[0] for r in conn.execute(
            f"SELECT match_id FROM predictions WHERE {_PRE_KO} GROUP BY match_id ORDER BY MIN(generated_at)")]
    except sqlite3.OperationalError:
        return []


def read_scores(conn: sqlite3.Connection, match_id: str) -> list[dict]:
    """某场按来源分开的比分：[{source, home, away, fetched_at}]，football-data 在前、FotMob 在后，
    各用自己的获取时间（不合并、不互相回填）。没挂 fotmob.db 时只有 football-data 那条；都没有时 []。"""
    out = []
    r = conn.execute("SELECT home_goals, away_goals, fetched_at FROM matches WHERE match_id=?",
                     (match_id,)).fetchone()
    if r is not None and r[0] is not None:
        out.append({"source": "football-data", "home": r[0], "away": r[1], "fetched_at": r[2]})
    if fm := _fotmob_score(conn, match_id):
        out.append({"source": "fotmob", "home": fm[0], "away": fm[1], "fetched_at": fm[2]})
    return out
