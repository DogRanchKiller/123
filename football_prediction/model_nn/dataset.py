"""
model_nn/dataset.py  v0.1.0
model_nn 的样本与特征：每场按它自己的 cutoff 生成特征（只用 match_date < 该场日期的比赛）。
  一个联赛按日期顺序扫一遍：先用当前状态给当天所有比赛出特征，当天全部出完再用赛果更新状态，
  所以同日比赛互不可见，与 features/builder.py 的 cutoff 口径相同（cutoff 不含当天）；
  不先算整个窗口的统计再贴回每一场。
  状态：Elo（净胜球加权，规则同 model_elo；按 modules.md 不引用别的模型族，这里自带一份）、
  进失球 / 射正 / xG 的指数加权均值（向联赛均值收缩）、休息天数、联赛场均进球。
  超过 RESET_DAYS 天没在本联赛出场的队（升班马、降级后回来）按新队处理。
  变体 B 的市场特征只用该场赛前平均赔率（Avg*，不用收盘价）：去水 1X2、大小 2.5、亚盘，
  以及 model_market.implied.fit_lambdas 反推的 λ（rho = DEFAULT_RHO；modules.md 登记的例外）。
  特征表缓存在 checkpoints/nn_features/（gitignore，可重建），每行带 cutoff_date 和 features_ver。
修改此文件后请同步更新 version.py 中 "model_nn" 的版本号。
"""
import hashlib
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_market.implied import DEFAULT_RHO, fair_probs, fit_lambdas

LAYER_VERSION = "0.1.0"
FEATURES_VER = "1"          # 特征定义变了就加一，旧缓存自动失效
CACHE_DIR = Path("checkpoints/nn_features")

ELO_K, ELO_HOME, ELO_BASE = 20.0, 60.0, 1500.0
NEWCOMER_Q = 0.15           # 新队初始 Elo：联赛在役球队评分的 15% 分位（升班马通常偏弱）
RESET_DAYS = 200            # 超过这么多天没在本联赛出场，按新队处理
PRIOR_GAMES = 3.0           # 球队统计向联赛均值收缩的等效场数
REST_CAP = 14               # 休息天数上限
LEAGUE_HL = 300             # 联赛场均的半衰期（场）
# 球队统计的半衰期（场）。gfh / gah 只记主场，gfa / gaa 只记客场
TEAM_STATS = {"gf5": 5, "ga5": 5, "gf20": 20, "ga20": 20, "gfh": 10, "gah": 10,
              "gfa": 10, "gaa": 10, "sf": 10, "sa": 10, "xf": 10, "xa": 10}
# 联赛先验（伪场数 LEAGUE_PRIOR_W）：主 / 客进球、射正、xG
LEAGUE_PRIOR = {"hg": 1.5, "ag": 1.2, "hs": 4.6, "as": 3.9, "hx": 1.5, "ax": 1.2}
LEAGUE_PRIOR_W = 50.0

SIDE_COLS = ["gf5", "ga5", "gf20", "ga20", "gfv", "gav", "sf", "sa", "xf", "xa",
             "elo", "games", "rest", "gap"]
XG_COLS = {"xf", "xa"}
LEAGUE_COLS = ["elo_diff", "lg_hg", "lg_ag"]
MARKET_COLS = ["mk_ph", "mk_pd", "mk_pa", "mk_over", "mk_has_ou", "mk_ah_line", "mk_ah_p",
               "mk_has_ah", "mk_log_lam_h", "mk_log_lam_a"]
ID_COLS = ["match_id", "league", "season", "match_date", "home_team", "away_team",
           "home_goals", "away_goals", "cutoff_date", "features_ver"]
ODDS_COLS = ["avg_h", "avg_d", "avg_a", "avg_over25", "avg_under25", "ah_line", "avg_ahh", "avg_aha"]


def feature_columns(feature_set: str, variant: str) -> list[str]:
    """网络的输入列。full 含 xG（只用于五联赛）；no_xg 不含；变体 B 另加市场列。"""
    if feature_set not in ("full", "no_xg") or variant not in ("A", "B"):
        raise ValueError((feature_set, variant))
    side = [c for c in SIDE_COLS if feature_set == "full" or c not in XG_COLS]
    cols = [f"h_{c}" for c in side] + [f"a_{c}" for c in side] + LEAGUE_COLS
    return cols + (MARKET_COLS if variant == "B" else [])


@dataclass
class _Team:
    elo: float
    games: int = 0
    last: date | None = None
    stats: dict = field(default_factory=dict)    # 键 -> (加权和, 权重)

    def push(self, key: str, x: float) -> None:
        d = 0.5 ** (1 / TEAM_STATS[key])
        s, w = self.stats.get(key, (0.0, 0.0))
        self.stats[key] = (d * s + x, d * w + 1)

    def est(self, key: str, mu: float) -> float:
        s, w = self.stats.get(key, (0.0, 0.0))
        return (s + PRIOR_GAMES * mu) / (w + PRIOR_GAMES)


