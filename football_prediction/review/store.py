"""
review/store.py  v1.4.0
复盘层：保存预测记录、赛后评分、跨版本对比。
预测记录永不覆盖，旧版本预测保留，确保公平比较。
v1.1.0: has_prediction 去重（每场每模型版本只留开赛前首次预测）；live_report 实盘同场对比市场。
v1.2.0: live_report 加命中率与配对 SE；promotion_check 按 version.PROMOTE_MIN_N 规则检查主模型替换。
v1.3.0: 赛后另评大小2.5（extra 有 over_2.5）与精确比分（extra 有 score_matrix）的 log loss；
        成绩单增加这两列；首条记录改用 drop_duplicates 取整行（不再逐列取首个非空值）。
v1.4.0: 临场档（模型名以 _t1 结尾）不参加 promotion_check；新增 horizon_report，临场档与赛前档同场配对。
修改此文件后请同步更新 version.py 中 "review" 的版本号。
"""
import sqlite3
import json
from datetime import datetime, timezone
from math import log

import numpy as np
import pandas as pd

LAYER_VERSION = "1.4.0"
HORIZON_SUFFIX = "_t1"                          # 临场档模型名后缀（live --near 存档）
HORIZON_BASE = {"lineup_t1": "lineup_base_t1"}  # 临场档的默认对照是去掉后缀的赛前档，例外在此登记

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
    ou25_log_loss  REAL,            -- 大小2.5 log loss（有 over_2.5 时）
    score_log_loss REAL,            -- 精确比分 log loss（有 score_matrix 时）
    scored_at      TEXT,
    layer_ver      TEXT NOT NULL
);
"""


SCORE_N = 9   # score_matrix 为 9×9（0~8 球）按行展平，行=主队进球


def _init_review_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
    for col in ("ou25_log_loss", "score_log_loss"):   # 旧库迁移，幂等
        if col not in have:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} REAL")
    conn.commit()


def market_log_losses(extra: dict, hg: int, ag: int) -> tuple[float | None, float | None]:
    """大小2.5 与精确比分 log loss；extra 缺对应字段时为 None。"""
    ou = sc = None
    if extra.get("over_2.5") is not None:
        p = extra["over_2.5"] if hg + ag > 2.5 else 1 - extra["over_2.5"]
        ou = -log(min(max(p, 1e-7), 1.0))
    m = extra.get("score_matrix")
    if m and len(m) == SCORE_N * SCORE_N:
        p = m[hg * SCORE_N + ag] if hg < SCORE_N and ag < SCORE_N else 0.0
        sc = -log(max(p, 1e-7))
    return ou, sc


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
        """SELECT p.pred_id, p.p_home_win, p.p_draw, p.p_away_win, p.extra_markets,
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
        ex = row["extra_markets"]                  # 缺失时 pandas 读成 NaN/None
        extra = json.loads(ex) if isinstance(ex, str) and ex else {}
        ou, sc = market_log_losses(extra, hg, ag)

        conn.execute(
            """UPDATE predictions
               SET actual_outcome=?, log_loss=?, brier=?, ou25_log_loss=?, score_log_loss=?,
                   scored_at=?
               WHERE pred_id=?""",
            (outcome, round(ll, 6), round(br, 6),
             None if ou is None else round(ou, 6), None if sc is None else round(sc, 6),
             scored_at, row["pred_id"]),
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


def _scored_first(conn: sqlite3.Connection) -> pd.DataFrame:
    """已评分预测，同场同模型版本只取最早一条（与 has_prediction 规则一致），附命中标记。"""
    _init_review_db(conn)
    df = pd.read_sql_query(
        """SELECT p.match_id, p.model_name, p.model_ver, p.log_loss, p.brier,
                  p.ou25_log_loss, p.score_log_loss,
                  p.p_home_win, p.p_draw, p.p_away_win, p.actual_outcome
           FROM predictions p JOIN matches m ON p.match_id = m.match_id
           WHERE p.actual_outcome IS NOT NULL
           ORDER BY p.generated_at""",
        conn,
    )
    if df.empty:
        return df
    df = df.drop_duplicates(["match_id", "model_name", "model_ver"]).reset_index(drop=True)
    pick = np.array(["home_win", "draw", "away_win"])[
        df[["p_home_win", "p_draw", "p_away_win"]].to_numpy().argmax(axis=1)]
    df["hit"] = (pick == df["actual_outcome"]).astype(float)
    return df


def _paired(a: pd.DataFrame, b: pd.DataFrame) -> tuple[int, float, float]:
    """同场配对 log loss 差（a − b）：返回 (场数, 差值, SE)。"""
    m = a[["match_id", "log_loss"]].merge(
        b[["match_id", "log_loss"]], on="match_id", suffixes=("_a", "_b"))
    if m.empty:
        return 0, float("nan"), float("nan")
    d = m["log_loss_a"] - m["log_loss_b"]
    se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else float("nan")
    return len(d), float(d.mean()), float(se)


def live_report(conn: sqlite3.Connection,
                baseline: str = "market_avg") -> pd.DataFrame:
    """
    实盘成绩单：每个 模型/版本 的已评分场数、Log Loss、Brier、命中率，
    以及在【同一批比赛】上与市场基准的配对差值和 SE（负=模型优于市场）。
    """
    df = _scored_first(conn)
    if df.empty:
        return df
    base = df[df["model_name"] == baseline].drop_duplicates("match_id")

    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        n, diff, se = _paired(g, base)
        rows.append({
            "model_name":   name,
            "model_ver":    ver,
            "matches":      len(g),
            "log_loss":     g["log_loss"].mean(),
            "brier":        g["brier"].mean(),
            "hit_rate":     g["hit"].mean(),
            "ou25_ll":      g["ou25_log_loss"].mean(),    # 无数据时为 NaN
            "score_ll":     g["score_log_loss"].mean(),
            "paired_n":     n,
            "diff_vs_base": diff,
            "se":           se,
        })
    return pd.DataFrame(rows).sort_values("log_loss")


def promotion_check(conn: sqlite3.Connection, primary: tuple[str, str],
                    min_n: int) -> pd.DataFrame:
    """
    主模型替换检查：每个挑战者（除主模型与市场基准外）与主模型同场配对。
    规则：场数 ≥ min_n 且 (差值 + 2×SE) < 0 时 verdict="可替换"。
    primary 为 (model_name, model_ver)。
    """
    df = _scored_first(conn)
    if df.empty:
        return df
    prim = df[(df["model_name"] == primary[0]) & (df["model_ver"] == primary[1])]
    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        if (name, ver) == tuple(primary) or name == "market_avg" or name.endswith(HORIZON_SUFFIX):
            continue   # 临场档只覆盖部分场次、信息时点不同，不与赛前主模型争替换（见 horizon_report）
        n, diff, se = _paired(g, prim)
        if n < min_n:
            verdict = f"样本不足（{n}/{min_n}）"
        elif diff + 2 * se < 0:
            verdict = "可替换"
        else:
            verdict = "不替换"
        rows.append({"model_name": name, "model_ver": ver, "paired_n": n,
                     "diff": diff, "se": se, "verdict": verdict})
    return pd.DataFrame(rows)


def horizon_report(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    临场档对赛前档：每个 X_t1（各版本）与赛前档 X 在同一批已评分比赛上配对（差值负=临场更好）。
    赛前档有多个版本时每场取最早一条；没有配对场次的不列出。
    """
    df = _scored_first(conn)
    if df.empty:
        return df
    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        if not name.endswith(HORIZON_SUFFIX):
            continue
        base_name = HORIZON_BASE.get(name, name[: -len(HORIZON_SUFFIX)])
        base = df[df["model_name"] == base_name].drop_duplicates("match_id")
        n, diff, se = _paired(g, base)
        if n:
            rows.append({"model_name": name, "model_ver": ver, "base": base_name,
                         "paired_n": n, "diff": diff, "se": se})
    return pd.DataFrame(rows)
