"""
review/store.py  v1.7.0
复盘层：保存预测记录、赛后评分、跨版本对比。
预测记录永不覆盖，旧版本预测保留，确保公平比较。
v1.1.0: has_prediction 去重（每场每模型版本只留开赛前首次预测）；live_report 实盘同场对比市场。
v1.2.0: live_report 加命中率与配对 SE；promotion_check 按 version.PROMOTE_MIN_N 规则检查主模型替换。
v1.3.0: 赛后另评大小2.5（extra 有 over_2.5）与精确比分（extra 有 score_matrix）的 log loss；
        成绩单增加这两列；首条记录改用 drop_duplicates 取整行（不再逐列取首个非空值）。
v1.4.0: 临场档（模型名以 _t1 结尾）不参加 promotion_check；新增 horizon_report，临场档与赛前档同场配对。
v1.5.0: matches 还没有赛果时用 fotmob_results 的比分先评分（predictions.result_src="fotmob"）；
        reconcile_results 在 football-data 赛果到达后核对，不一致按 football-data 重评；pending_fotmob 计数。
        成绩单 / 替换检查（_scored_first）不再 JOIN matches，FotMob 先评的场次也计入。
v1.6.0: 亚盘评分（只作参考，不进 promotion_check）：在存档时的市场亚盘线上，用 extra 里的
        ah_{线} 五种结算概率算 log loss（ah_log_loss），赢盘概率较高一方为选择方算命中（ah_hit，
        赢 / 赢半 = 1，输 / 输半 = 0，走盘为空）；评分用的线记入 ah_line。线取本行 extra.odds.ah_line，
        没有时取同场同档（赛前 / 临场 _t1）最早一条带亚盘线的存档，各模型同场同线、可配对。
        已评分的旧行由 score_predictions 补算；成绩单增加 ah_n / ah_ll / ah_hit 三列。
        文件超过 400 行，成绩单 / 替换检查 / 临场对照拆到 review/scorecard.py（同为 review 层）。
v1.7.0: save_prediction 收生成时刻 at，extra 的开球时间不晚于 at 时不存（一轮里抓数据、拟合耗时长，
        轮开头的 now 会过期）；成绩单 / 替换检查 / 临场对照不计 generated_at 不早于开球的旧行（不删不改）。
修改此文件后请同步更新 version.py 中 "review" 的版本号。
"""
import sqlite3
import json
from datetime import datetime, timezone
from math import log

import pandas as pd

