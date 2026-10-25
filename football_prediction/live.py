"""
football_prediction/live.py  v1.9.0
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
v1.5.0: 并行存档 market_shin（Shin 去水的市场隐含，model_market_shin 版本）与 dc_market（用历史赔率 λ
        估强度的 DC，model_dc_market 版本）；understat 缺的 xG 用 FotMob 补；
        新增 --near 临场档：开球前 T1_HOURS 小时内抓多家赔率与阵容，存 market_avg_t1 / market_implied_t1 /
        market_shin_t1（多家中位数赔率），成绩单另列各临场档与赛前档的同场对比；
        已公布正式首发时另存 lineup_t1（阵容调整后的市场隐含）与 lineup_base_t1（同时刻未调整，配对基准）。
v1.6.0: 实盘联赛加意甲 I1、法甲 F1（2122 起的赛季，与另外三联赛相同；Elo / DC 按联赛分别拟合，
        原三联赛的预测不受影响）。
v1.7.0: 临场档先抓阵容再抓赔率；lineup_t1 按赔率与首次看到正式首发的先后选阵容系数（model_lineup 1.1.0
        合并规则），extra 记 odds_vs_lineup；每场打印临场最终看法（阵容调整 > T1 市场隐含），不另存档。
v1.8.0: 更新数据时抓 FotMob 各联赛页的完赛比分（fotmob_results，每联赛 1 次请求）；football-data 赛果未到时
        先用它评分，到达后 reconcile_results 核对，不一致按 football-data 重评。预测与模型拟合不受影响。
v1.9.0: 实盘联赛加英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1（2122 起；模型按联赛分别拟合，
        原五联赛的预测不受影响）。understat 没有这六个联赛，跳过 load_xg，xG 只靠 FotMob 补，补不到时
        dc_xg 用进球兜底。
"""
import argparse
import shutil
from datetime import date, datetime, timedelta, timezone

from football_prediction import version
from football_prediction.data                 import fotmob, oddsportal
from football_prediction.data.loader          import init_db, load_season, season_of
from football_prediction.data.fixtures        import load_fixtures
from football_prediction.data.oddsportal      import book_consensus
from football_prediction.data.understat       import US_LEAGUES, load_xg
from football_prediction.model_blend.blend    import MODEL_NAME as BLEND_NAME
from football_prediction.model_dc.market_dc   import MODEL_NAME as DC_MARKET_NAME
from football_prediction.model_lineup.adjust  import (
    MODEL_NAME as LINEUP_NAME, adjust_lambdas, coef_for, odds_timing,
)
from football_prediction.model_lineup.ratings import LineupModel, current_lineup, first_standard_at
from football_prediction.model_market.devig   import SHIN_NAME
from football_prediction.model_market.implied import (
    MODEL_NAME as IMPLIED_NAME, dc_matrix, implied_matrix,
)
from football_prediction.output.analysis      import devig, odds_dict
from football_prediction.output.derive        import derive_markets
from football_prediction.output.pipeline      import FIXTURE_ODDS, ModelCache, fixture_odds
from football_prediction.output.report        import (
    build_report, upcoming_fixtures, write_report, format_row,
)
from football_prediction.review.store         import (
    has_prediction, save_prediction, score_predictions, live_report, promotion_check, horizon_report,
    pending_fotmob, reconcile_results,
)

DB_PATH = "football.db"
LEAGUES = {"E0": "英超", "D1": "德甲", "SP1": "西甲", "I1": "意甲", "F1": "法甲",
           "E1": "英冠", "N1": "荷甲", "P1": "葡超", "SC0": "苏超", "B1": "比甲", "T1": "土超"}
MARKET_VER = "1.1.0"   # 市场基准算法版本（1/赔率 按比例去抽水），算法变化时才改
T1_HOURS = 1.5         # 临场档：开球前 1.5 小时内
T1_FRESH_MIN = 90      # 临场档只用 90 分钟内抓到的多家赔率
T1_MIN_BOOKS = 3       # 且至少 3 家公司


