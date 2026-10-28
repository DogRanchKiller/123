"""
services/match_read.py  只读用例（中间层）
给接口（server/）和以后的页面读：本轮快照（live_round.write_snapshot 写的 reports/latest_round.json）
里的当前看法与成绩单，加上库里主模型的首次存档和赛果。不拟合模型、不写库、不联网。
首次存档按 ARCHIVE_MODELS 顺序取（dc_dyn → 市场隐含 → dc_market：v2.0.0 之前的场次没有 dc_dyn 存档）。
展示字段（倾向、信心档、亚盘选择方）按存档时的概率现算，信心档跟存档的模型走：
dc_dyn 按首选概率分 PRIMARY_TIERS（亚盘 PRIMARY_AH_TIERS）；市场隐含有存档赔率时按 Shin 去水的最大概率
（市场档）；dc_market 按存档概率（自研档）。亚盘只有存档时有市场线才分档；稳妥线用存档里各线的五种结算
（AH_LINES ±4 之外为空）。
比分与评分同一顺序：football-data（matches）优先，没到时用只读挂上的 fotmob.db 的 fotmob_results。
read_recent 给列表附带最近几天已开球的场次（首次存档 + 比分），关注页与完赛筛选用。
存档另给市场隐含的临场档 near_archived（开球前 1.5 小时内多家中位数，近开球时的看法）；
两份存档都不计开球后才存的行。
"""
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

from football_prediction import version
from football_prediction.data.fotmob import DB_PATH as FOTMOB_DB
from football_prediction.model_market.devig import shin
from football_prediction.output.analysis import (
    AH_TIERS, LABEL, MARKET_TIERS, MODEL_TIERS, PRIMARY_AH_TIERS, PRIMARY_TIERS, ah_tier, confidence_tier,
    double_label, safe_line,
)
from football_prediction.output.derive import ah_fair_prob
from football_prediction.services.live_round import DB_PATH, LEAGUES, SNAPSHOT_PATH, _num

_KEYS = ("home_win", "draw", "away_win")
_AH_KEYS = ("win", "half_win", "push", "half_lose", "lose")


def open_readonly(db_path: str = DB_PATH, timeout: float = 10.0,
                  fotmob_path: str | None = FOTMOB_DB) -> sqlite3.Connection:
    """只读连接（SQLite URI mode=ro）：接口进程不会改库；实盘一轮写库时最多等 timeout 秒。
    库文件不存在时抛 sqlite3.OperationalError，不会新建空库。fotmob.db 存在时同样只读挂为 fm，
    用它的完赛比分（fotmob_results）补 football-data 还没到的赛果；不存在时跳过。"""
    uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout, check_same_thread=False)
    if fotmob_path and pathlib.Path(fotmob_path).exists():
        conn.execute("ATTACH DATABASE ? AS fm", (pathlib.Path(fotmob_path).resolve().as_uri() + "?mode=ro",))
    return conn


