"""
services/backtest_run.py  回测演示（中间层）
原 main.py（v1.3.0）里的串联，行为不变：三联赛下载赛季 → 各联赛回测对比与同场配对 → Platt 校准（英超示例）
→ 各联赛一场示例预测。命令行入口 main.py 只做打印。
2526 是全新留出赛季：shrink 在 2324 选参、2425 确认，2526 从未参与任何调参。
"""
import functools
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd

from football_prediction.calibration.platt import PlattCalibrator
from football_prediction.data.loader import load_season
from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.model_dc.sot_dc import SotDixonColesModel
from football_prediction.model_elo.elo import EloModel
from football_prediction.validation.backtest import (
    paired_compare, run_backtest, run_lgbm_backtest, run_market_backtest,
)

Log = Callable[[str], None]

SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
TRAIN = ["2122", "2223", "2324", "2425"]
TEST = ["2526"]

# 联赛配置：每个联赛独立跑完整对比
BACKTEST_LEAGUES = {code: {"name": name, "seasons": SEASONS, "train": TRAIN, "test": TEST}
                    for code, name in (("E0", "英超"), ("D1", "德甲"), ("SP1", "西甲"))}

# 示例预测场次（各联赛各选一场）
DEMO_MATCHES = {
    "E0":  ("Arsenal",       "Chelsea"),
    "D1":  ("Bayern Munich", "Dortmund"),
    "SP1": ("Real Madrid",   "Barcelona"),
}


def load_backtest_data(conn: sqlite3.Connection, db_path: str, log: Log = print) -> None:
    """下载所有联赛所有赛季；网络失败时本地已有该赛季则沿用，否则抛出。"""
    for code, cfg in BACKTEST_LEAGUES.items():
        for s in cfg["seasons"]:
            log(f"    [{cfg['name']}] 赛季 {s} ...")
            try:
                n = load_season(code, s, conn, db_path)
                log(f"    写入 {n} 场（已有则跳过）")
            except Exception as e:
                have = conn.execute("SELECT COUNT(*) FROM matches WHERE league=? AND season=?",
                                    (code, s)).fetchone()[0]
                if not have:
                    raise
                log(f"    下载失败（{type(e).__name__}），使用本地已有 {have} 场")


def run_league_backtest(conn: sqlite3.Connection, code: str, log: Log = print) -> tuple[list, list]:
    """单个联赛的完整回测：(汇总行, 同场配对行)。"""
    from football_prediction.model_lgbm.lgbm_model import LGBMCorrectionModel   # lightgbm 可选，用到才导入
    cfg = BACKTEST_LEAGUES[code]
    name, train, test = cfg["name"], cfg["train"], cfg["test"]
    log(f"\n{'=' * 60}\n联赛: {name} ({code})\n{'=' * 60}")

    DCv0 = functools.partial(DixonColesModel, xi=0.0)
    DCv0.__name__ = "DixonColesModel_xi0"
    DCv12 = functools.partial(DixonColesModel, shrink=0.0)   # v1.2.0 对照：无收缩
    DCv12.__name__ = "DixonColesModel_v120"

    elo_r = run_backtest(conn, code, train, test, EloModel)
    dc_v0_r = run_backtest(conn, code, train, test, DCv0)
    dc_r = run_backtest(conn, code, train, test, DixonColesModel)
    dc_mo12 = run_backtest(conn, code, train, test, DCv12, refit_freq="monthly")
    dc_mo_r = run_backtest(conn, code, train, test, DixonColesModel, refit_freq="monthly")
    sot_mo_r = run_backtest(conn, code, train, test, SotDixonColesModel, refit_freq="monthly")
    lgbm_r = run_lgbm_backtest(conn, code, train, test, DixonColesModel, LGBMCorrectionModel)
    mkt_pre = run_market_backtest(conn, code, test, closing=False)
    mkt_cls = run_market_backtest(conn, code, test, closing=True)

    label_lg = f"{name}({code})"
    rows = [{"联赛": label_lg, "模型": label, "场数": len(df),
             "Log Loss": round(df["log_loss"].mean(), 4), "Brier": round(df["brier"].mean(), 4)}
            for label, df in (("Elo 基线", elo_r), ("DC xi=0 单次 (对照)", dc_v0_r),
                              ("DC 单次 (v1.3.0)", dc_r), ("DC 月度 无收缩 (v1.2.0)", dc_mo12),
                              ("DC 月度 shrink=0.5 (v1.3.0)", dc_mo_r),
                              ("射正版 DC 月度 w=0.7 (v1.0.0)", sot_mo_r),
                              ("LightGBM 修正 (v1.1.0)", lgbm_r),
                              ("市场 赛前平均赔率", mkt_pre), ("市场 收盘平均赔率", mkt_cls))
            if len(df)]
    # 同场配对：主模型 DC 月度 v1.3.0 对各参照的 Log Loss 差（负=DC 更好）；射正版 DC 月度对 DC 月度与市场赛前
    pairs = [{"联赛": label_lg, "主模型": "DC 月度", "对照": label, **paired_compare(dc_mo_r, ref)}
             for label, ref in (("DC xi=0 单次", dc_v0_r), ("市场 赛前", mkt_pre), ("市场 收盘", mkt_cls))]
    pairs += [{"联赛": label_lg, "主模型": "射正DC 月度", "对照": label, **paired_compare(sot_mo_r, ref)}
              for label, ref in (("DC 月度", dc_mo_r), ("市场 赛前", mkt_pre))]
    return rows, pairs


def calibrate_demo(conn: sqlite3.Connection) -> PlattCalibrator:
    """Platt 校准（英超 E0，校准赛季 2324）。2425 月度 OOS 上三联赛 Log Loss 变化均在 ±0.005 内，
    无显著增益，仅作展示，正式预测仍用 DC 原始概率。"""
    cal = PlattCalibrator()
    cal.fit(conn, "E0", DixonColesModel, calib_seasons=["2324"], helper_seasons=["2122", "2223"])
    return cal


def _demo_cutoff(conn: sqlite3.Connection, league: str) -> str:
    """该联赛最新比赛日期 +1 天，避免时间衰减权重归零。"""
    last = pd.read_sql_query("SELECT MAX(match_date) AS dt FROM matches WHERE league=?",
                             conn, params=[league]).iloc[0]["dt"]
    return (date.fromisoformat(last) + timedelta(days=1)).isoformat()


def run_demo_predictions(conn: sqlite3.Connection, cal: PlattCalibrator) -> list[dict]:
    """各联赛一场示例预测：DC 原始、DC 校准后（仅英超且校准成功时）、LightGBM 修正。"""
    from football_prediction.model_lgbm.lgbm_model import LGBMCorrectionModel
    out = []
    for code, (home, away) in DEMO_MATCHES.items():
        cfg = BACKTEST_LEAGUES[code]
        cutoff = _demo_cutoff(conn, code)
        dc = DixonColesModel()
        dc.fit(conn, code, cutoff_date=cutoff)
        raw = dc.predict_1x2(home, away)
        calibrated = cal.calibrate_dict(raw) if cal.fitted and code == "E0" else None
        lgbm = LGBMCorrectionModel()
        lgbm.fit(conn, code, dc, cfg["train"])
        out.append({"league": code, "name": cfg["name"], "home": home, "away": away, "cutoff": cutoff,
                    "raw": raw, "calibrated": calibrated,
                    "lgbm": lgbm.predict_match(conn, code, dc, home, away, cutoff)})
    return out
