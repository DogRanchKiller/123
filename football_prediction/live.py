"""
football_prediction/live.py  v1.4.0
实盘预测闭环：更新数据（含赔率快照）→ 赛后评分 → 对未开赛场次存档预测 → 预测报告 → 实盘成绩单。
每轮比赛前后各跑一次即可（开赛前多跑几次可记录盘口变动）：
    python -m football_prediction.live
单场说明：python -m football_prediction.explain 英超 主队 客队
规则：
- 只对尚未开球的比赛预测，预测时间必定早于开球时间（无未来信息）。
- 每场每个模型版本只保存首次预测，之后重跑不会覆盖或追加，避免事后挑选。
- 同时保存当时的市场平均赔率（去抽水）作为基准 market_avg，赛后同场对比。
- 报告按最新赔率现算（当前看法）；存档只认首次预测，二者互不影响。
v1.0.1: market_avg 版本号固定为 MARKET_VER，不再跟随数据层版本，避免数据层升级后同场重复基准。
v1.1.0: 新增射正版 DC（dc_sot，model_sot 版本），与 DC / Elo / 市场 同场并列保存。
v1.2.0: 每次运行刷新当前赛季 understat xG；新增 xG 版 DC（dc_xg，model_xg 版本）。
v1.3.0: 输出主模型预测报告（控制台 + reports/ CSV）；成绩单加命中率与 SE；主模型替换检查。
v1.4.0: 按判断流程出报告（市场为底 + 自研对照 + 盘口变动 + 风险）；新增存档 market_implied
        （有胜平负与大小球盘时）与 blend_xg_elo；DC 系与市场隐含存比分矩阵，成绩单加大小2.5/比分 log loss。
"""
from datetime import datetime, timezone

from football_prediction import version
from football_prediction.data.loader          import init_db, load_season, load_fixtures, season_of
from football_prediction.data.understat       import load_xg
from football_prediction.model_blend.blend    import MODEL_NAME as BLEND_NAME
from football_prediction.model_market.implied import MODEL_NAME as IMPLIED_NAME, implied_matrix
from football_prediction.output.analysis      import devig, odds_dict
from football_prediction.output.derive        import derive_markets
from football_prediction.output.pipeline      import ModelCache, fixture_odds
from football_prediction.output.report        import (
    build_report, upcoming_fixtures, write_report, format_row,
)
from football_prediction.review.store         import (
    has_prediction, save_prediction, score_predictions, live_report, promotion_check,
)

DB_PATH = "football.db"
LEAGUES = {"E0": "英超", "D1": "德甲", "SP1": "西甲"}
MARKET_VER = "1.1.0"   # 市场基准算法版本（1/赔率 按比例去抽水），算法变化时才改


def _update_data(conn, today: str) -> None:
    """刷新当前赛季结果和未开赛赛程（同时追加赔率快照）；网络失败时沿用本地数据。"""
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
        print(f"  未开赛赛程 {n} 场（赔率快照已追加）")
    except Exception as e:
        print(f"  赛程下载失败（{type(e).__name__}），使用上次缓存的赛程")


def _markets_extra(m, kickoff) -> dict:
    """比分矩阵派生的各盘口 + 展平的比分矩阵（赛后评精确比分用）"""
    mk = derive_markets(m)
    extra = {k: v for k, v in mk.items() if k not in ("home_win", "draw", "away_win", "layer_ver")}
    extra["score_matrix"] = [round(float(x), 6) for x in m.ravel()]
    extra["kickoff_utc"] = kickoff
    return extra


