"""
data/fotmob_parse.py  v1.2.0
FotMob 页面解析（纯函数，不联网、不读库）。数据来自 HTML 页里的 <script id="__NEXT_DATA__">，
不调用 /api/（robots.txt 禁止）。
  league_matches：联赛赛程页 → 每场 FotMob id、页面地址、主客队、开球时间、状态、完赛比分、是否判负。
  compact_match：比赛页 → 精简记录（首发/替补/伤停、球员分钟与 xG/xA、逐脚射门、全队 xG）。
  pair_matches：FotMob 场次 ↔ 本库 match_id（队名映射相似度 ≥0.9 + 主客方向一致 + 日期 ±1 天）。
  2324–2627 三联赛核对：完赛场次除 1 场中止重赛、1 场改期外全部配上。
v1.1.0: league_matches 增加 awarded 与 score（完赛比分，供 fotmob.collect_results 提前评分）。
v1.2.0: LEAGUE_IDS 加英冠 E1 / 荷甲 N1 / 葡超 P1 / 苏超 SC0 / 比甲 B1 / 土超 T1（2026-10-25 用 2627 赛程核对），
        FOTMOB_ALIASES 补 QPR、Sittard、Sporting、Hearts、OH Leuven、Basaksehir。
修改此文件后请同步更新 version.py 中 "data_fotmob" 的版本号。
"""
import json
import re
from datetime import date

from football_prediction.data.oddsportal_parse import name_sim, norm_name

LAYER_VERSION = "1.2.0"

# football-data 联赛代码 -> (FotMob 联赛 id, 页面 slug)；2026-10-25 核对过（I1 / F1 用 2627 赛程核对，
# PSG 靠 oddsportal_parse.NAME_ALIASES 配上）
LEAGUE_IDS = {"E0": (47, "premier-league"), "D1": (54, "bundesliga"), "SP1": (87, "laliga"),
              "I1": (55, "serie"), "F1": (53, "ligue-1"),
              "E1": (48, "championship"), "N1": (57, "eredivisie"), "P1": (61, "liga-portugal"),
              "SC0": (64, "premiership"), "B1": (40, "first-division-a"), "T1": (71, "super-lig")}
TEAM_MIN = 0.9          # 队名映射的最低相似度（0.6 会把 Real Madrid 配到 Ath Madrid）

# 队名别名：FotMob 写法（规范化后）-> football-data 写法（规范化后）。对不上的新队名补在这里。
FOTMOB_ALIASES = {   # 2026-10-25 用 E0/D1/SP1 2324–2627 全部球队核对过
    "nottinghamforest": "nottmforest", "bayernmunchen": "bayernmunich",
    "borussiamonchengladbach": "mgladbach", "athleticclub": "athbilbao",
    "atleticomadrid": "athmadrid", "deportivoacoruna": "lacoruna",
    "queensparkrangers": "qpr", "fortunasittard": "forsittard", "sportingcp": "splisbon",
    "heartofmidlothian": "hearts", "ohleuven": "oudheverleeleuven", "basaksehir": "buyuksehyr",
}

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def next_data(html: str) -> dict | None:
    m = _NEXT_RE.search(html)
    return json.loads(m.group(1)) if m else None


def season_param(season: str) -> str:
    """"2425" -> "2024/2025"（赛程页的 ?season= 参数）"""
    a = 2000 + int(season[:2])
    return f"{a}/{a + 1}"


def fm_norm(name: str) -> str:
    s = norm_name(name)
    return FOTMOB_ALIASES.get(s, s)


def fm_sim(fotmob_name: str, our_name: str) -> float:
    return name_sim(fm_norm(fotmob_name), our_name)


def _score(s) -> tuple[int, int] | None:
    """scoreStr "2 - 1" → (2, 1)；其他格式返回 None。"""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def league_matches(nd: dict) -> list[dict]:
    """赛程页 __NEXT_DATA__ → [{fotmob_id, page_url, home, away, kickoff_utc, started, finished, cancelled,
    awarded, score}]；score 只在完赛时给 (主, 客)，否则 None。"""
    pp = nd.get("props", {}).get("pageProps", {})
    out = []
    for m in (pp.get("fixtures") or {}).get("allMatches") or []:
        st = m.get("status") or {}
        out.append({"fotmob_id": str(m["id"]), "page_url": m["pageUrl"].split("#")[0],
                    "home": m["home"]["name"], "away": m["away"]["name"],
                    "kickoff_utc": st.get("utcTime"), "started": bool(st.get("started")),
                    "finished": bool(st.get("finished")), "cancelled": bool(st.get("cancelled")),
                    "awarded": bool(st.get("awarded")),
                    "score": _score(st.get("scoreStr")) if st.get("finished") else None})
    return out


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _sub_minute(p: dict, kind: str) -> int | None:
    for e in ((p.get("performance") or {}).get("substitutionEvents") or []):
        if e.get("type") == kind:
            return e.get("time")
    return None