LAYER_VERSION = "1.7.0"
HORIZON_SUFFIX = "_t1"                          # 临场档模型名后缀（live --near 存档）

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
    layer_ver      TEXT NOT NULL,
    result_src     TEXT,            -- 评分用的赛果："fd"（matches）/ "fotmob"（待 football-data 核对）；旧行为空 = fd
    ah_line        REAL,            -- 亚盘评分用的市场线（主队方向，负=主让）
    ah_log_loss    REAL,            -- 该线五种结算的 log loss（extra 有 ah_{线} 时）
    ah_hit         REAL             -- 赢盘概率较高一方：赢 / 赢半 1，输 / 输半 0，走盘为空
);
"""


SCORE_N = 9   # score_matrix 为 9×9（0~8 球）按行展平，行=主队进球
AH_KEYS = ("win", "half_win", "push", "half_lose", "lose")   # extra 里 ah_{线} 的顺序（output.derive）


def _init_review_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
    for col, typ in (("ou25_log_loss", "REAL"), ("score_log_loss", "REAL"),
                     ("result_src", "TEXT"), ("ah_line", "REAL"), ("ah_log_loss", "REAL"),
                     ("ah_hit", "REAL")):               # 旧库迁移，幂等
        if col not in have:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} {typ}")
    conn.commit()


def _has_fotmob_results(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM fotmob_results LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


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


def ah_settle(margin: int, line: float) -> str:
    """主队净胜 margin、让球线 line（主队方向）的结算：四分之一盘拆两半注（与 output.derive 一致）。"""
    q = round(line * 4)
    halves = ((q - 1) / 4, (q + 1) / 4) if q % 2 else (q / 4, q / 4)
    s = sum((margin + h > 0) - (margin + h < 0) for h in halves)
    return {2: "win", 1: "half_win", 0: "push", -1: "half_lose", -2: "lose"}[s]


def ah_scores(extra: dict, hg: int, ag: int, line) -> tuple[float | None, float | None]:
    """该线上的五种结算 log loss 与选择方命中；extra 没有该线概率时 (None, None)，走盘命中为 None。"""
    if line is None or line != line:
        return None, None
    p = extra.get(f"ah_{float(line) + 0.0:+.2f}")
    if not p or len(p) != len(AH_KEYS):
        return None, None
    o = dict(zip(AH_KEYS, p))
    k = ah_settle(hg - ag, float(line))
    ll = -log(max(o[k], 1e-7))
    if k == "push":
        return ll, None
    home = o["win"] + o["half_win"] / 2 >= o["lose"] + o["half_lose"] / 2   # 赢盘概率 ≥ 50% 选主队
    return ll, float((k in ("win", "half_win")) == home)


def _ah_ref_lines(conn: sqlite3.Connection) -> dict[tuple[str, bool], float]:
    """{(match_id, 是否临场档): 亚盘线}：同场同档最早一条在 extra.odds 里带亚盘线的存档。"""
    out = {}
    for mid, name, ex in conn.execute(
            "SELECT match_id, model_name, extra_markets FROM predictions "
            "WHERE extra_markets LIKE '%\"ah_line\"%' ORDER BY generated_at"):
        line = _own_ah_line(json.loads(ex))
        key = (mid, name.endswith(HORIZON_SUFFIX))
        if line is not None and key not in out:
            out[key] = line
    return out


def _own_ah_line(extra: dict):
    od = extra.get("odds")
    return od.get("ah_line") if isinstance(od, dict) else None


def _ah_line_for(row, extra: dict, ref: dict):
    line = _own_ah_line(extra)
    if line is None:
        line = ref.get((row["match_id"], row["model_name"].endswith(HORIZON_SUFFIX)))
    return line


def _make_pred_id(match_id: str, model_name: str,
                  model_ver: str, generated_at: str) -> str:
    import hashlib
    key = f"{match_id}|{model_name}|{model_ver}|{generated_at}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def started(extra: dict | None, at: datetime) -> bool:
    """extra 里记了开球时间且 at 已到开球：这时的预测不能算赛前预测。"""
    ko = (extra or {}).get("kickoff_utc")
    return bool(ko) and datetime.fromisoformat(ko) <= at


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
    at: datetime | None = None,
) -> str | None:
    """
    保存一条预测记录，返回 pred_id。
    同一场比赛可保存多个模型版本的预测，互不覆盖。
    at 是生成时刻（默认当前 UTC）；extra_markets 里的 kickoff_utc 不晚于它（已开球）时不存，返回 None。
    """
    _init_review_db(conn)
    at = at or datetime.now(timezone.utc)
    if started(extra_markets, at):
        return None
    generated_at = at.astimezone(timezone.utc).isoformat()
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


def _extra(row) -> dict:
    ex = row["extra_markets"]                  # 缺失时 pandas 读成 NaN/None
    return json.loads(ex) if isinstance(ex, str) and ex else {}


def _r6(x):
    return None if x is None else round(x, 6)


def _ah_values(row, extra: dict, hg: int, ag: int, ref: dict) -> tuple:
    """(ah_line, ah_log_loss, ah_hit)；该线没有概率时三项都为 None。"""
    line = _ah_line_for(row, extra, ref)
    ll, hit = ah_scores(extra, hg, ag, line)
    return (None, None, None) if ll is None else (float(line), round(ll, 6), hit)


def _score_row(conn: sqlite3.Connection, row, hg: int, ag: int, src: str, scored_at: str,
               ref: dict) -> None:
    outcome = "home_win" if hg > ag else ("draw" if hg == ag else "away_win")
    p = {"home_win": row["p_home_win"],
         "draw":     row["p_draw"],
         "away_win": row["p_away_win"]}
    ll = -log(max(p[outcome], 1e-7))
    br = sum((p[k] - (1.0 if k == outcome else 0.0)) ** 2
             for k in ("home_win", "draw", "away_win"))
    extra = _extra(row)
    ou, sc = market_log_losses(extra, hg, ag)
    conn.execute(
        """UPDATE predictions
           SET actual_outcome=?, log_loss=?, brier=?, ou25_log_loss=?, score_log_loss=?,
               scored_at=?, result_src=?, ah_line=?, ah_log_loss=?, ah_hit=?
           WHERE pred_id=?""",
        (outcome, round(ll, 6), round(br, 6), _r6(ou), _r6(sc), scored_at, src,
         *_ah_values(row, extra, hg, ag, ref), row["pred_id"]),
    )


def _backfill_ah(conn: sqlite3.Connection, ref: dict) -> None:
    """已评分、extra 有亚盘概率但还没有亚盘评分的行（1.6.0 之前评的）：只补亚盘三列。
    赛果按 result_src 取（fotmob 先评的用 FotMob 比分，其余用 matches）。"""
    fm = _has_fotmob_results(conn)
    rows = pd.read_sql_query(
        f"""SELECT p.pred_id, p.match_id, p.model_name, p.extra_markets, p.result_src,
                   m.home_goals AS fd_h, m.away_goals AS fd_a,
                   {"r.home_goals" if fm else "NULL"} AS fm_h, {"r.away_goals" if fm else "NULL"} AS fm_a
            FROM predictions p
            LEFT JOIN matches m ON p.match_id = m.match_id
            {"LEFT JOIN fotmob_results r ON p.match_id = r.match_id" if fm else ""}
            WHERE p.actual_outcome IS NOT NULL AND p.ah_log_loss IS NULL
              AND p.extra_markets LIKE '%"ah_+0.00"%'""",
        conn,
    )
    for _, row in rows.iterrows():
        h, a = ("fm_h", "fm_a") if row["result_src"] == "fotmob" else ("fd_h", "fd_a")
        if pd.isna(row[h]) or pd.isna(row[a]):
            continue
        vals = _ah_values(row, _extra(row), int(row[h]), int(row[a]), ref)
        if vals[1] is not None:
            conn.execute("UPDATE predictions SET ah_line=?, ah_log_loss=?, ah_hit=? WHERE pred_id=?",
                         (*vals, row["pred_id"]))


def score_predictions(conn: sqlite3.Connection) -> int:
    """
    关联实际结果，自动填写 log_loss / brier。赛果优先用 matches（football-data）；
    matches 还没有、但挂了 fotmob.db 且 fotmob_results 有比分时先用 FotMob（result_src="fotmob"），
    之后由 reconcile_results 用 football-data 核对。
    只处理尚未评分的记录，幂等可多次调用。返回本次评分的条数。
    """
    _init_review_db(conn)
    fm = _has_fotmob_results(conn)
    unscored = pd.read_sql_query(
        f"""SELECT p.pred_id, p.match_id, p.model_name, p.p_home_win, p.p_draw, p.p_away_win,
                   p.extra_markets,
                   m.home_goals AS fd_h, m.away_goals AS fd_a,
                   {"r.home_goals" if fm else "NULL"} AS fm_h, {"r.away_goals" if fm else "NULL"} AS fm_a
            FROM predictions p
            LEFT JOIN matches m ON p.match_id = m.match_id
            {"LEFT JOIN fotmob_results r ON p.match_id = r.match_id" if fm else ""}
            WHERE p.actual_outcome IS NULL""",
        conn,
    )

    count = 0
    ref = _ah_ref_lines(conn)
    scored_at = datetime.now(timezone.utc).isoformat()
    for _, row in unscored.iterrows():
        if pd.notna(row["fd_h"]) and pd.notna(row["fd_a"]):
            hg, ag, src = int(row["fd_h"]), int(row["fd_a"]), "fd"
        elif pd.notna(row["fm_h"]) and pd.notna(row["fm_a"]):
            hg, ag, src = int(row["fm_h"]), int(row["fm_a"]), "fotmob"
        else:
            continue
        _score_row(conn, row, hg, ag, src, scored_at, ref)
        count += 1
    _backfill_ah(conn, ref)

    conn.commit()
    return count


def reconcile_results(conn: sqlite3.Connection) -> tuple[int, list[dict]]:
    """用 FotMob 比分评过、现在 matches 已有 football-data 赛果的预测：比分一致只改标记为 fd，
    不一致按 football-data 重评。返回（核对的预测条数, 不一致的场次 [{match_id, fotmob, fd}]）。
    这是评分用的赛果更正，不改预测本身。"""
    _init_review_db(conn)
    fm = _has_fotmob_results(conn)
    rows = pd.read_sql_query(
        f"""SELECT p.pred_id, p.match_id, p.model_name, p.p_home_win, p.p_draw, p.p_away_win,
                   p.extra_markets,
                   m.home_goals AS fd_h, m.away_goals AS fd_a,
                   {"r.home_goals" if fm else "NULL"} AS fm_h, {"r.away_goals" if fm else "NULL"} AS fm_a
            FROM predictions p
            JOIN matches m ON p.match_id = m.match_id
            {"LEFT JOIN fotmob_results r ON p.match_id = r.match_id" if fm else ""}
            WHERE p.result_src = 'fotmob' AND m.home_goals IS NOT NULL""",
        conn,
    )
    bad, seen = [], set()
    ref = _ah_ref_lines(conn) if len(rows) else {}
    scored_at = datetime.now(timezone.utc).isoformat()
    for _, row in rows.iterrows():
        fd = (int(row["fd_h"]), int(row["fd_a"]))
        fmv = (int(row["fm_h"]), int(row["fm_a"])) if pd.notna(row["fm_h"]) else None
        if fmv == fd:
            conn.execute("UPDATE predictions SET result_src='fd' WHERE pred_id=?", (row["pred_id"],))
            continue
        _score_row(conn, row, *fd, "fd", scored_at, ref)   # 没挂 fotmob.db 时无从比较，直接按 fd 重评
        if fmv is not None and row["match_id"] not in seen:
            seen.add(row["match_id"])
            bad.append({"match_id": row["match_id"], "fotmob": fmv, "fd": fd})
    conn.commit()
    return len(rows), bad


def pending_fotmob(conn: sqlite3.Connection) -> int:
    """用 FotMob 比分评分、还在等 football-data 核对的场数。"""
    _init_review_db(conn)
    return conn.execute(
        "SELECT COUNT(DISTINCT match_id) FROM predictions WHERE result_src='fotmob'").fetchone()[0]
