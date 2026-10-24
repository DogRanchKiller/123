"""
football_prediction/live.py  v1.3.0
实盘预测闭环：更新数据 → 赛后评分 → 对未开赛场次保存预测 → 实盘成绩单。
每轮比赛前后各跑一次即可：
    python -m football_prediction.live
规则：
- 只对尚未开球的比赛预测，预测时间必定早于开球时间（无未来信息）。
- 每场每个模型版本只保存首次预测，之后重跑不会覆盖或追加，避免事后挑选。
- 同时保存当时的市场平均赔率（去抽水）作为基准 market_avg，赛后同场对比。
v1.0.1: market_avg 版本号固定为 MARKET_VER，不再跟随数据层版本，避免数据层升级后同场重复基准。
v1.1.0: 新增射正版 DC（dc_sot，model_sot 版本），与 DC / Elo / 市场 同场并列保存。
v1.2.0: 每次运行刷新当前赛季 understat xG；新增 xG 版 DC（dc_xg，model_xg 版本）。
v1.3.0: 输出主模型预测报告（控制台 + reports/ CSV）；成绩单加命中率与 SE；主模型替换检查。
"""
from datetime import datetime, timezone

from football_prediction import version
from football_prediction.data.loader          import init_db, load_season, load_fixtures, season_of
from football_prediction.data.understat       import load_xg
from football_prediction.model_dc.dixon_coles import DixonColesModel
from football_prediction.model_dc.sot_dc      import SotDixonColesModel
from football_prediction.model_dc.xg_dc       import XgDixonColesModel
from football_prediction.model_elo.elo        import EloModel
from football_prediction.output.derive        import derive_markets
from football_prediction.output.report        import build_report, write_report, format_row
from football_prediction.review.store         import (
    has_prediction, save_prediction, score_predictions, live_report, promotion_check,
)

DB_PATH = "football.db"
LEAGUES = {"E0": "英超", "D1": "德甲", "SP1": "西甲"}
MARKET_VER = "1.1.0"   # 市场基准算法版本（1/赔率 按比例去抽水），算法变化时才改


def _update_data(conn, today: str) -> None:
    """刷新当前赛季结果和未开赛赛程；网络失败时沿用本地数据。"""
    season = season_of(today)
    for lg, name in LEAGUES.items():
        try:
            n = load_season(lg, season, conn, DB_PATH)
            print(f"  [{name}] {season} 新增赛果 {n} 场")
        except Exception as e:
            print(f"  [{name}] {season} 下载失败（{type(e).__name__}），使用本地数据")
        # xG 依赖 matches 已有赛果，必须在 load_season 之后
        try:
            n, miss = load_xg(conn, lg, season)
            print(f"  [{name}] {season} 新增 xG {n} 场" + (f"（{miss} 场未对齐）" if miss else ""))
        except Exception as e:
            print(f"  [{name}] {season} xG 下载失败（{type(e).__name__}），xG 版对缺失场次用进球兜底")
    try:
        n = load_fixtures(conn, list(LEAGUES))
        print(f"  未开赛赛程 {n} 场")
    except Exception as e:
        print(f"  赛程下载失败（{type(e).__name__}），使用上次缓存的赛程")


