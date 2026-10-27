"""
services/match_analysis.py  单场判断编排（中间层）
把数据库、模型与判断流程（output/analysis.analyse）连起来：按联赛缓存拟合好的模型，对一场比赛给出完整判断。
实盘一轮（存档、报告）、explain（单场说明）共用。原 output/pipeline.py（output 1.5.0）与
output/report.build_report 挪到这里，行为不变：
- latest_odds：报告与 explain 优先用 OddsPortal 多家中位数（≥3 家、24 小时内、有 1X2 与大小 2.5），
  否则用赛程表快照；存档（live_round.predict_upcoming）仍用赛程表赔率。
- analyse_match 另取赛程表首条快照作亚盘初盘（只有一条快照时也有），给亚盘轨迹用。
- 自研兜底（无赔率 / 缺大小球盘时的比分与胜平负、亚盘同线对照）为 dc_market（output 1.7.0）。
- explain_detail 另给赔率获取时间（Agent 工具层给现算结果标时点用）；explain_inputs 是它的元组形式，行为不变。
"""
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from football_prediction.data.fixtures import odds_movement
from football_prediction.data.loader import season_of
from football_prediction.data.oddsportal import book_consensus
from football_prediction.model_blend.blend import blend_1x2
from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.model_dc.market_dc import MarketDixonColesModel
from football_prediction.model_dc.sot_dc import SotDixonColesModel
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.model_elo.elo import EloModel
from football_prediction.output.analysis import analyse, devig, matrix_1x2
from football_prediction.output.report import report_row, upcoming_fixtures

THIN_MATCHES = 10   # 某队在该联赛历史场数少于此值视为数据少
BOOK_MIN = 3        # 报告用多家中位数：至少 3 家公司
BOOK_FRESH_H = 24   # 且 24 小时内抓到（每日任务两次，覆盖未来 30 小时）
_BJ = ZoneInfo("Asia/Shanghai")

FIXTURE_ODDS = ("avg_h", "avg_d", "avg_a", "avg_over25", "avg_under25",
                "ah_line", "avg_ahh", "avg_aha")


class LeagueModels:
    """一个联赛在 cutoff 时点拟合好的 DC / 射正 DC / xG DC / 市场版 DC / Elo。"""
    def __init__(self, conn: sqlite3.Connection, league: str, cutoff: str):
        self.dc, self.sot, self.xg, self.market, self.elo = (
            DixonColesModel(), SotDixonColesModel(), XgDixonColesModel(),
            MarketDixonColesModel(), EloModel())
        for m in (self.dc, self.sot, self.xg, self.market, self.elo):
            m.fit(conn, league, cutoff)

    def known(self, team: str) -> bool:
        return team in self.xg.attack

    def inputs(self, home: str, away: str) -> dict:
        """自研兜底 dc_market 的比分矩阵、rho（仍取 dc_xg 的，市场隐含用它，主模型不变）
        与自研 1X2（dc_market / dc_xg / Elo / blend，只作分歧提示与存档）"""
        m = self.market.score_matrix(home, away)
        e = self.elo.predict(home, away)
        p_xg = matrix_1x2(self.xg.score_matrix(home, away))
        p_elo = (e["home_win"], e["draw"], e["away_win"])
        return {"self_matrix": m, "rho": float(self.xg.rho),
                "models": {"dc_market": matrix_1x2(m), "dc_xg": p_xg, "elo": p_elo,
                           "blend": blend_1x2(p_xg, p_elo)}}


class ModelCache:
    """按联赛懒加载 LeagueModels；cutoff 之前已完赛的比赛才参与拟合（无未来信息）。"""
    def __init__(self, conn: sqlite3.Connection, cutoff: str):
        self.conn, self.cutoff, self._m = conn, cutoff, {}

    def get(self, league: str) -> LeagueModels:
        if league not in self._m:
            self._m[league] = LeagueModels(self.conn, league, self.cutoff)
        return self._m[league]


def team_risks(conn: sqlite3.Connection, league: str, home: str, away: str,
               cutoff: str) -> list[str]:
    """升班马（上赛季不在该联赛）/ 无历史数据 / 历史场数少。"""
    prev = season_of(cutoff)
    prev = f"{(int(prev[:2]) - 1) % 100:02d}{prev[:2]}"
    has_prev = conn.execute("SELECT 1 FROM matches WHERE league=? AND season=? LIMIT 1",
                            (league, prev)).fetchone() is not None
    out = []
    for t in (home, away):
        n = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE league=? AND match_date<? "
            "AND (home_team=? OR away_team=?)", (league, cutoff, t, t)).fetchone()[0]
        last = conn.execute(
            "SELECT 1 FROM matches WHERE league=? AND season=? AND (home_team=? OR away_team=?) "
            "LIMIT 1", (league, prev, t, t)).fetchone()
        if n == 0:
            out.append(f"{t} 无该联赛历史数据，自研模型用联赛均值")
        elif n < THIN_MATCHES:
            out.append(f"{t} 该联赛历史仅 {n} 场")
        elif has_prev and last is None:
            out.append(f"{t} 升班马（上赛季不在该联赛），自研模型可能低估/高估")
    return out


def fixture_odds(row: dict) -> dict:
    """fixtures 行中的赔率列"""
    return {c: row.get(c) for c in FIXTURE_ODDS}


