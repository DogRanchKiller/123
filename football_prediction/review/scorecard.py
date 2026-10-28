"""
review/scorecard.py  （review 层的一部分，版本跟 review/store.py 的 LAYER_VERSION）
实盘成绩单与对照：版本对比 compare_versions、成绩单 live_report（同场对比同一档的 market_avg）、
对收盘参照 closing_report、主模型替换检查 promotion_check、临场档对赛前档 horizon_report。
只读 predictions 表里已评分的行（closing_report 另读 match_odds 的收盘赔率）。
v1.6.0: 从 store.py 拆出（行为不变）；成绩单增加亚盘列 ah_n / ah_ll / ah_hit（只作参考，不进替换检查）。
v1.7.0: _scored_first 剔除 generated_at 不早于 extra.kickoff_utc 的行（开球后才存，不算赛前预测）。
v1.8.0: 临场档 _t2 也不进 promotion_check；horizon_report 里 _t2 分别对赛前档与 _t1 配对。
v1.9.0: live_report 每行对同一档的市场基准（赛前档 market_avg，_t1 对 market_avg_t1，_t2 对 market_avg_t2），
        新增 base 列；此前临场档也对赛前 market_avg，信息时点不同，差值偏向临场档。
        新增 closing_report：已评分场次上各模型对 football-data 收盘平均赔率（按比例去水）的同场差，
        收盘在存档时还看不到，只作参照，不进替换检查。T24 档 _t24 同样对 market_avg_t24、不进替换检查；
        horizon_report 里 _t24 对赛前档，_t1 / _t2 另对 _t24 配对。
修改此文件后请同步更新 version.py 中 "review" 的版本号。
"""
import sqlite3

import numpy as np
import pandas as pd

from football_prediction.review.store import HORIZON_SUFFIXES, _init_review_db, horizon_of

CLOSING_NAME = "closing_avg"   # closing_report 里收盘参照自身的行名（不存档）
HORIZON_BASE = {"lineup_t1": "lineup_base_t1"}  # 临场档的默认对照是去掉后缀的赛前档，例外在此登记


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
                  p.ou25_log_loss, p.score_log_loss, p.ah_log_loss, p.ah_hit,
                  p.p_home_win, p.p_draw, p.p_away_win, p.actual_outcome,
                  p.generated_at, json_extract(p.extra_markets, '$.kickoff_utc') AS kickoff_utc
           FROM predictions p
           WHERE p.actual_outcome IS NOT NULL
           ORDER BY p.generated_at""",
        conn,
    )
    if df.empty:
        return df
    # 开球后才存的行（v1.7.0 之前一轮耗时过长时会出现）不算赛前预测；不删库里的行，只在这里不计
    gen = pd.to_datetime(df["generated_at"], utc=True, format="ISO8601")
    ko = pd.to_datetime(df["kickoff_utc"], utc=True, format="ISO8601")
    df = df[~(ko.notna() & (gen >= ko))]
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
    以及在【同一批比赛】上与同一档市场基准 base（baseline + 本行的档后缀）的配对差值和 SE（负=模型优于市场）。
    亚盘列：ah_n 有亚盘评分的场数，ah_ll 市场线五种结算 log loss，ah_hit 选择方命中（不含走盘）。
    """
    df = _scored_first(conn)
    if df.empty:
        return df

    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        base_name = baseline + horizon_of(name)
        n, diff, se = _paired(g, df[df["model_name"] == base_name].drop_duplicates("match_id"))
        rows.append({
            "model_name":   name,
            "model_ver":    ver,
            "matches":      len(g),
            "log_loss":     g["log_loss"].mean(),
            "brier":        g["brier"].mean(),
            "hit_rate":     g["hit"].mean(),
            "ou25_ll":      g["ou25_log_loss"].mean(),    # 无数据时为 NaN
            "score_ll":     g["score_log_loss"].mean(),
            "ah_n":         int(g["ah_log_loss"].notna().sum()),   # 亚盘：只作参考，不进替换检查
            "ah_ll":        g["ah_log_loss"].mean(),
            "ah_hit":       g["ah_hit"].mean(),                    # 走盘不计
            "base":         base_name,
            "paired_n":     n,
            "diff_vs_base": diff,
            "se":           se,
        })
    return pd.DataFrame(rows).sort_values("log_loss")


