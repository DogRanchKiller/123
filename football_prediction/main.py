"""
football_prediction/main.py  v1.3.0
主入口：回测演示的命令行（串联在 services/backtest_run.py，本文件只打印）。
v1.1.0: 多联赛跨联赛验证（E0/D1/SP1）；Platt scaling 概率校准；LightGBM v1.1.0 滚动OOS。
v1.2.0: 测试赛季改为全新留出的 2526；加入市场赔率基准与同场配对比较；实盘预测移至 live.py。
v1.3.0: 加入射正版 DC 月度（model_sot，w 在 2324+2425 选参）及其与 DC 月度、市场的配对比较。
用法：python -m football_prediction.main
"""
import functools

from football_prediction import version
from football_prediction.data.loader import init_db
from football_prediction.services import (
    BACKTEST_LEAGUES, calibrate_demo, load_backtest_data, run_demo_predictions, run_league_backtest,
)

DB_PATH = "football.db"
_log = functools.partial(print, flush=True)


def _p3(p: dict) -> str:
    return f"H={p['home_win']:.4f} D={p['draw']:.4f} A={p['away_win']:.4f}"


def main():
    print(f"系统版本: {version.SYSTEM_VERSION}")
    print(f"各层版本: {version.LAYER_VERSIONS}\n")

    print(">>> [1] 初始化数据库并下载数据 ...")
    conn = init_db(DB_PATH)
    load_backtest_data(conn, DB_PATH, _log)

    print("\n>>> [2] 多联赛回测对比 ...")
    all_rows, all_pairs = [], []
    for code in BACKTEST_LEAGUES:
        rows, pairs = run_league_backtest(conn, code, _log)
        all_rows.extend(rows)
        all_pairs.extend(pairs)

    print(f"\n{'=' * 72}\n跨联赛模型对比汇总\n{'=' * 72}")
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

    print("\n>>> [3] Platt scaling 概率校准（英超 E0）...")
    cal = calibrate_demo(conn)

    print("\n>>> [4] 示例预测 ...")
    for d in run_demo_predictions(conn, cal):
        print(f"\n  [{d['name']}] {d['home']} vs {d['away']}  cutoff={d['cutoff']}")
        print(f"    DC 原始:    {_p3(d['raw'])}")
        if d["calibrated"] is not None:
            print(f"    DC 校准后:  {_p3(d['calibrated'])}")
        lg = d["lgbm"]
        print(f"    LightGBM:   {_p3(lg)} (alpha={lg['alpha']})")

    print("\n>>> [5] 实盘预测请运行：python -m football_prediction.live")
    conn.close()


if __name__ == "__main__":
    main()
