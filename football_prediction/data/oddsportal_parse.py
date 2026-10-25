"""
data/oddsportal_parse.py  v1.6.0
OddsPortal 纯解析（不联网、不读库）：队名规范化与配对、比赛链接 ↔ fixtures 配对、
OddsHarvester 输出的盘口键与逐家赔率解析。从 data/oddsportal.py 拆出（行为不变）。
v1.6.0: NAME_ALIASES 补意甲 / 法甲（PSG）。FotMob 队名也先过这张表。
修改此文件后请同步更新 version.py 中 "data" 的版本号。
"""
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher

LAYER_VERSION = "1.6.0"

LEAGUE_SLUGS = {   # football-data 联赛代码 -> OddsPortal 联赛 slug
    "E0": "england-premier-league", "D1": "germany-bundesliga", "SP1": "spain-laliga",
    "I1": "italy-serie-a", "F1": "france-ligue-1",
}
MATCH_MIN = 0.6          # 队名配对的最低相似度

# 队名别名：OddsPortal 写法（规范化后）-> football-data 写法（规范化后）
NAME_ALIASES = {   # 2026-10-24 用三联赛 2526/2627 全部球队核对过
    "atlmadrid": "athmadrid", "bmonchengladbach": "mgladbach", "depacoruna": "lacoruna",
    "racingsantander": "santander", "manchesterunited": "manchesterutd",
    "manchestercity": "mancity", "newcastleutd": "newcastle", "nottingham": "nottmforest",
    "eintrachtfrankfurt": "einfrankfurt", "bayerleverkusen": "leverkusen",
    "athleticbilbao": "athbilbao", "rayovallecano": "vallecano", "espanyol": "espanol",
    "realsociedad": "sociedad", "celtavigo": "celta",
    # v1.6.0：意甲 / 法甲（2026-10-25 用 2627 全部球队核对；其余队名靠包含关系配上）
    "psg": "parissg", "parissaintgermain": "parissg",
}


# ---------- 队名配对 ----------
def norm_name(name: str) -> str:
    """去重音、小写、只留字母数字，再查别名。"""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return NAME_ALIASES.get(s, s)


def name_sim(a: str, b: str) -> float:
    a, b = norm_name(a), norm_name(b)
    if a == b:
        return 1.0
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def link_teams(link: str) -> tuple[str, str] | None:
    """比赛页链接 .../h2h/{队A-id}/{队B-id}/#xxx -> (队A, 队B)；链接里两队按字母序，不分主客。"""
    m = re.search(r"/h2h/([^/]+)/([^/#]+)", link)
    if not m:
        return None
    strip = lambda s: re.sub(r"-[A-Za-z0-9]{8}$", "", s).replace("-", " ")
    return strip(m.group(1)), strip(m.group(2))


def pair_score(teams: tuple[str, str], home: str, away: str) -> float:
    """两队无序配对的相似度（取两个方向中较好的一个，再取两队中较差的一个）。"""
    t1, t2 = teams
    return max(min(name_sim(t1, home), name_sim(t2, away)),
               min(name_sim(t1, away), name_sim(t2, home)))


def match_links(links: list[dict], fixtures: list[dict]) -> dict[str, dict]:
    """
    links: OddsHarvester --links-only 的记录（match_link, league, kickoff_utc）。
    fixtures: {match_id, league, match_date, home_team, away_team, ...}。
    同联赛、日期差 ≤1 天，按相似度从高到低贪心一一配对。返回 {match_link: fixture}。
    """
    slug_to_code = {v: k for k, v in LEAGUE_SLUGS.items()}
    cands = []
    for ln in links:
        teams = link_teams(ln["match_link"])
        code = slug_to_code.get(ln.get("league"))
        if teams is None or code is None or "/inplay-odds/" in ln["match_link"]:
            continue
        ld = _link_date(ln.get("kickoff_utc"))
        for fx in fixtures:
            if fx["league"] != code:
                continue
            if ld is not None and abs((date.fromisoformat(fx["match_date"]) - ld).days) > 1:
                continue
            s = pair_score(teams, fx["home_team"], fx["away_team"])
            if s >= MATCH_MIN:
                cands.append((s, ln["match_link"], fx["match_id"], fx))
    out, used = {}, set()
    for s, link, mid, fx in sorted(cands, key=lambda c: -c[0]):
        if link in out or mid in used:
            continue
        out[link] = fx
        used.add(mid)
    return out


def _link_date(raw) -> date | None:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------- 解析 OddsHarvester 输出 ----------
_SEL = {"1x2": ("1", "X", "2"), "ou": ("odds_over", "odds_under"),
        "ah": ("team1_handicap", "team2_handicap")}


def _odd(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 1.0 else None


def market_of(key: str) -> tuple[str, float] | None:
    """'1x2_market' -> ('1x2', 0)；'over_under_2_5_market' -> ('ou', 2.5)；
    'asian_handicap_-0_25_market' -> ('ah', -0.25)。其它返回 None。"""
    if key == "1x2_market":
        return "1x2", 0.0
    m = re.fullmatch(r"(over_under|asian_handicap)_([+-]?\d+)(?:_(\d+))?_market", key)
    if not m:
        return None
    whole, frac = m.group(2), m.group(3)
    line = abs(int(whole)) + (int(frac) / 10 ** len(frac) if frac else 0.0)
    line = -line if whole.startswith("-") else line
    return ("ou" if m.group(1) == "over_under" else "ah"), line


def parse_record(rec: dict) -> list[tuple]:
    """一场比赛 -> [(bookmaker, market, line, o1, o2, o3, open1, open2, open3, opened_at)]。
    被庄家撤下的选项（blocked_outcomes）记为空。"""
    rows = []
    for key, books in rec.items():
        mk = market_of(key)
        if mk is None or not isinstance(books, list):
            continue
        market, line = mk
        sels = _SEL[market]
        for b in books:
            blocked = set(b.get("blocked_outcomes") or [])
            cur = [None if s in blocked else _odd(b.get(s)) for s in sels]
            hist = b.get("odds_history_data") or []
            opens, opened = [], []
            for i in range(len(sels)):
                op = (hist[i].get("opening_odds") if i < len(hist) and hist[i] else None) or {}
                opens.append(_odd(op.get("odds")))
                if op.get("timestamp"):
                    opened.append(op["timestamp"])
            if all(v is None for v in cur):
                continue
            cur += [None] * (3 - len(cur))
            opens += [None] * (3 - len(opens))
            rows.append((b.get("bookmaker_name") or "?", market, line, *cur, *opens,
                         min(opened) if opened else None))
    return rows


def record_orientation(rec: dict, fx: dict) -> bool:
    """抓到的主客队是否与 fixtures 一致（OddsPortal 的 home_team 才是主队）。"""
    h, a = rec.get("home_team", ""), rec.get("away_team", "")
    return min(name_sim(h, fx["home_team"]), name_sim(a, fx["away_team"])) >= \
        min(name_sim(h, fx["away_team"]), name_sim(a, fx["home_team"]))