def _closing_probs(conn: sqlite3.Connection, match_ids) -> pd.DataFrame:
    """[match_id, p_home_win, p_draw, p_away_win]：football-data 收盘平均 1X2（avgc_*）按比例去水
    （与 market_avg 同一种去水）；缺任一赔率或赔率 ≤ 1 的场次不列。"""
    empty = pd.DataFrame(columns=["match_id", "p_home_win", "p_draw", "p_away_win"])
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'match_odds'").fetchone()
    ids = list(dict.fromkeys(match_ids))
    if not has or not ids:
        return empty
    q = ",".join("?" * len(ids))
    odds = pd.read_sql_query(
        f"SELECT match_id, avgc_h, avgc_d, avgc_a FROM match_odds WHERE match_id IN ({q})", conn, params=ids)
    o = odds[["avgc_h", "avgc_d", "avgc_a"]].to_numpy(dtype=float)
    ok = np.isfinite(o).all(axis=1) & (o > 1).all(axis=1)
    odds, o = odds[ok].reset_index(drop=True), o[ok]
    if odds.empty:
        return empty
    p = (1 / o) / (1 / o).sum(axis=1, keepdims=True)
    return odds[["match_id"]].assign(p_home_win=p[:, 0], p_draw=p[:, 1], p_away_win=p[:, 2])


def closing_report(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    对收盘参照：每个 模型/版本 与收盘平均赔率（去水）在同一批已评分比赛上配对的胜平负 log loss 差和 SE
    （负 = 比收盘好）。首行 closing_avg 是收盘自身（差值 0）。收盘在存档时还看不到，只作参照，不进替换检查。
    """
    df = _scored_first(conn)
    if df.empty:
        return df
    close = _closing_probs(conn, df["match_id"])
    if close.empty:
        return pd.DataFrame()
    close = close.merge(df[["match_id", "actual_outcome"]].drop_duplicates("match_id"), on="match_id")
    cols = {"home_win": "p_home_win", "draw": "p_draw", "away_win": "p_away_win"}
    p = close.apply(lambda r: r[cols[r["actual_outcome"]]], axis=1).to_numpy(dtype=float)
    close["log_loss"] = -np.log(np.maximum(p, 1e-7))
    rows = [{"model_name": CLOSING_NAME, "model_ver": "", "paired_n": len(close),
             "log_loss": float(close["log_loss"].mean()), "diff_vs_close": 0.0, "se": 0.0}]
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        n, diff, se = _paired(g, close)
        if n:
            rows.append({"model_name": name, "model_ver": ver, "paired_n": n,
                         "log_loss": float(g[g["match_id"].isin(close["match_id"])]["log_loss"].mean()),
                         "diff_vs_close": diff, "se": se})
    return pd.DataFrame(rows).sort_values("diff_vs_close", kind="stable").reset_index(drop=True)


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
        if (name, ver) == tuple(primary) or name == "market_avg" or horizon_of(name):
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
    临场档对更早的档：每个临场档 X_h（各版本）与赛前档 X、以及 HORIZON_SUFFIXES 里排在 h 之前的各档各配对一次
    （_t24 对赛前；_t1 对赛前、_t24；_t2 对赛前、_t24、_t1）。
    同一批已评分比赛上同场配对（差值负=临场更好）。对照档有多个版本时每场取最早一条；没有配对场次的不列出。
    """
    df = _scored_first(conn)
    if df.empty:
        return df
    rows = []
    for (name, ver), g in df.groupby(["model_name", "model_ver"]):
        h = horizon_of(name)
        if not h:
            continue
        stem = name[: -len(h)]
        bases = [HORIZON_BASE.get(name, stem)] + [stem + s for s in HORIZON_SUFFIXES[:HORIZON_SUFFIXES.index(h)]]
        for base_name in bases:
            base = df[df["model_name"] == base_name].drop_duplicates("match_id")
            n, diff, se = _paired(g, base)
            if n:
                rows.append({"model_name": name, "model_ver": ver, "base": base_name,
                             "paired_n": n, "diff": diff, "se": se})
    return pd.DataFrame(rows)