def _player_stats(p: dict) -> dict:
    vals = {}
    for g in p.get("stats") or []:
        for v in (g.get("stats") or {}).values():
            k = v.get("key")
            if k and k not in vals:
                vals[k] = _num((v.get("stat") or {}).get("value"))
    return vals


def compact_match(pp: dict) -> dict:
    """比赛页 pageProps → 精简记录。side 为 "home" / "away"（按 general.homeTeam.id 判断）。"""
    g, c = pp["general"], pp.get("content") or {}
    hid = g["homeTeam"]["id"]
    side_of = lambda tid: "home" if tid == hid else "away"
    lu = c.get("lineup") or {}
    lineup = []
    for key, side in (("homeTeam", "home"), ("awayTeam", "away")):
        t = lu.get(key) or {}
        for role, plist in (("starter", t.get("starters")), ("sub", t.get("subs")),
                            ("unavailable", t.get("unavailable"))):
            for p in plist or []:
                lineup.append({
                    "side": side, "player_id": p.get("id"), "name": p.get("name"), "role": role,
                    "position_id": p.get("positionId") or p.get("usualPlayingPositionId"),
                    "sub_minute": _sub_minute(p, "subIn" if role == "sub" else "subOut"),
                    "detail": json.dumps(p["unavailability"], ensure_ascii=False)
                    if role == "unavailable" and p.get("unavailability") else None})
    players = []
    for p in (c.get("playerStats") or {}).values():
        s = _player_stats(p)
        if s.get("minutes_played") is None:
            continue
        players.append({"side": side_of(p.get("teamId")), "player_id": p.get("id"),
                        "name": p.get("name"), "minutes": s["minutes_played"],
                        "xg": s.get("expected_goals") or 0.0, "xa": s.get("expected_assists") or 0.0,
                        "npxg": s.get("expected_goals_non_penalty") or 0.0})
    shots = [{"shot_id": s.get("id"), "side": side_of(s.get("teamId")), "player_id": s.get("playerId"),
              "minute": s.get("min"), "xg": _num(s.get("expectedGoals")),
              "own_goal": int(bool(s.get("isOwnGoal"))), "situation": s.get("situation")}
             for s in ((c.get("shotmap") or {}).get("shots") or [])]
    return {"fotmob_id": str(g["matchId"]), "kickoff_utc": g.get("matchTimeUTCDate"),
            "started": bool(g.get("started")), "finished": bool(g.get("finished")),
            "home": g["homeTeam"]["name"], "away": g["awayTeam"]["name"],
            "lineup_type": lu.get("lineupType"), "lineup": lineup, "players": players,
            "shots": shots, "team_xg": _team_xg(c.get("stats"))}


def _team_xg(stats) -> list[float] | None:
    """stats.Periods.All 里 key=expected_goals 的 [主, 客]。"""
    for grp in (((stats or {}).get("Periods") or {}).get("All") or {}).get("stats") or []:
        for s in grp.get("stats") or []:
            if s.get("key") == "expected_goals" and s.get("type") != "title":
                vals = [_num(v) for v in s.get("stats") or []]
                if len(vals) == 2 and None not in vals:
                    return vals
    return None


def team_map(fm_names, our_names) -> dict[str, str]:
    """FotMob 队名 -> 本库队名：按相似度从高到低一一对应，低于 TEAM_MIN 的不映射。"""
    out, taken = {}, set()
    scored = sorted(((fm_sim(f, o), f, o) for f in set(fm_names) for o in set(our_names)), reverse=True)
    for s, f, o in scored:
        if s < TEAM_MIN:
            break
        if f not in out and o not in taken:
            out[f] = o
            taken.add(o)
    return out


def pair_matches(fm: list[dict], ours: list[dict]) -> dict[str, dict]:
    """fm: league_matches 的记录；ours: {match_id, match_date, home_team, away_team}。
    先建队名映射，再按（主队, 客队）且日期差 ≤1 天配对。返回 {fotmob_id: our_row}。"""
    tm = team_map([n for f in fm for n in (f["home"], f["away"])],
                  [n for o in ours for n in (o["home_team"], o["away_team"])])
    idx = {}
    for o in ours:
        idx.setdefault((o["home_team"], o["away_team"]), []).append(o)
    out = {}
    for f in fm:
        if not f.get("kickoff_utc"):
            continue
        fd = date.fromisoformat(f["kickoff_utc"][:10])
        for o in idx.get((tm.get(f["home"]), tm.get(f["away"])), []):
            if abs((date.fromisoformat(o["match_date"]) - fd).days) <= 1:
                out[f["fotmob_id"]] = o
                break
    return out
