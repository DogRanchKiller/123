"""
features/builder.py  v1.0.0
特征层：从数据库读取历史比赛，生成赛前可用特征。
⚠️ 所有特征必须只用 cutoff_date 之前的数据。
修改此文件后请同步更新 version.py 中 "features" 的版本号。
"""
import sqlite3
import pandas as pd
from datetime import date

LAYER_VERSION = "1.0.0"

# 计算近期状态时使用的窗口场数
FORM_WINDOW = 6


def _fetch_matches(conn: sqlite3.Connection,
                   league: str,
                   cutoff_date: str) -> pd.DataFrame:
    """取 cutoff_date 之前的所有已完成比赛"""
    return pd.read_sql_query(
        """SELECT match_date, home_team, away_team, home_goals, away_goals
           FROM matches
           WHERE league = ? AND match_date < ?
           ORDER BY match_date""",
        conn,
        params=(league, cutoff_date),
    )


def _team_stats(df: pd.DataFrame, team: str,
                cutoff_date: str, window: int = FORM_WINDOW) -> dict:
    """计算某队在 cutoff_date 前的主客场胜率和近期进失球均值"""
    home = df[df["home_team"] == team].copy()
    away = df[df["away_team"] == team].copy()

    # 主场胜率
    home_win_rate = (home["home_goals"] > home["away_goals"]).mean() if len(home) else 0.0
    # 客场胜率
    away_win_rate = (away["away_goals"] > away["home_goals"]).mean() if len(away) else 0.0

    # 近 window 场进失球（主客合并，按日期取最新）
    all_games = pd.concat([
        home.assign(gf=home["home_goals"], ga=home["away_goals"]),
        away.assign(gf=away["away_goals"], ga=away["home_goals"]),
    ]).sort_values("match_date").tail(window)

    recent_gf = all_games["gf"].mean() if len(all_games) else 1.2
    recent_ga = all_games["ga"].mean() if len(all_games) else 1.0

    return {
        "home_win_rate": round(home_win_rate, 4),
        "away_win_rate": round(away_win_rate, 4),
        "recent_gf":     round(recent_gf, 4),
        "recent_ga":     round(recent_ga, 4),
        "home_matches":  len(home),
        "away_matches":  len(away),
    }


def build_features(
    conn: sqlite3.Connection,
    league: str,
    cutoff_date: str,
    home_team: str,
    away_team: str,
) -> dict:
    """
    为单场比赛生成赛前特征。
    cutoff_date: 预测生成时点（ISO 8601 日期字符串），严格不含当天。
    返回特征 dict，包含 layer_ver 和 cutoff_date 供追溯。
    """
    df = _fetch_matches(conn, league, cutoff_date)

    home_stats = _team_stats(df, home_team, cutoff_date)
    away_stats = _team_stats(df, away_team, cutoff_date)

    # H2H 历史对阵
    h2h = df[
        ((df["home_team"] == home_team) & (df["away_team"] == away_team)) |
        ((df["home_team"] == away_team) & (df["away_team"] == home_team))
    ].tail(10)
    h2h_home_win = (
        ((h2h["home_team"] == home_team) & (h2h["home_goals"] > h2h["away_goals"])) |
        ((h2h["away_team"] == home_team) & (h2h["away_goals"] > h2h["home_goals"]))
    ).mean() if len(h2h) else 0.45

    features = {
        "home_win_rate":      home_stats["home_win_rate"],
        "home_recent_gf":     home_stats["recent_gf"],
        "home_recent_ga":     home_stats["recent_ga"],
        "home_matches":       home_stats["home_matches"],
        "away_win_rate":      away_stats["away_win_rate"],
        "away_recent_gf":     away_stats["recent_gf"],
        "away_recent_ga":     away_stats["recent_ga"],
        "away_matches":       away_stats["away_matches"],
        "h2h_home_win_rate":  round(h2h_home_win, 4),
        "h2h_count":          len(h2h),
        # 追溯字段
        "layer_ver":          LAYER_VERSION,
        "cutoff_date":        cutoff_date,
    }
    return features