def read_snapshot(path: str = SNAPSHOT_PATH) -> dict | None:
    """本轮快照；还没跑过实盘一轮（文件不存在）时 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _started(m: dict, now: datetime) -> bool:
    if m.get("kickoff_utc"):
        return datetime.fromisoformat(m["kickoff_utc"]) <= now
    return m["match_date"] < now.date().isoformat()


def read_current(now: datetime, path: str = SNAPSHOT_PATH) -> dict | None:
    """当前列表：快照里尚未开球的场次（快照生成后已开球的剔除）。快照不存在时 None。"""
    snap = read_snapshot(path)
    if snap is None:
        return None
    return {k: snap[k] for k in ("generated_at", "system_version", "primary_model")} | {
        "matches": [m for m in snap["matches"] if not _started(m, now)]}


def read_scorecard(path: str = SNAPSHOT_PATH) -> dict | None:
    """本轮成绩单（live_report 的行）与对收盘参照（closing_report 的行；schema 1 的旧快照没有，为空）。
    快照不存在时 None。"""
    snap = read_snapshot(path)
    if snap is None:
        return None
    return {k: snap[k] for k in ("generated_at", "system_version", "primary_model", "scorecard")} | {
        "closing": snap.get("closing", [])}


_ARCHIVE_COLS = ("model_name", "model_ver", "generated_at", "p_home_win", "p_draw", "p_away_win",
                 "extra_markets", "actual_outcome", "log_loss", "brier", "ou25_log_loss",
                 "score_log_loss", "ah_line", "ah_log_loss", "ah_hit", "result_src", "scored_at")
# 首次存档的取法顺序：主模型 dc_dyn（v2.0.0 起）→ 市场隐含（v1.4.0–v1.13.0 的主模型，之后仍每场存档）→ 兜底。
ARCHIVE_MODELS = (version.PRIMARY_MODEL, version.MARKET_MODEL, version.FALLBACK_MODEL)
# 临场档只有市场隐含一族存（dc_dyn 只用历史赔率信号，临场赔率不改变它）。
NEAR_MODELS = ((version.MARKET_MODEL[0] + "_t1", version.MARKET_MODEL[1]),)


def _is_market(model_name: str) -> bool:
    """市场隐含一族（含临场档）的存档：信心档按存档赔率的 Shin 最大概率，亚盘按 AH_TIERS。"""
    return model_name.startswith(version.MARKET_MODEL[0])


def _archive_pick(p: list[float], od: dict, model_name: str) -> dict:
    """存档概率的倾向 / 双选 / 信心档。主模型 dc_dyn 按首选概率分 PRIMARY_TIERS；市场隐含有存档的 1X2
    赔率时按 Shin 最大概率分市场档；其余（dc_market）按首选概率分自研档。"""
    probs = dict(zip(_KEYS, p))
    order = sorted(probs, key=probs.get, reverse=True)
    odds = [od.get(k) for k in ("avg_h", "avg_d", "avg_a")]
    if model_name == version.PRIMARY_MODEL[0]:
        tier, hit1, hit2 = confidence_tier(probs[order[0]], PRIMARY_TIERS)
    elif _is_market(model_name) and all(o is not None and o > 1 for o in odds):
        tier, hit1, hit2 = confidence_tier(float(max(shin(odds))), MARKET_TIERS)
    else:
        tier, hit1, hit2 = confidence_tier(probs[order[0]], MODEL_TIERS)
    return {"lean": LABEL[order[0]], "double": double_label(order[:2]), "confidence": tier,
            "historical_first_hit": hit1, "historical_double_hit": hit2}


def _archive_asian(line, ah: list | None, market_line: bool, ex: dict | None = None,
                   tiers=PRIMARY_AH_TIERS) -> dict | None:
    """存档时那条线上的五种结算与选择方；只有市场线才给信心档（tiers：主模型档或旧市场存档的 AH_TIERS）。
    ex：存档 extra（各线 ah_{line} 的五种结算），用来算稳妥线；缺线时稳妥线为空。"""
    if line is None or ah is None:
        return None
    ex = ex or {}

    def home_fair(x: float) -> float | None:
        o = ex.get(f"ah_{x + 0.0:+.2f}")
        return ah_fair_prob(dict(zip(_AH_KEYS, o))) if o else None

    out = dict(zip(_AH_KEYS, ah))
    fair = ah_fair_prob(out)
    side, p_cover = ("主", fair) if fair >= 0.5 else ("客", 1 - fair)
    tier, hit = ah_tier(p_cover, tiers) if market_line else ("-", None)
    safe = safe_line(home_fair, float(line), side)
    return {"line": round(float(line) + 0.0, 2), "line_source": "市场线" if market_line else "公平线",
            "outcome": {k: _num(v) for k, v in out.items()}, "side": side,
            "p_cover": _num(p_cover), "tier": tier, "historical_hit": _num(hit),
            "safe_line": safe[0] if safe else None, "safe_cover": _num(safe[1]) if safe else None}


_PRE_KO = ("NOT (json_extract(extra_markets, '$.kickoff_utc') IS NOT NULL "
           "AND generated_at >= json_extract(extra_markets, '$.kickoff_utc'))")   # 开球后的存档不算


def _first_row(conn: sqlite3.Connection, match_id: str, models) -> tuple | None:
    """按 models 的顺序取第一个有存档的模型，其首次存档（当前版本优先）。"""
    for name, key in models:
        r = conn.execute(
            f"SELECT {','.join(_ARCHIVE_COLS)} FROM predictions WHERE match_id=? AND model_name=? "
            f"AND {_PRE_KO} ORDER BY model_ver != ?, generated_at LIMIT 1",
            (match_id, name, version.get(key))).fetchone()
        if r is not None:
            return r
    return None


def _first_archive(conn: sqlite3.Connection, match_id: str, near: bool = False) -> dict | None:
    """该场的首次存档，按 ARCHIVE_MODELS 顺序：主模型 dc_dyn；v2.0.0 之前的场次没有它时用市场隐含，再用兜底。
    near=True 时取 NEAR_MODELS 的临场档（开球前 1.5 小时内多家中位数）。"""
    try:
        r = _first_row(conn, match_id, NEAR_MODELS if near else ARCHIVE_MODELS)
    except sqlite3.OperationalError:          # 库里还没有 predictions 表
        return None
    if r is None:
        return None
    d = dict(zip(_ARCHIVE_COLS, r))
    ex = json.loads(d.pop("extra_markets") or "{}")
    od = ex.get("odds") if isinstance(ex.get("odds"), dict) else {}
    od = {k: v for k, v in od.items() if v is not None}   # 无赔率场次 dc_dyn 存的是全空赔率列
    market_line = od.get("ah_line") is not None or d["ah_line"] is not None
    line = d["ah_line"] if d["ah_line"] is not None else od.get("ah_line", ex.get("ah_fair_line"))
    ah = ex.get(f"ah_{float(line) + 0.0:+.2f}") if line is not None else None
    probs = [_num(d[k]) for k in ("p_home_win", "p_draw", "p_away_win")]
    return {
        "model_name": d["model_name"], "model_version": d["model_ver"],
        "generated_at": d["generated_at"], "kickoff_utc": ex.get("kickoff_utc"),
        "probabilities": probs, **_archive_pick(probs, od, d["model_name"]),
        "asian": _archive_asian(line, ah, market_line, ex,
                                PRIMARY_AH_TIERS if d["model_name"] == version.PRIMARY_MODEL[0] else AH_TIERS),
        "likely_scores": [{"score": s["score"], "prob": _num(s["prob"])}
                          for s in ex.get("top5_scores", [])],
        "over25": _num(ex.get("over_2.5")),
        "odds": od or None,
        "horizon": ex.get("horizon", "pre"), "n_books": ex.get("n_books"),
        "hours_to_ko": _num(ex.get("hours_to_ko")),
        "scored": d["scored_at"] is not None,
        **{k: (_num(d[k]) if k not in ("actual_outcome", "result_src", "scored_at") else d[k])
           for k in ("actual_outcome", "log_loss", "brier", "ou25_log_loss", "score_log_loss",
                     "ah_log_loss", "ah_hit", "result_src", "scored_at")},
    }


def _fotmob_score(conn: sqlite3.Connection, match_id: str) -> tuple | None:
    try:
        return conn.execute("SELECT home_goals, away_goals, fetched_at FROM fm.fotmob_results "
                            "WHERE match_id=?", (match_id,)).fetchone()
    except sqlite3.OperationalError:          # 没挂 fotmob.db
        return None


_INFO_SQL = (   # 对阵来源，按顺序取第一个查到的
    ("matches", "SELECT league, match_date, home_team, away_team, home_goals, away_goals, fetched_at "
                "FROM matches WHERE match_id=?"),
    ("fixtures", "SELECT league, match_date, home_team, away_team, kickoff_utc FROM fixtures WHERE match_id=?"),
    ("archive", "SELECT json_extract(extra_markets, '$.match.league'), json_extract(extra_markets, '$.match.match_date'), "
                "json_extract(extra_markets, '$.match.home'), json_extract(extra_markets, '$.match.away'), "
                "json_extract(extra_markets, '$.kickoff_utc') FROM predictions "
                "WHERE match_id=? AND json_extract(extra_markets, '$.match.home') IS NOT NULL "
                "ORDER BY generated_at DESC LIMIT 1"),
)


def _match_info(conn: sqlite3.Connection, match_id: str) -> dict | None:
    """对阵与比分：完赛表 matches 优先，其次赛程表 fixtures（每次刷新整表替换，只有近期场次），
    再次存档 extra 里记下的对阵（fixtures 换掉、football-data 赛果未到的场次；早于记对阵的旧存档没有）。
    football-data 赛果没到时用 FotMob 比分（与评分同一顺序，score_source 标明来源）。"""
    for table, sql in _INFO_SQL:
        try:
            r = conn.execute(sql, (match_id,)).fetchone()
        except sqlite3.OperationalError:
            continue
        if r is None:
            continue
        lg, d, home, away, *rest = r
        info = {"match_id": match_id, "league": lg, "league_name": LEAGUES.get(lg, lg),
                "home": home, "away": away, "match_date": d, "kickoff_utc": None,
                "score": None, "score_source": None, "score_fetched_at": None}
        if table == "matches" and rest[0] is not None:
            info |= {"score": {"home": rest[0], "away": rest[1]}, "score_source": "football-data",
                     "score_fetched_at": rest[2]}
        if table != "matches":
            info["kickoff_utc"] = rest[0]
        if info["score"] is None and (fm := _fotmob_score(conn, match_id)):
            info |= {"score": {"home": fm[0], "away": fm[1]}, "score_source": "fotmob",
                     "score_fetched_at": fm[2]}
        return info
    return None


def read_match(conn: sqlite3.Connection, match_id: str, path: str = SNAPSHOT_PATH) -> dict | None:
    """单场详情：本轮看法（快照里有才给，开球后也保留最后一轮的看法）+ 主模型首次存档
    + 主模型临场档（near_archived，没有时 None）+ 赛果。
    快照、matches、fixtures、存档里记下的对阵都没有这场（不知道对阵）时 None。只读。"""
    snap = read_snapshot(path)
    current = next((m for m in (snap or {}).get("matches", []) if m["match_id"] == match_id), None)
    info = _match_info(conn, match_id)
    if current is None and info is None:
        return None
    archived = _first_archive(conn, match_id)
    base = {k: current[k] for k in ("match_id", "league", "league_name", "home", "away",
                                    "kickoff_utc", "match_date")} if current else {}
    match = {"score": None, "score_source": None, "score_fetched_at": None, **(info or {}), **base}
    if not match.get("kickoff_utc"):
        match["kickoff_utc"] = archived["kickoff_utc"] if archived else None
    return {"match": match, "current": current, "archived": archived,
            "near_archived": _first_archive(conn, match_id, near=True),
            "generated_at": snap["generated_at"] if snap else None}


RECENT_DAYS = 3        # 列表附带的最近已开球场次：开球在 now 之前这么多天以内
ARCHIVE_LEAD_DAYS = 8  # 存档最早在开球前约一周（fixtures.csv 的范围），候选按存档时间多放这么多天


def read_recent(conn: sqlite3.Connection, now: datetime, days: int = RECENT_DAYS) -> list[dict]:
    """最近 days 天内已开球、有 ARCHIVE_MODELS 任一首次存档的场次：对阵与比分 + 首次存档 + 临场档，开球时间倒序。
    对阵取 matches / fixtures / 存档里记下的对阵；三处都没有的（记对阵之前的旧存档、且已被赛程表换掉）跳过。"""
    names = [m[0] for m in ARCHIVE_MODELS]
    since = (now - timedelta(days=days + ARCHIVE_LEAD_DAYS)).isoformat()
    try:
        ids = [r[0] for r in conn.execute(
            f"SELECT DISTINCT match_id FROM predictions WHERE model_name IN ({','.join('?' * len(names))}) "
            "AND generated_at >= ?", (*names, since))]
    except sqlite3.OperationalError:          # 库里还没有 predictions 表
        return []
    out = []
    for mid in ids:
        info = _match_info(conn, mid)
        archived = _first_archive(conn, mid) if info else None
        if archived is None:
            continue
        info["kickoff_utc"] = info["kickoff_utc"] or archived["kickoff_utc"]
        ko = (datetime.fromisoformat(info["kickoff_utc"]) if info["kickoff_utc"]
              else datetime.fromisoformat(info["match_date"] + "T00:00:00+00:00"))
        if _started(info, now) and ko >= now - timedelta(days=days):
            out.append({"match": info, "archived": archived,
                        "near_archived": _first_archive(conn, mid, near=True)})
    return sorted(out, key=lambda x: x["match"]["kickoff_utc"] or x["match"]["match_date"], reverse=True)
