"""中间层：一个用例一份编排。命令行入口（live / explain / main）、server/ 和 agent/ 都从这里引用，
不从领域包里自己拼流程。本文件只做再导出。规则见 docs/modules.md。"""
from football_prediction.services.backtest_run import (
    BACKTEST_LEAGUES, calibrate_demo, load_backtest_data, run_demo_predictions, run_league_backtest,
)
from football_prediction.services.live_round import (
    DB_PATH, LEAGUES, MARKET_VER, SNAPSHOT_PATH, match_view, predict_upcoming, run_round,
)
from football_prediction.services.match_analysis import (
    ModelCache, analyse_match, build_report, explain_detail, explain_inputs, latest_odds,
)
from football_prediction.services.match_read import (
    FOTMOB_DB, RECENT_DAYS, open_readonly, read_current, read_match, read_recent, read_scorecard,
    read_snapshot,
)
from football_prediction.services.monitor import health_check, health_lines
from football_prediction.services.near_round import T1_HOURS, T24_HI, T24_LO, predict_near, predict_t24, run_near
from football_prediction.services.team_read import (
    GRADED_MODELS, league_code, read_archived_ids, read_grading, read_lineups, read_next_fixture,
    read_scores, read_team_recent, resolve_team_name,
)

__all__ = [
    "DB_PATH", "LEAGUES", "MARKET_VER", "SNAPSHOT_PATH", "T1_HOURS",
    "ModelCache", "analyse_match", "build_report", "explain_detail", "explain_inputs", "latest_odds",
    "match_view", "predict_upcoming", "run_round",
    "open_readonly", "read_current", "read_match", "read_recent", "read_scorecard", "read_snapshot",
    "FOTMOB_DB", "RECENT_DAYS",
    "predict_near", "predict_t24", "run_near", "T24_HI", "T24_LO", "health_check", "health_lines",
    "GRADED_MODELS", "league_code", "read_grading", "read_lineups", "read_next_fixture",
    "read_team_recent", "resolve_team_name", "read_archived_ids", "read_scores",
    "BACKTEST_LEAGUES", "load_backtest_data", "run_league_backtest", "calibrate_demo",
    "run_demo_predictions",
]
