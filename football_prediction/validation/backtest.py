"""
validation/backtest.py  v1.0.0
验证层：按时间切分回测，计算 Log Loss、Brier Score 和概率校准。
⚠️ 每个预测时点只用该时点之前的数据训练，严格禁止随机 KFold。
修改此文件后请同步更新 version.py 中 "validation" 的版本号。
"""
import sqlite3
import numpy as np
import pandas as pd
from math import log

LAYER_VERSION = "1.0.0"


def _log_loss_one(probs: dict, outcome: str) -> float:
    """单场 Log Loss，outcome 为 'home_win' / 'draw' / 'away_win'"""
    p = max(probs[outcome], 1e-7)
    return -log(p)


def _brier_one(probs: dict, outcome: str) -> float:
    """单场 Brier Score（三分类）"""
    mapping = {"home_win": 0, "draw": 1, "away_win": 2}
    actuals = [0.0, 0.0, 0.0]
    actuals[mapping[outcome]] = 1.0
    preds = [probs["home_win"], probs["draw"], probs["away_win"]]
    return sum((p - a) ** 2 for p, a in zip(preds, actuals))


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home_win"
    if home_goals == away_goals:
        return "draw"
    return "away_win"


def run_backtest(
    conn: sqlite3.Connection,
    league: str,
    train_seasons: list[str],   # 训练赛季，如 ["2122", "2223"]
    test_seasons: list[str],    # 测试赛季，如 ["2324"]
    model_cls,                  # DixonColesModel 或 EloModel 类（未实例化）
    min_train_matches: int = 100,
    rolling: bool = False,      # True=每场重新拟合(慢)，False=训练集拟合一次(快)
    refit_freq: str = None,     # "monthly"=按月重新拟合，兼顾速度与时效
) -> pd.DataFrame:
    """
    时间外回测：
    - rolling=False（默认）：训练集拟合一次，对所有测试场预测。
    - rolling=True：每场用该场日期 cutoff 重新拟合，更新最及时但慢。
    - refit_freq="monthly": 测试集按月分桶，每月初重新拟合一次，兼顾速度与时效。
      时间衰减(xi>0)应配合 refit_freq="monthly" 或 rolling=True 才能生效。
    返回每场预测结果 DataFrame，含 log_loss 和 brier。
    """
    season_filter = ",".join("?" * len(test_seasons))
    test_df = pd.read_sql_query(
        f"""SELECT match_id, match_date, home_team, away_team,
                   home_goals, away_goals
            FROM matches
            WHERE league = ? AND season IN ({season_filter})
              AND home_goals IS NOT NULL
            ORDER BY match_date""",
        conn,
        params=[league] + test_seasons,
    )

    train_count = pd.read_sql_query(
        f"""SELECT COUNT(*) AS cnt FROM matches
            WHERE league = ? AND season IN ({','.join('?'*len(train_seasons))})
              AND home_goals IS NOT NULL""",
        conn,
        params=[league] + train_seasons,
    ).iloc[0]["cnt"]

    if train_count < min_train_matches:
        raise ValueError(
            f"训练集仅 {train_count} 场，低于最小要求 {min_train_matches}，"
            "请增加训练赛季。"
        )

    # rolling=False：训练集末尾日期作为 cutoff，只拟合一次
    if not rolling and refit_freq != "monthly":
        train_cutoff = pd.read_sql_query(
            f"""SELECT MAX(match_date) AS dt FROM matches
                WHERE league = ? AND season IN ({','.join('?'*len(train_seasons))})""",
            conn, params=[league] + train_seasons,
        ).iloc[0]["dt"]
        from datetime import date, timedelta
        cutoff_fixed = (
            date.fromisoformat(train_cutoff) + timedelta(days=1)
        ).isoformat()
        print(f"单次拟合 cutoff: {cutoff_fixed}，训练场数: {train_count}")
        fixed_model = model_cls()
        fixed_model.fit(conn, league, cutoff_fixed)
    else:
        from datetime import date, timedelta
        fixed_model = None   # monthly/rolling 模式下按需拟合

    records = []
    current_month_model = None
    current_month_key   = None   # "YYYY-MM"

    for _, row in test_df.iterrows():
        if rolling:
            model = model_cls()
            model.fit(conn, league, row["match_date"])
        elif refit_freq == "monthly":
            month_key = row["match_date"][:7]   # "YYYY-MM"
            if month_key != current_month_key:
                current_month_key = month_key
                cutoff = row["match_date"]
                print(f"  月度重拟合 cutoff={cutoff}", flush=True)
                current_month_model = model_cls()
                current_month_model.fit(conn, league, cutoff)
            model = current_month_model
        else:
            model = fixed_model

        home, away = row["home_team"], row["away_team"]
        try:
            if hasattr(model, "predict_1x2"):
                probs = model.predict_1x2(home, away)
            else:
                probs = model.predict(home, away)
        except KeyError:
            # 测试集出现训练集未见过的球队，跳过
            continue

        actual = _outcome(int(row["home_goals"]), int(row["away_goals"]))
        p = {"home_win": probs["home_win"],
             "draw":     probs["draw"],
             "away_win": probs["away_win"]}
        records.append({
            "match_id":   row["match_id"],
            "match_date": row["match_date"],
            "home_team":  home,
            "away_team":  away,
            "actual":     actual,
            "p_home_win": p["home_win"],
            "p_draw":     p["draw"],
            "p_away_win": p["away_win"],
            "log_loss":   round(_log_loss_one(p, actual), 6),
            "brier":      round(_brier_one(p, actual), 6),
            "layer_ver":  LAYER_VERSION,
        })

    result_df = pd.DataFrame(records)
    if len(result_df):
        print(f"\n=== 回测结果 [{league}] 测试赛季: {test_seasons} ===")
        print(f"场数:            {len(result_df)}")
        print(f"平均 Log Loss:   {result_df['log_loss'].mean():.4f}")
        print(f"平均 Brier:      {result_df['brier'].mean():.4f}")
        pred_outcome = result_df[["p_home_win","p_draw","p_away_win"]]\
            .idxmax(axis=1).str.replace("p_", "")
        acc = (result_df["actual"] == pred_outcome).mean()
        print(f"最大概率准确率:  {acc:.4f}  ← 单独看此指标容易误判")
    return result_df