def _update_data(conn, today: str) -> None:
    """刷新当前赛季结果和未开赛赛程（同时追加赔率快照）；网络失败时沿用本地数据。"""
    season = season_of(today)
    for lg, name in LEAGUES.items():
        try:
            n = load_season(lg, season, conn, DB_PATH)
            print(f"  [{name}] {season} 新增赛果 {n} 场")
        except Exception as e:
            print(f"  [{name}] {season} 下载失败（{type(e).__name__}），使用本地数据")
        if lg not in US_LEAGUES:   # understat 没有的联赛，xG 只靠下面的 FotMob 补
            continue
        # xG 依赖 matches 已有赛果，必须在 load_season 之后
        try:
            n, miss = load_xg(conn, lg, season)
            print(f"  [{name}] {season} 新增 xG {n} 场" + (f"（{miss} 场未对齐）" if miss else ""))
        except Exception as e:
            print(f"  [{name}] {season} xG 下载失败（{type(e).__name__}），xG 版对缺失场次用进球兜底")
    # understat 完赛数天仍缺的场次，用已抓的 FotMob 全队 xG 补（不联网）
    n = fotmob.backfill_xg(conn, date.fromisoformat(today))
    if n:
        print(f"  FotMob xG 补入 {n} 场（understat 缺）")
    try:
        n = load_fixtures(conn, list(LEAGUES))
        print(f"  未开赛赛程 {n} 场（赔率快照已追加）")
    except Exception as e:
        print(f"  赛程下载失败（{type(e).__name__}），使用上次缓存的赛程")
    # football-data 赛果常晚几天；FotMob 联赛页的完赛比分只用于先评分，不进 matches
    try:
        n = fotmob.collect_results(conn, list(LEAGUES), season)
        print(f"  FotMob 赛果 新增 {n} 场（只用于评分，football-data 到达后核对）")
    except Exception as e:
        print(f"  FotMob 赛果抓取失败（{type(e).__name__}），评分只用 football-data")


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
            BLEND_NAME: version.get("model_blend"), DC_MARKET_NAME: version.get("model_dc_market")}
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

        for name, model in (("dixon_coles", lm.dc), ("dc_sot", lm.sot), ("dc_xg", lm.xg),
                            (DC_MARKET_NAME, lm.market)):
            if has_prediction(conn, mid, name, vers[name]):
                continue
            m = model.score_matrix(home, away)
            mk = derive_markets(m)
            save(mid, name, vers[name], (mk["home_win"], mk["draw"], mk["away_win"]),
                 _markets_extra(m, kickoff))

        inp = lm.inputs(home, away)
        save(mid, "elo", vers["elo"], inp["models"]["elo"], {"kickoff_utc": kickoff})
        save(mid, BLEND_NAME, vers[BLEND_NAME], inp["models"]["blend"], {"kickoff_utc": kickoff})

        saved += _save_market(conn, mid, fixture_odds(r), inp["rho"], kickoff, feat_ver)
    return saved


def _save_market(conn, mid: str, odds: dict, rho: float, kickoff, feat_ver: str,
                 suffix: str = "", info: dict | None = None) -> int:
    """市场基准 market_avg + 市场隐含（按比例去水 / Shin 去水）。suffix="_t1" 为临场存档。"""
    saved = 0

    def save(name, ver, p, extra):
        nonlocal saved
        if not has_prediction(conn, mid, name, ver):
            save_prediction(conn, mid, name, ver, feat_ver, p[0], p[1], p[2], {**extra, **(info or {})})
            saved += 1

    mkt = devig(odds["avg_h"], odds["avg_d"], odds["avg_a"])
    if not mkt:
        return 0
    save("market_avg" + suffix, MARKET_VER, mkt,
         {"odds": [odds["avg_h"], odds["avg_d"], odds["avg_a"]], "kickoff_utc": kickoff})
    # 市场隐含：需胜平负 + 大小球盘（只有胜平负时反推的大小球不如 dc_xg，不存档）
    if not devig(odds["avg_over25"], odds["avg_under25"]):
        return saved
    for name, key, method in ((IMPLIED_NAME, "model_market", "proportional"),
                              (SHIN_NAME, "model_market_shin", "shin")):
        ver = version.get(key)
        if has_prediction(conn, mid, name + suffix, ver):
            continue
        m, fit = implied_matrix(odds_dict(odds), rho, method=method)
        mk = derive_markets(m)
        extra = _markets_extra(m, kickoff)
        extra.update(fit={k: fit[k] for k in ("lam_h", "lam_a", "rmse", "used")}, rho=rho,
                     odds={k: odds.get(k) for k in FIXTURE_ODDS})
        save(name + suffix, ver, (mk["home_win"], mk["draw"], mk["away_win"]), extra)
    return saved