def _predict_upcoming(conn, now: datetime, cache: ModelCache | None = None) -> int:
    """对未开球的比赛存档 DC / 射正 DC / xG DC / Elo / blend / 市场 / 市场隐含，返回新保存条数。"""
    cache = cache or ModelCache(conn, now.date().isoformat())
    feat_ver = version.get("features")
    vers = {"dixon_coles": version.get("model_dc"), "dc_sot": version.get("model_sot"),
            "dc_xg": version.get("model_xg"), "elo": version.get("model_elo"),
            BLEND_NAME: version.get("model_blend"), IMPLIED_NAME: version.get("model_market")}
    saved = 0

    def save(mid, name, ver, p, extra):
        nonlocal saved
        if not has_prediction(conn, mid, name, ver):
            save_prediction(conn, mid, name, ver, feat_ver, p[0], p[1], p[2], extra)
            saved += 1

    for r in upcoming_fixtures(conn, LEAGUES, now):
        mid, lg, home, away, kickoff = (r["match_id"], r["league"], r["home_team"],
                                        r["away_team"], r["kickoff_utc"])
        lm = cache.get(lg)
        for t in (home, away):
            if not lm.known(t):
                print(f"  ⚠ {t} 不在 {lg} 历史数据中，DC 用联赛均值兜底")

        for name, model in (("dixon_coles", lm.dc), ("dc_sot", lm.sot), ("dc_xg", lm.xg)):
            if has_prediction(conn, mid, name, vers[name]):
                continue
            m = model.score_matrix(home, away)
            mk = derive_markets(m)
            save(mid, name, vers[name], (mk["home_win"], mk["draw"], mk["away_win"]),
                 _markets_extra(m, kickoff))

        inp = lm.inputs(home, away)
        save(mid, "elo", vers["elo"], inp["models"]["elo"], {"kickoff_utc": kickoff})
        save(mid, BLEND_NAME, vers[BLEND_NAME], inp["models"]["blend"], {"kickoff_utc": kickoff})

        odds = fixture_odds(r)
        mkt = devig(odds["avg_h"], odds["avg_d"], odds["avg_a"])
        if mkt:
            save(mid, "market_avg", MARKET_VER, mkt,
                 {"odds": [odds["avg_h"], odds["avg_d"], odds["avg_a"]], "kickoff_utc": kickoff})
        # 市场隐含：需胜平负 + 大小球盘（只有胜平负时反推的大小球不如 dc_xg，不存档）
        if mkt and devig(odds["avg_over25"], odds["avg_under25"]) \
                and not has_prediction(conn, mid, IMPLIED_NAME, vers[IMPLIED_NAME]):
            m, fit = implied_matrix(odds_dict(odds), inp["rho"])
            mk = derive_markets(m)
            extra = _markets_extra(m, kickoff)
            extra.update(fit={k: fit[k] for k in ("lam_h", "lam_a", "rmse", "used")},
                         rho=inp["rho"], odds=odds)
            save(mid, IMPLIED_NAME, vers[IMPLIED_NAME],
                 (mk["home_win"], mk["draw"], mk["away_win"]), extra)
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

    print("\n>>> [3] 未开赛场次预测存档（所有模型，首次预测为准）...")
    cache = ModelCache(conn, today)
    print(f"  新保存 {_predict_upcoming(conn, now, cache)} 条预测")

    p_name, p_key = version.PRIMARY_MODEL
    p_ver = version.get(p_key)
    print("\n>>> [4] 预测报告（最新赔率；胜平负=市场去水，比分=市场隐含，自研模型作对照；"
          "信心档后为历史命中率 首选/双选）...")
    rpt = build_report(conn, LEAGUES, now, cache)
    if rpt.empty:
        print("  暂无未开赛场次。")
    else:
        for _, r in rpt.iterrows():
            print(format_row(r))
        print(f"  报告已写入 {write_report(rpt, now)}")
        print("  概率是估计，足球结果随机性大：即使'高'信心档，历史上也约有 1/4 不中。")

    print("\n>>> [5] 实盘成绩单（同场对比市场，差值负=优于市场；|差值| < 2×SE 视为无显著差异；"
          "大小2.5/比分为对应 log loss）...")
    rep = live_report(conn)
    if rep.empty:
        print("  暂无已评分的实盘预测，比赛结束、数据源更新后再运行即可。")
    else:
        print(f"  {'模型':<16}{'版本':<8}{'场数':>5}{'LogLoss':>9}{'Brier':>8}{'命中率':>7}"
              f"{'同场':>6}{'差值':>9}{'SE':>8}{'大小2.5':>9}{'比分':>8}")
        for _, r in rep.iterrows():
            print(f"  {r['model_name']:<16}{r['model_ver']:<8}{r['matches']:>5}"
                  f"{r['log_loss']:>9.4f}{r['brier']:>8.4f}{r['hit_rate']:>7.1%}"
                  f"{r['paired_n']:>6}{r['diff_vs_base']:>+9.4f}{r['se']:>8.4f}"
                  f"{r['ou25_ll']:>9.4f}{r['score_ll']:>8.4f}")

        print(f"\n>>> [6] 主模型替换检查（主模型 {p_name} {p_ver}；"
              f"规则：同场 ≥ {version.PROMOTE_MIN_N} 场且 差值+2×SE < 0）...")
        chk = promotion_check(conn, (p_name, p_ver), version.PROMOTE_MIN_N)
        for _, r in chk.iterrows():
            print(f"  {r['model_name']:<16}{r['model_ver']:<8} 对主模型 {r['diff']:+.4f}±{r['se']:.4f}"
                  f"  → {r['verdict']}")
    conn.close()


if __name__ == "__main__":
    main()