def run_lgbm_backtest(
    conn: sqlite3.Connection,
    league: str,
    train_seasons: list[str],
    test_seasons: list[str],
    dc_model_cls,
    lgbm_model_cls,
    min_train_matches: int = 100,
) -> pd.DataFrame:
    """
    LightGBM 修正层回测：
    1. 用 train_seasons 全量数据拟合 DC（单次，内样本）
    2. 用相同 train_seasons 拟合 LightGBM（DC 概率 + 统计特征 → 标签）
    3. 对 test_seasons 每场用 DC + LightGBM 联合预测
    严格时间外验证：LightGBM 从未见过 test_seasons 中的任何数据。
    """
    train_count = pd.read_sql_query(
        f"""SELECT COUNT(*) AS cnt FROM matches
            WHERE league = ? AND season IN ({','.join('?'*len(train_seasons))})
              AND home_goals IS NOT NULL""",
        conn, params=[league] + train_seasons,
    ).iloc[0]["cnt"]

    if train_count < min_train_matches:
        raise ValueError(
            f"训练集仅 {train_count} 场，低于最小要求 {min_train_matches}"
        )

    # Step 1: DC 训练集拟合（cutoff = 训练集最后一天 +1）
    train_cutoff = pd.read_sql_query(
        f"""SELECT MAX(match_date) AS dt FROM matches
            WHERE league = ? AND season IN ({','.join('?'*len(train_seasons))})""",
        conn, params=[league] + train_seasons,
    ).iloc[0]["dt"]
    from datetime import date, timedelta
    cutoff_str = (date.fromisoformat(train_cutoff) + timedelta(days=1)).isoformat()
    print(f"  LightGBM — DC 拟合 cutoff: {cutoff_str}，训练场数: {train_count}")

    dc = dc_model_cls()
    dc.fit(conn, league, cutoff_str)

    # Step 2: LightGBM 在训练赛季上拟合
    lgbm = lgbm_model_cls()
    lgbm.fit(conn, league, dc, train_seasons)

    # Step 3: 测试赛季预测
    season_filter = ",".join("?" * len(test_seasons))
    test_df = pd.read_sql_query(
        f"""SELECT match_id, match_date, home_team, away_team,
                   home_goals, away_goals
            FROM matches
            WHERE league = ? AND season IN ({season_filter})
              AND home_goals IS NOT NULL
            ORDER BY match_date""",
        conn, params=[league] + test_seasons,
    )

    records = []
    for _, row in test_df.iterrows():
        home, away = row["home_team"], row["away_team"]
        try:
            probs = lgbm.predict_match(
                conn, league, dc, home, away, row["match_date"]
            )
        except Exception:
            continue

        actual = _outcome(int(row["home_goals"]), int(row["away_goals"]))
        p = {k: probs[k] for k in ("home_win", "draw", "away_win")}
        records.append({
            "match_id":   row["match_id"],
            "match_date": row["match_date"],
            "home_team":  home,
            "away_team":  away,
            "actual":     actual,
            "p_home_win": p["home_win"],
            "p_draw":     p["draw"],
            "p_away_win": p["away_win"],
            "log_loss":   round(_log_loss_one(p, actual), 6),
            "brier":      round(_brier_one(p, actual), 6),
            "layer_ver":  LAYER_VERSION,
        })

    result_df = pd.DataFrame(records)
    if len(result_df):
        print(f"\n=== 回测结果 [{league}] 测试赛季: {test_seasons} ===")
        print(f"场数:            {len(result_df)}")
        print(f"平均 Log Loss:   {result_df['log_loss'].mean():.4f}")
        print(f"平均 Brier:      {result_df['brier'].mean():.4f}")
        pred_outcome = result_df[["p_home_win","p_draw","p_away_win"]]\
            .idxmax(axis=1).str.replace("p_", "")
        acc = (result_df["actual"] == pred_outcome).mean()
        print(f"最大概率准确率:  {acc:.4f}  ← 单独看此指标容易误判")
    return result_df
