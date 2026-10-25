"""
model_lineup/ratings.py  v1.1.0
阵容模型的球员评分、常规首发与阵容特征（数据：FotMob 的 lineups / player_match，见 data/fotmob.py）。
  进攻评分：球员 (npxG + xA) / 90 的时间衰减均值，向位置组均值收缩（相当于 SHRINK_90S 个 90 分钟）。
  常规首发：球队最近 N_RECENT 场联赛首发次数（越近权重越高）最多的 11 人。
  一支球队一场的阵容特征：
    d_att   = log(本场首发进攻评分之和 / 常规首发进攻评分之和)
    rot     = 1 − 本场首发里常规首发的人数 / 11
    rot_def = 1 − 本场首发里常规首发门将+后卫的人数 / 常规首发门将+后卫人数
  只用 cutoff 之前完赛的比赛；每场取最后一批阵容。
修改此文件后请同步更新 version.py 中 "model_lineup" 的版本号。
"""
import sqlite3
from math import log

import numpy as np
import pandas as pd

LAYER_VERSION = "1.1.0"
XI = 0.005           # 时间衰减，与 DC 相同（约 139 天半衰期）
SHRINK_90S = 5.0     # 收缩强度：相当于 5 个 90 分钟的位置组均值
N_RECENT = 5         # 常规首发看最近 5 场
RECENT_DECAY = 0.8   # 每往前一场权重 ×0.8
DEFENSIVE = ("GK", "DEF")


def pos_group(position_id) -> str:
    """FotMob 阵型坐标（十位 = 从门将起的行）-> GK / DEF / MID / FWD；没有坐标为 UNK。"""
    if position_id is None or pd.isna(position_id):
        return "UNK"
    p = int(position_id)
    if p == 11:
        return "GK"
    row = p // 10
    return "DEF" if row <= 4 else "MID" if row <= 8 else "FWD"


def load_history(conn: sqlite3.Connection, league: str, cutoff: str) -> pd.DataFrame:
    """cutoff 之前完赛场次的首发 / 替补（每场最后一批阵容）+ 出场分钟与 npxG / xA。"""
    df = pd.read_sql_query(
        """SELECT m.match_id, m.match_date, l.fetched_at,
                  CASE l.side WHEN 'home' THEN m.home_team ELSE m.away_team END AS team,
                  l.player_id, l.role, l.position_id, p.minutes, p.npxg, p.xa
           FROM lineups l JOIN matches m ON m.match_id = l.match_id
           LEFT JOIN player_match p ON p.match_id = l.match_id AND p.player_id = l.player_id
           WHERE m.league = ? AND m.match_date < ? AND l.role IN ('starter', 'sub')""",
        conn, params=(league, cutoff))
    if df.empty:
        return df
    last = df.groupby("match_id")["fetched_at"].transform("max")
    return df[df["fetched_at"] == last].drop(columns="fetched_at").reset_index(drop=True)


def current_lineup(conn: sqlite3.Connection, match_id: str) -> tuple[str, dict] | None:
    """该场最新一批阵容：(lineup_type, {"home": [(player_id, position_id)], "away": [...]})。"""
    last = conn.execute("SELECT MAX(fetched_at) FROM lineups WHERE match_id = ?",
                        (match_id,)).fetchone()[0]
    if last is None:
        return None
    rows = conn.execute(
        "SELECT lineup_type, side, player_id, position_id FROM lineups "
        "WHERE match_id = ? AND fetched_at = ? AND role = 'starter'", (match_id, last)).fetchall()
    if not rows:
        return None
    out = {"home": [], "away": []}
    for _, side, pid, pos in rows:
        out[side].append((pid, pos))
    return rows[0][0], out


def first_standard_at(conn: sqlite3.Connection, match_id: str) -> str | None:
    """该场第一次抓到正式首发（lineup_type='standard'）的时间；没有则 None。"""
    return conn.execute("SELECT MIN(fetched_at) FROM lineups WHERE match_id = ? "
                        "AND lineup_type = 'standard'", (match_id,)).fetchone()[0]


