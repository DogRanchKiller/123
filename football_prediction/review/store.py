"""
review/store.py  v1.1.0
复盘层：保存预测记录、赛后评分、跨版本对比。
预测记录永不覆盖，旧版本预测保留，确保公平比较。
v1.1.0: has_prediction 去重（每场每模型版本只留开赛前首次预测）；live_report 实盘同场对比市场。
修改此文件后请同步更新 version.py 中 "review" 的版本号。
"""
import sqlite3
import json
from datetime import datetime, timezone
from math import log

import pandas as pd

LAYER_VERSION = "1.1.0"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    pred_id        TEXT PRIMARY KEY,
    match_id       TEXT NOT NULL,
    generated_at   TEXT NOT NULL,   -- ISO 8601 UTC，预测生成时间
    model_name     TEXT NOT NULL,   -- "elo" | "dixon_coles"
    model_ver      TEXT NOT NULL,
    feature_ver    TEXT NOT NULL,
    p_home_win     REAL NOT NULL,
    p_draw         REAL NOT NULL,
    p_away_win     REAL NOT NULL,
    extra_markets  TEXT,            -- JSON，大小球/让球等
    -- 赛后填入
    actual_outcome TEXT,            -- "home_win" | "draw" | "away_win"
    log_loss       REAL,
    brier          REAL,
    scored_at      TEXT,
    layer_ver      TEXT NOT NULL
);
"""


def _init_review_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _make_pred_id(match_id: str, model_name: str,
                  model_ver: str, generated_at: str) -> str:
    import hashlib
    key = f"{match_id}|{model_name}|{model_ver}|{generated_at}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def has_prediction(conn: sqlite3.Connection, match_id: str,
                   model_name: str, model_ver: str) -> bool:
    """该场比赛是否已有此模型版本的预测（实盘只保留首次预测，避免挑选结果）。"""
    _init_review_db(conn)
    return conn.execute(
        """SELECT 1 FROM predictions
           WHERE match_id=? AND model_name=? AND model_ver=? LIMIT 1""",
        (match_id, model_name, model_ver),
    ).fetchone() is not None


def save_prediction(
    conn: sqlite3.Connection,
    match_id: str,
    model_name: str,
    model_ver: str,
    feature_ver: str,
    p_home_win: float,
    p_draw: float,
    p_away_win: float,
    extra_markets: dict | None = None,
) -> str:
    """
    保存一条预测记录，返回 pred_id。
    同一场比赛可保存多个模型版本的预测，互不覆盖。
    """
    _init_review_db(conn)
    generated_at = datetime.now(timezone.utc).isoformat()
    pred_id = _make_pred_id(match_id, model_name, model_ver, generated_at)

    conn.execute(
        """INSERT OR IGNORE INTO predictions
           (pred_id, match_id, generated_at, model_name, model_ver,
            feature_ver, p_home_win, p_draw, p_away_win,
            extra_markets, layer_ver)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pred_id, match_id, generated_at, model_name, model_ver,
            feature_ver, p_home_win, p_draw, p_away_win,
            json.dumps(extra_markets) if extra_markets else None,
            LAYER_VERSION,
        ),
    )
    conn.commit()
    return pred_id


def score_predictions(conn: sqlite3.Connection) -> int:
    """
    关联 matches 表中已有实际结果，自动填写 log_loss / brier。
    只处理尚未评分的记录，幂等可多次调用。
    返回本次评分的条数。
    """
    _init_review_db(conn)
    unscored = pd.read_sql_query(
        """SELECT p.pred_id, p.p_home_win, p.p_draw, p.p_away_win,
                  m.home_goals, m.away_goals
           FROM predictions p
           JOIN matches m ON p.match_id = m.match_id
           WHERE p.actual_outcome IS NULL
             AND m.home_goals IS NOT NULL""",
        conn,
    )

    count = 0
    scored_at = datetime.now(timezone.utc).isoformat()
    for _, row in unscored.iterrows():
        hg, ag = int(row["home_goals"]), int(row["away_goals"])
        if hg > ag:
            outcome = "home_win"
        elif hg == ag:
            outcome = "draw"
        else:
            outcome = "away_win"

        p = {"home_win": row["p_home_win"],
             "draw":     row["p_draw"],
             "away_win": row["p_away_win"]}
        ll = -log(max(p[outcome], 1e-7))
        br = sum((p[k] - (1.0 if k == outcome else 0.0)) ** 2
                 for k in ("home_win", "draw", "away_win"))

        conn.execute(
            """UPDATE predictions
               SET actual_outcome=?, log_loss=?, brier=?, scored_at=?
               WHERE pred_id=?""",
            (outcome, round(ll, 6), round(br, 6), scored_at, row["pred_id"]),
        )
        count += 1

    conn.commit()
    return count


def compare_versions(conn: sqlite3.Connection,
                     model_name: str) -> pd.DataFrame:
    """
    按 model_ver 汇总已评分预测的平均 Log Loss 和 Brier Score。
    用于判断新版本是否优于旧版本。
    """
    _init_review_db(conn)
    return pd.read_sql_query(
        """SELECT model_ver, feature_ver,
                  COUNT(*)            AS matches,
                  AVG(log_loss)       AS avg_log_loss,
                  AVG(brier)          AS avg_brier
           FROM predictions
           WHERE model_name = ? AND actual_outcome IS NOT NULL
           GROUP BY model_ver, feature_ver
           ORDER BY avg_log_loss""",
        conn,
        params=(model_name,),
    )


def live_report(conn: sqlite3.Connection,
                baseline: str = "market_avg") -> pd.DataFrame:
    """
    实盘成绩单：每个 模型/版本 的已评分场数、Log Loss、Brier，
    以及在【同一批比赛】上市场基准的 Log Loss 和差值（负=模型优于市场）。
    """
    _init_review_db(conn)
    df = pd.read_sql_query(
        """SELECT p.match_id, p.model_name, p.model_ver, p.log_loss, p.brier
           FROM predictions p JOIN matches m ON p.match_id = m.match_id
           WHERE p.actual_outcome IS NOT NULL
           ORDER BY p.generated_at""",
        conn,
    )
    if df.empty:
        return df
    # 同场同模型版本若有多条，只取最早一条（与 has_prediction 规则一致）
    df = df.groupby(["match_id", "model_name", "model_ver"], as_index=False).first()
    base = df[df["model_name"] == baseline][["match_id", "log_loss"]] \
        .drop_duplicates("match_id").rename(columns={"log_loss": "base_ll"})

    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        m = g.merge(base, on="match_id", how="left")
        both = m.dropna(subset=["base_ll"])
        rows.append({
            "model_name":  name,
            "model_ver":   ver,
            "matches":     len(g),
            "log_loss":    g["log_loss"].mean(),
            "brier":       g["brier"].mean(),
            "paired_n":    len(both),
            "base_ll":     both["base_ll"].mean() if len(both) else float("nan"),
            "diff_vs_base": (both["log_loss"] - both["base_ll"]).mean()
                            if len(both) else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("log_loss")