class LeagueState:
    """一个联赛到某天为止的状态。只能按日期顺序喂比赛（scan）。"""

    def __init__(self):
        self.teams: dict[str, _Team] = {}
        self.lg = {k: (v * LEAGUE_PRIOR_W, LEAGUE_PRIOR_W) for k, v in LEAGUE_PRIOR.items()}

    def _lg(self, key: str) -> float:
        s, w = self.lg[key]
        return s / w

    def _lg_push(self, key: str, x: float) -> None:
        d = 0.5 ** (1 / LEAGUE_HL)
        s, w = self.lg[key]
        self.lg[key] = (d * s + x, d * w + 1)

    def _view(self, name: str, day: date) -> _Team:
        """该队在 day 开赛前的状态；新队或久未出场的队给一个新状态（不写回）。"""
        t = self.teams.get(name)
        if t is not None and t.last is not None and (day - t.last).days <= RESET_DAYS:
            return t
        active = [x.elo for x in self.teams.values()
                  if x.last is not None and (day - x.last).days <= RESET_DAYS]
        return _Team(elo=float(np.quantile(active, NEWCOMER_Q)) if active else ELO_BASE)

    def _side(self, t: _Team, venue: str, day: date) -> dict:
        hg, ag = self._lg("hg"), self._lg("ag")
        mu_g, mu_s, mu_x = (hg + ag) / 2, (self._lg("hs") + self._lg("as")) / 2, \
            (self._lg("hx") + self._lg("ax")) / 2
        gfv, gav = (t.est("gfh", hg), t.est("gah", ag)) if venue == "h" else \
            (t.est("gfa", ag), t.est("gaa", hg))
        days = (day - t.last).days if t.last is not None else RESET_DAYS
        return {"gf5": t.est("gf5", mu_g), "ga5": t.est("ga5", mu_g),
                "gf20": t.est("gf20", mu_g), "ga20": t.est("ga20", mu_g),
                "gfv": gfv, "gav": gav,
                "sf": t.est("sf", mu_s), "sa": t.est("sa", mu_s),
                "xf": t.est("xf", mu_x), "xa": t.est("xa", mu_x),
                "elo": (t.elo - ELO_BASE) / 100, "games": math.log1p(t.games) / math.log(40),
                "rest": min(days, REST_CAP) / REST_CAP, "gap": min(days, RESET_DAYS) / RESET_DAYS}

    def _features(self, th: _Team, ta: _Team, day: date) -> dict:
        out = {f"h_{k}": v for k, v in self._side(th, "h", day).items()}
        out |= {f"a_{k}": v for k, v in self._side(ta, "a", day).items()}
        out |= {"elo_diff": (th.elo + ELO_HOME - ta.elo) / 100,
                "lg_hg": self._lg("hg"), "lg_ag": self._lg("ag")}
        return out

    def features(self, home: str, away: str, day: date) -> dict:
        """day 开赛前（只用 day 之前的比赛）的特征；不改状态。"""
        return self._features(self._view(home, day), self._view(away, day), day)

    def _update(self, th: _Team, ta: _Team, r: dict, day: date) -> None:
        hg, ag = int(r["home_goals"]), int(r["away_goals"])
        e = 1 / (1 + 10 ** (-(th.elo + ELO_HOME - ta.elo) / 400))
        s = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        k = ELO_K * math.log1p(abs(hg - ag)) if hg != ag else ELO_K
        th.elo, ta.elo = th.elo + k * (s - e), ta.elo - k * (s - e)
        for t, gf, ga in ((th, hg, ag), (ta, ag, hg)):
            for key, x in (("gf5", gf), ("ga5", ga), ("gf20", gf), ("ga20", ga)):
                t.push(key, x)
            t.games, t.last = t.games + 1, day
        th.push("gfh", hg), th.push("gah", ag), ta.push("gfa", ag), ta.push("gaa", hg)
        self._lg_push("hg", hg), self._lg_push("ag", ag)
        for kh, ka, lh, la in (("home_sot", "away_sot", "hs", "as"),
                               ("home_xg", "away_xg", "hx", "ax")):
            xh, xa = r.get(kh), r.get(ka)
            if xh is None or xa is None or xh != xh or xa != xa:
                continue                           # 缺射正 / xG 的场次只是不更新这一项
            sk = "s" if lh == "hs" else "x"
            th.push(f"{sk}f", xh), th.push(f"{sk}a", xa)
            ta.push(f"{sk}f", xa), ta.push(f"{sk}a", xh)
            self._lg_push(lh, xh), self._lg_push(la, xa)

    def scan(self, rows: list[dict], collect: bool = True) -> list[dict]:
        """按日期喂比赛（rows 已按 match_date 排好）。collect 时返回每场赛前特征。"""
        out, i = [], 0
        while i < len(rows):
            j = i
            while j < len(rows) and rows[j]["match_date"] == rows[i]["match_date"]:
                j += 1
            day = date.fromisoformat(rows[i]["match_date"][:10])
            views = [(self._view(r["home_team"], day), self._view(r["away_team"], day))
                     for r in rows[i:j]]
            if collect:
                out += [self._features(th, ta, day) for th, ta in views]
            for r, (th, ta) in zip(rows[i:j], views):   # 当天全部出完特征后才更新
                self._update(th, ta, r, day)
                self.teams[r["home_team"]], self.teams[r["away_team"]] = th, ta
            i = j
        return out