def _predict_upcoming(conn, now: datetime) -> int:
    """对未开球的比赛保存 DC / 射正版 DC / xG 版 DC / Elo / 市场 五条预测，返回新保存条数。"""
    today = now.date().isoformat()
    fixtures = conn.execute(
        """SELECT match_id, league, match_date, kickoff_utc, home_team, away_team,
                  avg_h, avg_d, avg_a
           FROM fixtures ORDER BY kickoff_utc, match_date"""
    ).fetchall()

    dc_ver, elo_ver = version.get("model_dc"), version.get("model_elo")
    sot_ver, xg_ver = version.get("model_sot"), version.get("model_xg")
    feat_ver = version.get("features")
    models, saved = {}, 0

    for (mid, lg, mdate, kickoff, home, away, oh, od, oa) in fixtures:
        if lg not in LEAGUES:
            continue
        # 已开球（或无开球时间且日期已过）的比赛不再预测
        if kickoff:
            if datetime.fromisoformat(kickoff) <= now:
                continue
        elif mdate < today:
            continue

        if lg not in models:
            # cutoff=今天：只用今天之前已完赛的比赛拟合
            dc = DixonColesModel()
            dc.fit(conn, lg, today)
            sot = SotDixonColesModel()
            sot.fit(conn, lg, today)
            xg = XgDixonColesModel()
            xg.fit(conn, lg, today)
            elo = EloModel()
            elo.fit(conn, lg, today)
            models[lg] = (dc, sot, xg, elo)
        dc, sot, xg, elo = models[lg]

        for t in (home, away):
            if t not in dc.attack:
                print(f"  ⚠ {t} 不在 {lg} 历史数据中，DC 用联赛均值兜底")

        for name, model, ver in (("dixon_coles", dc, dc_ver), ("dc_sot", sot, sot_ver),
                                 ("dc_xg", xg, xg_ver)):
            if has_prediction(conn, mid, name, ver):
                continue
            mk = derive_markets(model.score_matrix(home, away))
            extra = {k: v for k, v in mk.items()
                     if k not in ("home_win", "draw", "away_win", "layer_ver")}
            extra["kickoff_utc"] = kickoff
            save_prediction(conn, mid, name, ver, feat_ver,
                            mk["home_win"], mk["draw"], mk["away_win"], extra)
            saved += 1

        if not has_prediction(conn, mid, "elo", elo_ver):
            p = elo.predict(home, away)
            save_prediction(conn, mid, "elo", elo_ver, feat_ver,
                            p["home_win"], p["draw"], p["away_win"],
                            {"kickoff_utc": kickoff})
            saved += 1

        if oh and od and oa and not has_prediction(conn, mid, "market_avg", MARKET_VER):
            inv = [1 / oh, 1 / od, 1 / oa]
            s = sum(inv)
            save_prediction(conn, mid, "market_avg", MARKET_VER, feat_ver,
                            inv[0] / s, inv[1] / s, inv[2] / s,
                            {"odds": [oh, od, oa], "kickoff_utc": kickoff})
            saved += 1
    return saved


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    print(f"系统版本: {version.SYSTEM_VERSION}  当前时间(UTC): {now:%Y-%m-%d %H:%M}")
    conn = init_db(DB_PATH)

    print("\n>>> [1] 更新数据 ...")
    _update_data(conn, today)

    print("\n>>> [2] 赛后评分 ...")
    print(f"  本次评分 {score_predictions(conn)} 条")

    print("\n>>> [3] 未开赛场次预测（所有模型均存档，首次预测为准）...")
    print(f"  新保存 {_predict_upcoming(conn, now)} 条预测")

    p_name, p_key = version.PRIMARY_MODEL
    p_ver = version.get(p_key)
    print(f"\n>>> [4] 预测报告（主模型 {p_name} {p_ver}；信心档后为历史命中率 首选/双选）...")
    rpt = build_report(conn, LEAGUES, p_name, p_ver, now)
    if rpt.empty:
        print("  暂无未开赛场次。")
    else:
        for _, r in rpt.iterrows():
            print(format_row(r))
        print(f"  报告已写入 {write_report(rpt, now)}")
        print("  概率是模型估计，足球结果随机性大：即使'高'信心档，历史上也约有 1/4 不中。")

    print("\n>>> [5] 实盘成绩单（同场对比市场，差值负=优于市场；|差值| < 2×SE 视为无显著差异）...")
    rep = live_report(conn)
    if rep.empty:
        print("  暂无已评分的实盘预测，比赛结束、数据源更新后再运行即可。")
    else:
        print(f"  {'模型':<16}{'版本':<8}{'场数':>5}{'LogLoss':>9}{'Brier':>8}{'命中率':>7}"
              f"{'同场':>6}{'差值':>9}{'SE':>8}")
        for _, r in rep.iterrows():
            print(f"  {r['model_name']:<16}{r['model_ver']:<8}{r['matches']:>5}"
                  f"{r['log_loss']:>9.4f}{r['brier']:>8.4f}{r['hit_rate']:>7.1%}"
                  f"{r['paired_n']:>6}{r['diff_vs_base']:>+9.4f}{r['se']:>8.4f}")

        print(f"\n>>> [6] 主模型替换检查（规则：同场 ≥ {version.PROMOTE_MIN_N} 场且 差值+2×SE < 0）...")
        chk = promotion_check(conn, (p_name, p_ver), version.PROMOTE_MIN_N)
        for _, r in chk.iterrows():
            print(f"  {r['model_name']:<16}{r['model_ver']:<8} 对主模型 {r['diff']:+.4f}±{r['se']:.4f}"
                  f"  → {r['verdict']}")
    conn.close()


if __name__ == "__main__":
    main()
