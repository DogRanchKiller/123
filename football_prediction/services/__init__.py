"""中间层：一个用例一份编排。命令行入口（live / explain / main）和以后的 server/ 都从这里引用，
不从领域包里自己拼流程。本文件只做再导出。规则见 docs/modules.md。"""
from football_prediction.services.backtest_run import (
    BACKTEST_LEAGUES, calibrate_demo, load_backtest_data, run_demo_predictions, run_league_backtest,
)
from football_prediction.services.live_round import (
    DB_PATH, LEAGUES, MARKET_VER, SNAPSHOT_PATH, predict_upcoming, run_round,
)
from football_prediction.services.match_analysis import (
    ModelCache, analyse_match, build_report, explain_inputs, latest_odds,
)
from football_prediction.services.match_read import (
    FOTMOB_DB, RECENT_DAYS, open_readonly, read_current, read_match, read_recent, read_scorecard,
)
from football_prediction.services.near_round import T1_HOURS, predict_near, run_near

__all__ = [
    "DB_PATH", "LEAGUES", "MARKET_VER", "SNAPSHOT_PATH", "T1_HOURS",
    "ModelCache", "analyse_match", "build_report", "explain_inputs", "latest_odds",
    "predict_upcoming", "run_round", "open_readonly", "read_current", "read_match", "read_recent", "read_scorecard",
    "FOTMOB_DB", "RECENT_DAYS",
    "predict_near", "run_near",
    "BACKTEST_LEAGUES", "load_backtest_data", "run_league_backtest", "calibrate_demo",
    "run_demo_predictions",
]
