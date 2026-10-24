"""
football_prediction/main.py  v1.3.0
主入口：串联各层，演示完整流程。
v1.1.0: 多联赛跨联赛验证（E0/D1/SP1）；Platt scaling 概率校准；LightGBM v1.1.0 滚动OOS。
v1.2.0: 测试赛季改为全新留出的 2526；加入市场赔率基准与同场配对比较；实盘预测移至 live.py。
v1.3.0: 加入射正版 DC 月度（model_sot，w 在 2324+2425 选参）及其与 DC 月度、市场的配对比较。
用法：python -m football_prediction.main
"""
import sqlite3
import pandas as pd
from datetime import date, timedelta

from football_prediction import version
from football_prediction.data.loader           import init_db, load_season
from football_prediction.model_dc.dixon_coles  import DixonColesModel
from football_prediction.model_dc.sot_dc       import SotDixonColesModel
from football_prediction.model_elo.elo         import EloModel
from football_prediction.model_lgbm.lgbm_model import LGBMCorrectionModel
from football_prediction.calibration.platt     import PlattCalibrator
from football_prediction.output.derive         import derive_markets
from football_prediction.validation.backtest   import (
    run_backtest, run_lgbm_backtest, run_market_backtest, paired_compare,
)

DB_PATH = "football.db"

# 2526 是全新留出赛季：shrink 在 2324 选参、2425 确认，2526 从未参与任何调参
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
TRAIN   = ["2122", "2223", "2324", "2425"]
TEST    = ["2526"]

# 联赛配置：每个联赛独立跑完整对比
LEAGUES = {
    "E0": {
        "name":    "英超",
        "seasons": SEASONS,
        "train":   TRAIN,
        "test":    TEST,
    },
    "D1": {
        "name":    "德甲",
        "seasons": SEASONS,
        "train":   TRAIN,
        "test":    TEST,
    },
    "SP1": {
        "name":    "西甲",
        "seasons": SEASONS,
        "train":   TRAIN,
        "test":    TEST,
    },
}

# 示例预测场次（各联赛各选一场）
DEMO_MATCHES = {
    "E0":  ("Arsenal",       "Chelsea"),
    "D1":  ("Bayern Munich", "Dortmund"),
    "SP1": ("Real Madrid",   "Barcelona"),
}


