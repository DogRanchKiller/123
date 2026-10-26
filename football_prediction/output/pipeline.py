"""
output/pipeline.py  v1.5.0（输出层的一部分）
把数据库、模型与判断流程（analysis.analyse）连起来：按联赛缓存拟合好的模型，
对一场比赛给出完整判断。live（存档）、report（报告）、explain（单场说明）共用。
v1.4.0: latest_odds：报告与 explain 优先用 OddsPortal 多家中位数（≥3 家、24 小时内、有 1X2 与大小 2.5），
        否则用赛程表快照；存档（live._predict_upcoming）仍用赛程表赔率，不受影响。
v1.5.0: analyse_match 另取赛程表首条快照作亚盘初盘（只有一条快照时也有），给亚盘轨迹用。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

LAYER_VERSION = "1.5.0"

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
        """dc_xg 比分矩阵、rho 与自研 1X2（dc_xg / Elo / blend）"""
        m = self.xg.score_matrix(home, away)
        e = self.elo.predict(home, away)
        p_xg = matrix_1x2(m)
        p_elo = (e["home_win"], e["draw"], e["away_win"])
        return {"xg_matrix": m, "rho": float(self.xg.rho),
                "models": {"dc_xg": p_xg, "elo": p_elo, "blend": blend_1x2(p_xg, p_elo)}}


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


def latest_odds(conn: sqlite3.Connection, row: dict, now: datetime) -> tuple[dict, str]:
    """报告 / explain 用的最新赔率与来源说明。
    多家中位数（book_consensus）满足：≥ BOOK_MIN 家、有胜平负与大小 2.5、BOOK_FRESH_H 小时内抓到，
    就用它（OddsPortal 临场抓取，比约每周更新的 fixtures.csv 新）；否则用赛程表快照。"""
    try:
        cons = book_consensus(conn, row["match_id"])
    except sqlite3.OperationalError:          # 库里还没有 book_odds 表
        cons = None
    if cons and cons["n_books"] >= BOOK_MIN and devig(cons["avg_h"], cons["avg_d"], cons["avg_a"]) \
            and devig(cons["avg_over25"], cons["avg_under25"]) \
            and now - datetime.fromisoformat(cons["fetched_at"]) <= timedelta(hours=BOOK_FRESH_H):
        at = datetime.fromisoformat(cons["fetched_at"]).astimezone(_BJ)
        return ({c: cons[c] for c in FIXTURE_ODDS},
                f"多家中位数（{cons['n_books']} 家，北京 {at:%m-%d %H:%M} 抓取）")
    return fixture_odds(row), "赛程表快照（football-data）"


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
    return analyse(odds_row, inp["xg_matrix"], inp["rho"], inp["models"], first,
                   team_risks(conn, league, home, away, cache.cutoff), last, ah_open)


def _first_snapshot(conn: sqlite3.Connection, match_id: str) -> dict | None:
    """赛程表首条快照的亚盘（只有一条快照时 odds_movement 返回 None，亚盘初盘仍要用它）。"""
    r = conn.execute("SELECT ah_line, avg_ahh, avg_aha FROM odds_snapshots WHERE match_id=? "
                     "ORDER BY fetched_at LIMIT 1", (match_id,)).fetchone()
    return dict(zip(("ah_line", "avg_ahh", "avg_aha"), r)) if r else None