def _lineup_view(conn, r: dict, odds: dict, rho: float, models: dict, cutoff: str) -> dict | None:
    """已公布正式首发（standard）时的阵容调整：市场隐含 λ 乘按赔率与首发先后选的那套系数
    （model_lineup.adjust 的合并规则，一场只叠一次）。没有正式首发或缺大小球盘时 None。"""
    try:
        cur = current_lineup(conn, r["match_id"])
        lineup_at = first_standard_at(conn, r["match_id"])
    except Exception:                       # 未挂 FotMob 库（没有 lineups 表）
        return None
    if not cur or cur[0] != "standard" or not devig(odds["avg_over25"], odds["avg_under25"]):
        return None
    lg = r["league"]
    if lg not in models:
        models[lg] = LineupModel()
        models[lg].fit(conn, lg, cutoff)
    f_h = models[lg].team_features(r["home_team"], cur[1]["home"])
    f_a = models[lg].team_features(r["away_team"], cur[1]["away"])
    got = implied_matrix(odds_dict(odds), rho)
    if f_h is None or f_a is None or got is None:
        return None
    base, fit = got
    timing = odds_timing(odds.get("fetched_at"), lineup_at)
    lh, la = adjust_lambdas(fit["lam_h"], fit["lam_a"], f_h, f_a, coef_for(timing))
    return {"base": base, "adj": dc_matrix(lh, la, rho), "lam_base": (fit["lam_h"], fit["lam_a"]),
            "lam_adj": (lh, la), "f_h": f_h, "f_a": f_a, "timing": timing, "lineup_at": lineup_at}


def _save_lineup(conn, r: dict, view: dict | None, rho: float, info: dict) -> int:
    """lineup_base_t1 = 市场隐含，lineup_t1 = 其 λ 乘阵容调整。两者同版本（model_lineup）、同赔率，
    horizon_report 同场配对即阵容信息的增量；extra 记下赔率相对首发的先后（odds_vs_lineup）。"""
    ver = version.get("model_lineup")
    if view is None or has_prediction(conn, r["match_id"], LINEUP_NAME + "_t1", ver):
        return 0
    saved = 0
    for name, m, lam in (("lineup_base_t1", view["base"], view["lam_base"]),
                         (LINEUP_NAME + "_t1", view["adj"], view["lam_adj"])):
        if has_prediction(conn, r["match_id"], name, ver):
            continue
        mk = derive_markets(m)
        extra = _markets_extra(m, r["kickoff_utc"])
        extra.update(info, lam=[round(lam[0], 4), round(lam[1], 4)], rho=rho,
                     lineup={"home": view["f_h"], "away": view["f_a"]},
                     odds_vs_lineup=view["timing"], lineup_first_seen=view["lineup_at"])
        save_prediction(conn, r["match_id"], name, ver, version.get("features"),
                        mk["home_win"], mk["draw"], mk["away_win"], extra)
        saved += 1
    return saved


def _final_view(r: dict, odds: dict, rho: float, view: dict | None) -> str:
    """临场最终看法（只打印，不存档）：有正式首发用阵容调整后的矩阵，否则用 T1 赔率的市场隐含。"""
    if view is not None:
        m, src = view["adj"], f"T1 赔率 + 阵容（赔率{'晚' if view['timing'] == 'post' else '早'}于首发）"
    else:
        got = implied_matrix(odds_dict(odds), rho) if devig(odds["avg_over25"], odds["avg_under25"]) else None
        if got is None:
            return ""
        m, src = got[0], "T1 赔率"
    mk = derive_markets(m)
    return (f"  [{LEAGUES.get(r['league'], r['league'])}] {r['home_team']} vs {r['away_team']}  "
            f"主/平/客 {mk['home_win']:.0%}/{mk['draw']:.0%}/{mk['away_win']:.0%}  "
            f"大2.5 {mk['over_2.5']:.0%}  （{src}，{odds['n_books']} 家）")