def _load(conn: sqlite3.Connection, league: str, cutoff_date: str | None = None) -> pd.DataFrame:
    q = f"""SELECT m.match_id, m.league, m.season, m.match_date, m.home_team, m.away_team,
                   m.home_goals, m.away_goals, s.home_sot, s.away_sot, x.home_xg, x.away_xg,
                   {', '.join('o.' + c for c in ODDS_COLS)}
            FROM matches m
            LEFT JOIN match_stats s ON s.match_id = m.match_id
            LEFT JOIN match_xg x ON x.match_id = m.match_id
            LEFT JOIN match_odds o ON o.match_id = m.match_id
            WHERE m.league = ? AND m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL
              {'AND m.match_date < ?' if cutoff_date else ''}
            ORDER BY m.match_date, m.match_id"""
    params = (league, cutoff_date) if cutoff_date else (league,)
    return pd.read_sql_query(q, conn, params=params)


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if v is None or (isinstance(v, float) and v != v) else v)
             for k, v in r.items()} for r in df.to_dict("records")]


def market_features(odds: dict) -> dict:
    """该场赛前平均赔率 -> 市场列。odds 键同 model_market（h,d,a,over,under,ah_line,ah_h,ah_a）。
    缺胜平负时 mk_* 全为 NaN（变体 B 不用这类场次）。"""
    fp = fair_probs(odds)
    if "1x2" not in fp:
        return {c: float("nan") for c in MARKET_COLS} | {"mk_lam_h": float("nan"),
                                                         "mk_lam_a": float("nan")}
    lam = fit_lambdas(odds, DEFAULT_RHO)
    line, p_ah = fp.get("ah", (0.0, 0.5))
    return {"mk_ph": float(fp["1x2"][0]), "mk_pd": float(fp["1x2"][1]), "mk_pa": float(fp["1x2"][2]),
            "mk_over": fp.get("over25", 0.5), "mk_has_ou": float("over25" in fp),
            "mk_ah_line": line, "mk_ah_p": p_ah, "mk_has_ah": float("ah" in fp),
            "mk_log_lam_h": math.log(lam["lam_h"]), "mk_log_lam_a": math.log(lam["lam_a"]),
            "mk_lam_h": lam["lam_h"], "mk_lam_a": lam["lam_a"]}


def odds_of(r: dict) -> dict:
    """match_odds / fixtures 列名 -> model_market 的 odds 键（只取赛前平均）。"""
    m = {"h": "avg_h", "d": "avg_d", "a": "avg_a", "over": "avg_over25", "under": "avg_under25",
         "ah_line": "ah_line", "ah_h": "avg_ahh", "ah_a": "avg_aha"}
    return {k: r[c] for k, c in m.items() if r.get(c) is not None and r[c] == r[c]}


def build_table(conn: sqlite3.Connection, league: str, cache: bool = True) -> pd.DataFrame:
    """一个联赛全部已完赛比赛的样本表：每行是这一场按它自己日期为 cutoff 的赛前特征 + 赛果。"""
    raw = _load(conn, league)
    key = hashlib.md5(pd.util.hash_pandas_object(raw, index=False).values.tobytes()).hexdigest()[:12]
    path = CACHE_DIR / f"{league}_f{FEATURES_VER}_{key}.parquet"
    if cache and path.exists():
        return pd.read_parquet(path)
    rows = _records(raw)
    feats = pd.DataFrame(LeagueState().scan(rows), index=raw.index)
    mk = pd.DataFrame([market_features(odds_of(r)) for r in rows], index=raw.index)
    out = pd.concat([raw, feats, mk], axis=1)
    out["cutoff_date"], out["features_ver"] = out["match_date"].str[:10], FEATURES_VER
    if cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
    return out


def state_at(conn: sqlite3.Connection, league: str, cutoff_date: str) -> LeagueState:
    """只用 match_date < cutoff_date 的比赛建好的联赛状态（实盘预测用）。"""
    st = LeagueState()
    st.scan(_records(_load(conn, league, cutoff_date)), collect=False)
    return st