def _pick_odds(conn: sqlite3.Connection, row: dict, now: datetime) -> tuple[dict, str, str | None]:
    """(赔率, 来源说明, 获取时间)：多家中位数取抓取时间，赛程表快照取 fixtures.fetched_at。"""
    try:
        cons = book_consensus(conn, row["match_id"])
    except sqlite3.OperationalError:          # 库里还没有 book_odds 表
        cons = None
    if cons and cons["n_books"] >= BOOK_MIN and devig(cons["avg_h"], cons["avg_d"], cons["avg_a"]) \
            and devig(cons["avg_over25"], cons["avg_under25"]) \
            and now - datetime.fromisoformat(cons["fetched_at"]) <= timedelta(hours=BOOK_FRESH_H):
        at = datetime.fromisoformat(cons["fetched_at"]).astimezone(_BJ)
        return ({c: cons[c] for c in FIXTURE_ODDS},
                f"多家中位数（{cons['n_books']} 家，北京 {at:%m-%d %H:%M} 抓取）", cons["fetched_at"])
    return fixture_odds(row), "赛程表快照（football-data）", row.get("fetched_at")


def latest_odds(conn: sqlite3.Connection, row: dict, now: datetime) -> tuple[dict, str]:
    """报告 / explain 用的最新赔率与来源说明。
    多家中位数（book_consensus）满足：≥ BOOK_MIN 家、有胜平负与大小 2.5、BOOK_FRESH_H 小时内抓到，
    就用它（OddsPortal 临场抓取，比约每周更新的 fixtures.csv 新）；否则用赛程表快照。"""
    return _pick_odds(conn, row, now)[:2]


def analyse_match(conn: sqlite3.Connection, cache: ModelCache, league: str,
                  home: str, away: str, odds_row: dict | None = None,
                  match_id: str | None = None) -> dict:
    """一场比赛的完整判断：odds_row 为最新赔率（fixtures 列名）；match_id 用于取盘口变动。
    盘口变动只在赛程表快照之间比（首条 vs 最新），不拿多家中位数与 football-data 平均跨来源比。"""
    lm = cache.get(league)
    inp = lm.inputs(home, away)
    first = last = ah_open = None
    if match_id:
        mv = odds_movement(conn, match_id)
        if mv:
            first, last = mv[0], mv[-1]
        ah_open = first or _first_snapshot(conn, match_id)
    return analyse(odds_row, inp["self_matrix"], inp["rho"], inp["models"], first,
                   team_risks(conn, league, home, away, cache.cutoff), last, ah_open)


def _first_snapshot(conn: sqlite3.Connection, match_id: str) -> dict | None:
    """赛程表首条快照的亚盘（只有一条快照时 odds_movement 返回 None，亚盘初盘仍要用它）。"""
    r = conn.execute("SELECT ah_line, avg_ahh, avg_aha FROM odds_snapshots WHERE match_id=? "
                     "ORDER BY fetched_at LIMIT 1", (match_id,)).fetchone()
    return dict(zip(("ah_line", "avg_ahh", "avg_aha"), r)) if r else None


def analyse_upcoming(conn: sqlite3.Connection, leagues, now: datetime,
                     cache: ModelCache | None = None) -> list[tuple[dict, dict, str]]:
    """未开赛场次按最新赔率现算：[(赛程行, 判断结果, 赔率来源)]，按开球时间排序。
    报告 CSV 与给接口读的本轮快照都由这一份结果生成，不重复拟合。"""
    cache = cache or ModelCache(conn, now.date().isoformat())
    out = []
    for r in upcoming_fixtures(conn, leagues, now):
        odds, src = latest_odds(conn, r, now)
        out.append((r, analyse_match(conn, cache, r["league"], r["home_team"], r["away_team"],
                                     odds, r["match_id"]), src))
    return out


def build_report(conn: sqlite3.Connection, league_names: dict[str, str], now: datetime,
                 cache: ModelCache | None = None, analysed: list | None = None) -> pd.DataFrame:
    """未开赛场次的预测报告（按最新赔率现算），按开球时间排序。analysed 为 analyse_upcoming 的结果。"""
    if analysed is None:
        analysed = analyse_upcoming(conn, league_names, now, cache)
    out = [{**report_row(r, a, league_names), "赔率来源": src} for r, a, src in analysed]
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("_kickoff", kind="stable").drop(columns="_kickoff") \
        .reset_index(drop=True)


def explain_detail(conn: sqlite3.Connection, league: str, home: str, away: str,
                   manual: dict | None, now: datetime) -> dict:
    """explain 的取数与判断：{fixture 赛程行, odds 定价赔率, odds_source 来源说明,
    odds_fetched_at 赔率获取时间（手动输入或无赔率时 None）, analysis 判断结果}。只读，不存档。
    manual 为手动输入的赔率（fixtures 列名），有它时不取盘口变动。"""
    conn.row_factory = sqlite3.Row
    try:
        fx = conn.execute("SELECT * FROM fixtures WHERE league=? AND home_team=? AND away_team=? "
                          "ORDER BY match_date LIMIT 1", (league, home, away)).fetchone()
    finally:
        conn.row_factory = None
    fx = dict(fx) if fx else None
    at = None
    if manual:
        odds, src = dict(manual), "手动输入"
    elif fx:
        odds, src, at = _pick_odds(conn, fx, now)
    else:
        odds, src = None, "无（不在赛程表，未输入）"
    a = analyse_match(conn, ModelCache(conn, now.date().isoformat()), league, home, away,
                      odds, fx["match_id"] if fx and not manual else None)
    return {"fixture": fx, "odds": odds, "odds_source": src, "odds_fetched_at": at, "analysis": a}


def explain_inputs(conn: sqlite3.Connection, league: str, home: str, away: str,
                   manual: dict | None, now: datetime) -> tuple[dict | None, dict | None, str, dict]:
    """explain 命令行用的元组形式：(赛程行, 定价赔率, 赔率来源, 判断结果)，见 explain_detail。"""
    d = explain_detail(conn, league, home, away, manual, now)
    return d["fixture"], d["odds"], d["odds_source"], d["analysis"]