class LineupModel:
    """某联赛在 cutoff 时点的球员评分与历史首发；team_features 给出一支球队本场的阵容特征。"""
    MODEL_VER = LAYER_VERSION

    def fit(self, conn: sqlite3.Connection, league: str, cutoff: str) -> None:
        self.fit_history(load_history(conn, league, cutoff), cutoff)

    def fit_history(self, hist: pd.DataFrame, cutoff: str) -> None:
        """hist 为 load_history 的结果（须全部早于 cutoff）；回测时可一次读入后按日期切片。"""
        self.hist = hist
        self.rate, self.pos, self.prior, self.prior_all = {}, {}, {}, 0.0
        if hist.empty:
            return
        played = hist[hist["minutes"].fillna(0) > 0]
        days = (pd.Timestamp(cutoff) - pd.to_datetime(played["match_date"])).dt.days.to_numpy()
        w = np.exp(-XI * days)
        g = pd.DataFrame({"player_id": played["player_id"].to_numpy(),
                          "n90": w * played["minutes"].to_numpy() / 90,
                          "att": w * (played["npxg"].fillna(0) + played["xa"].fillna(0)).to_numpy()}
                         ).groupby("player_id").sum()
        st = hist[hist["role"] == "starter"]
        pos = st.assign(pg=st["position_id"].map(pos_group)).groupby("player_id")["pg"].agg(
            lambda s: s.mode().iat[0])
        self.pos = pos.to_dict()
        g["pos"] = [self.pos.get(p, "UNK") for p in g.index]
        self.prior_all = float(g["att"].sum() / max(g["n90"].sum(), 1e-9))
        self.prior = {k: float(d["att"].sum() / d["n90"].sum()) if d["n90"].sum() > 0 else self.prior_all
                      for k, d in g.groupby("pos")}
        prior = g["pos"].map(self.prior).fillna(self.prior_all)
        self.rate = ((g["att"] + SHRINK_90S * prior) / (g["n90"] + SHRINK_90S)).to_dict()

    def player_rate(self, pid, position_id=None) -> float:
        if pid in self.rate:
            return self.rate[pid]
        return self.prior.get(pos_group(position_id), self.prior_all)

    def usual_xi(self, team: str) -> list:
        """最近 N_RECENT 场按加权首发次数排前 11 的球员（同分取最近一场首发的）。"""
        st = self.hist[(self.hist["team"] == team) & (self.hist["role"] == "starter")]
        mids = (st.drop_duplicates("match_id").sort_values("match_date")["match_id"]
                .tolist()[-N_RECENT:])
        if len(mids) < N_RECENT:
            return []
        order = {m: i for i, m in enumerate(mids)}
        score: dict = {}
        r = st[st["match_id"].isin(order)]
        for m, p in zip(r["match_id"], r["player_id"]):
            s, last = score.get(p, (0.0, -1))
            score[p] = (s + RECENT_DECAY ** (len(mids) - 1 - order[m]), max(last, order[m]))
        return [p for p, _ in sorted(score.items(), key=lambda kv: kv[1], reverse=True)[:11]]

    def team_features(self, team: str, starters: list) -> dict | None:
        """starters 为 [(player_id, position_id)] 共 11 人；历史不足 N_RECENT 场返回 None。"""
        usual = self.usual_xi(team)
        if len(usual) < 11 or len(starters) != 11:
            return None
        ids = {p for p, _ in starters}
        att_s = sum(self.player_rate(p, pos) for p, pos in starters)
        att_u = sum(self.player_rate(p) for p in usual)
        udef = [p for p in usual if self.pos.get(p) in DEFENSIVE]
        return {"d_att": log(max(att_s, 1e-6) / max(att_u, 1e-6)),
                "rot": 1 - len(ids & set(usual)) / 11,
                "rot_def": 1 - len(ids & set(udef)) / len(udef) if udef else 0.0}