def _get_demo_cutoff(conn, league):
    """返回该联赛最新比赛日期 +1 天，避免时间衰减权重归零。"""
    last_date = pd.read_sql_query(
        "SELECT MAX(match_date) AS dt FROM matches WHERE league=?",
        conn, params=[league],
    ).iloc[0]["dt"]
    return (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()


def _run_league(conn, league_code, cfg):
    """对单个联赛跑完整回测流程，返回汇总行列表。"""
    import functools
    name  = cfg["name"]
    train = cfg["train"]
    test  = cfg["test"]

    print(f"\n{'='*60}")
    print(f"联赛: {name} ({league_code})")
    print(f"{'='*60}")

    DCv0 = functools.partial(DixonColesModel, xi=0.0)
    DCv0.__name__ = "DixonColesModel_xi0"

    DCv12 = functools.partial(DixonColesModel, shrink=0.0)   # v1.2.0 对照：无收缩
    DCv12.__name__ = "DixonColesModel_v120"

    elo_r    = run_backtest(conn, league_code, train, test, EloModel)
    dc_v0_r  = run_backtest(conn, league_code, train, test, DCv0)
    dc_r     = run_backtest(conn, league_code, train, test, DixonColesModel)
    dc_mo12  = run_backtest(conn, league_code, train, test, DCv12,
                            refit_freq="monthly")
    dc_mo_r  = run_backtest(conn, league_code, train, test, DixonColesModel,
                            refit_freq="monthly")
    sot_mo_r = run_backtest(conn, league_code, train, test, SotDixonColesModel,
                            refit_freq="monthly")
    lgbm_r   = run_lgbm_backtest(
        conn, league_code, train, test, DixonColesModel, LGBMCorrectionModel,
    )
    mkt_pre  = run_market_backtest(conn, league_code, test, closing=False)
    mkt_cls  = run_market_backtest(conn, league_code, test, closing=True)

    rows = []
    for label, df in [
        ("Elo 基线",                         elo_r),
        ("DC xi=0 单次 (对照)",              dc_v0_r),
        ("DC 单次 (v1.3.0)",                 dc_r),
        ("DC 月度 无收缩 (v1.2.0)",          dc_mo12),
        ("DC 月度 shrink=0.5 (v1.3.0)",      dc_mo_r),
        ("射正版 DC 月度 w=0.7 (v1.0.0)",    sot_mo_r),
        ("LightGBM 修正 (v1.1.0)",           lgbm_r),
        ("市场 赛前平均赔率",                mkt_pre),
        ("市场 收盘平均赔率",                mkt_cls),
    ]:
        if len(df):
            rows.append({
                "联赛": f"{name}({league_code})",
                "模型": label,
                "场数": len(df),
                "Log Loss": round(df["log_loss"].mean(), 4),
                "Brier":    round(df["brier"].mean(),    4),
            })

    # 同场配对：主模型 DC 月度 v1.3.0 对各参照的 Log Loss 差（负=DC 更好）
    pairs = []
    for label, ref in [("DC xi=0 单次", dc_v0_r), ("市场 赛前", mkt_pre),
                       ("市场 收盘", mkt_cls)]:
        pairs.append({"联赛": f"{name}({league_code})", "主模型": "DC 月度", "对照": label,
                      **paired_compare(dc_mo_r, ref)})
    # 射正版 DC 月度对 DC 月度与市场赛前
    for label, ref in [("DC 月度", dc_mo_r), ("市场 赛前", mkt_pre)]:
        pairs.append({"联赛": f"{name}({league_code})", "主模型": "射正DC 月度", "对照": label,
                      **paired_compare(sot_mo_r, ref)})
    return rows, pairs


def main():
    print(f"系统版本: {version.SYSTEM_VERSION}")
    print(f"各层版本: {version.LAYER_VERSIONS}\n")

    # 1. 数据层：下载所有联赛所有赛季
    print(">>> [1] 初始化数据库并下载数据 ...")
    conn = init_db(DB_PATH)
    for league_code, cfg in LEAGUES.items():
        for s in cfg["seasons"]:
            print(f"    [{cfg['name']}] 赛季 {s} ...", flush=True)
            try:
                n = load_season(league_code, s, conn, DB_PATH)
                print(f"    写入 {n} 场（已有则跳过）")
            except Exception as e:
                # 网络失败时，本地已有该赛季则沿用，否则中断
                have = conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE league=? AND season=?",
                    (league_code, s),
                ).fetchone()[0]
                if not have:
                    raise
                print(f"    下载失败（{type(e).__name__}），使用本地已有 {have} 场")

    # 2. 多联赛回测对比
    print("\n>>> [2] 多联赛回测对比 ...")
    all_rows, all_pairs = [], []
    for league_code, cfg in LEAGUES.items():
        rows, pairs = _run_league(conn, league_code, cfg)
        all_rows.extend(rows)
        all_pairs.extend(pairs)

    # 汇总表
    print(f"\n{'='*72}")
    print("跨联赛模型对比汇总")
    print(f"{'='*72}")
    print(f"{'联赛':<14} {'模型':<28} {'场数':>5} {'Log Loss':>10} {'Brier':>8}")
    print("-" * 72)
    for r in all_rows:
        print(f"{r['联赛']:<14} {r['模型']:<28} {r['场数']:>5}"
              f" {r['Log Loss']:>10.4f} {r['Brier']:>8.4f}")
    print("=" * 72)

    print("\n同场配对：主模型 − 对照（Log Loss，负=主模型更好；|差| < 2×SE 视为无显著差异）")
    print(f"{'联赛':<14} {'主模型':<12} {'对照':<14} {'场数':>5} {'差值':>9} {'SE':>8}")
    for p in all_pairs:
        print(f"{p['联赛']:<14} {p['主模型']:<12} {p['对照']:<14} {p['n']:>5}"
              f" {p['diff']:>+9.4f} {p['se']:>8.4f}")

    # 3. Platt 校准（用英超作为示例，校准赛季=2324）
    #    已在 2425 月度 OOS 上验证：三联赛 Log Loss 变化均在 ±0.005 内，无显著增益，
    #    仅作展示，正式预测仍用 DC 原始概率。
    print("\n>>> [3] Platt scaling 概率校准（英超 E0）...")
    cal = PlattCalibrator()
    cal.fit(conn, "E0", DixonColesModel,
            calib_seasons=["2324"],
            helper_seasons=["2122", "2223"])

    # 4. 示例预测（各联赛）
    print("\n>>> [4] 示例预测 ...")
    for league_code, (home, away) in DEMO_MATCHES.items():
        cfg        = LEAGUES[league_code]
        cutoff     = _get_demo_cutoff(conn, league_code)
        dc_full    = DixonColesModel()
        dc_full.fit(conn, league_code, cutoff_date=cutoff)
        raw_probs  = dc_full.predict_1x2(home, away)
        cal_probs  = cal.calibrate_dict(raw_probs) if cal.fitted and league_code == "E0" \
                     else raw_probs

        lgbm_full  = LGBMCorrectionModel()
        lgbm_full.fit(conn, league_code, dc_full, cfg["train"])
        lgbm_probs = lgbm_full.predict_match(
            conn, league_code, dc_full, home, away, cutoff
        )

        print(f"\n  [{cfg['name']}] {home} vs {away}  cutoff={cutoff}")
        print(f"    DC 原始:    H={raw_probs['home_win']:.4f} "
              f"D={raw_probs['draw']:.4f} A={raw_probs['away_win']:.4f}")
        if cal.fitted and league_code == "E0":
            print(f"    DC 校准后:  H={cal_probs['home_win']:.4f} "
                  f"D={cal_probs['draw']:.4f} A={cal_probs['away_win']:.4f}")
        print(f"    LightGBM:   H={lgbm_probs['home_win']:.4f} "
              f"D={lgbm_probs['draw']:.4f} A={lgbm_probs['away_win']:.4f} "
              f"(alpha={lgbm_probs['alpha']})")

    # 5. 实盘预测与复盘见 live.py（对真实未开赛场次保存预测，赛后自动评分）
    print("\n>>> [5] 实盘预测请运行：python -m football_prediction.live")

    conn.close()


if __name__ == "__main__":
    main()