def _predict_near(conn, now: datetime, cache: ModelCache) -> int:
    """开球前 T1_HOURS 小时内、且有 T1_FRESH_MIN 分钟内抓到的多家赔率的场次：存 *_t1 临场档。"""
    saved, lineup_models = 0, {}
    for r in upcoming_fixtures(conn, LEAGUES, now):
        if not r["kickoff_utc"]:
            continue
        hours = (datetime.fromisoformat(r["kickoff_utc"]) - now).total_seconds() / 3600
        if hours > T1_HOURS:
            continue
        cons = book_consensus(conn, r["match_id"])
        if not cons or cons["n_books"] < T1_MIN_BOOKS or \
                now - datetime.fromisoformat(cons["fetched_at"]) > timedelta(minutes=T1_FRESH_MIN):
            continue
        rho = cache.get(r["league"]).inputs(r["home_team"], r["away_team"])["rho"]
        info = {"horizon": "t1", "odds_source": "oddsportal_median", "n_books": cons["n_books"],
                "odds_fetched_at": cons["fetched_at"], "hours_to_ko": round(hours, 2)}
        saved += _save_market(conn, r["match_id"], cons, rho, r["kickoff_utc"],
                              version.get("features"), "_t1", info)
        view = _lineup_view(conn, r, cons, rho, lineup_models, cache.cutoff)
        saved += _save_lineup(conn, r, view, rho, info)
        line = _final_view(r, cons, rho, view)
        if line:
            print(line)
    return saved


def _run_near(conn, now: datetime, collect_odds=None, collect_lineups=None) -> int:
    """临场一轮：抓开球前 T1_HOURS 小时内的多家赔率与阵容 → 存 *_t1 临场档。返回新存档条数。"""
    lo, hi = now.isoformat(), (now + timedelta(hours=T1_HOURS)).isoformat()
    n_fx = conn.execute("SELECT COUNT(*) FROM fixtures WHERE kickoff_utc > ? AND kickoff_utc <= ?",
                        (lo, hi)).fetchone()[0]
    print(f"  {T1_HOURS} 小时内开球 {n_fx} 场")
    if not n_fx:
        return 0
    # 先抓阵容再抓赔率：同一轮里赔率晚于首发，按合并规则算「赔率已含阵容」（COEF_POST）
    try:
        got = (collect_lineups or fotmob.collect_upcoming)(conn, now, T1_HOURS)
        print("  阵容：" + ("，".join(f"{m} {t}" for m, t in got) if got else "暂无"))
    except Exception as e:
        print(f"  阵容抓取失败（{type(e).__name__}: {e}）")
    if collect_odds is None and shutil.which(oddsportal.harvester_path()):
        collect_odds = oddsportal.collect
    if collect_odds:
        try:
            print(f"  多家赔率 {collect_odds(conn, list(LEAGUES), now, hours=T1_HOURS)} 行")
        except Exception as e:
            print(f"  多家赔率抓取失败（{type(e).__name__}: {e}），沿用已有数据")
    else:
        print("  未找到 OddsHarvester（.venv-scrape），只用已有多家赔率")
    return _predict_near(conn, now, ModelCache(conn, now.date().isoformat()))


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="实盘预测闭环")
    ap.add_argument("--near", action="store_true",
                    help=f"只跑临场档：开球前 {T1_HOURS} 小时内的多家赔率 + 阵容 → *_t1 存档")
    ns = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    print(f"系统版本: {version.SYSTEM_VERSION}  当前时间(UTC): {now:%Y-%m-%d %H:%M}")
    conn = init_db(DB_PATH)
    fotmob.attach(conn)
    if ns.near:
        print("\n>>> 临场档（T1）...")
        print(f"  新保存 {_run_near(conn, now)} 条临场预测")
        conn.close()
        return

    print("\n>>> [1] 更新数据 ...")
    _update_data(conn, today)

    print("\n>>> [2] 赛后评分 ...")
    n, bad = reconcile_results(conn)
    if n:
        print(f"  football-data 赛果核对 {n} 条先用 FotMob 比分评过的预测，比分不一致 {len(bad)} 场"
              + ("（已按 football-data 重评）" if bad else ""))
    for b in bad:
        print(f"    {b['match_id']}: FotMob {b['fotmob']} → football-data {b['fd']}")
    print(f"  本次评分 {score_predictions(conn)} 条")
    n = pending_fotmob(conn)
    if n:
        print(f"  其中 {n} 场暂用 FotMob 比分，等 football-data 核对")

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

        hz = horizon_report(conn)
        if not hz.empty:
            print("\n>>> [7] 临场档（开球前约 1 小时）对赛前档，同场 log loss 差（负=临场更好）...")
            for _, r in hz.iterrows():
                print(f"  {r['model_name']:<20}{r['model_ver']:<8} 对 {r['base']:<16}"
                      f"{r['paired_n']:>5} 场 {r['diff']:+.4f}±{r['se']:.4f}")
    conn.close()


if __name__ == "__main__":
    main()
