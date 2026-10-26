"""
services/near_round.py  临场档一轮（中间层）
开球前 T1_HOURS 小时内：先抓阵容再抓多家赔率 → 存 *_t1 临场档（market_avg / market_implied / market_shin），
已公布正式首发时另存 lineup_t1 与配对基准 lineup_base_t1；每场输出临场最终看法（只输出，不另存档）。
开球前 T2_HOURS 小时内、且赔率在 T2_FRESH_MIN 分钟内抓到时，另存更接近开球的 *_t2（只有三个市场模型）。
窗口内有场次时，按最新赔率重写给接口读的快照（refresh_snapshot），网站看到开球前的多家赔率。
命令行入口是 `live.py --near`；行为与版本说明见 live.py 的文件头。
一轮的时刻用 live_round.round_clock：抓取与拟合之后、存档之前再取，已开球的场次不存。
"""
import shutil
import sqlite3
from datetime import datetime, timedelta

from football_prediction import version
from football_prediction.data import fotmob, oddsportal
from football_prediction.data.oddsportal import book_consensus
from football_prediction.model_lineup.adjust import (
    MODEL_NAME as LINEUP_NAME, adjust_lambdas, coef_for, odds_timing,
)
from football_prediction.model_lineup.ratings import LineupModel, current_lineup, first_standard_at
from football_prediction.model_market.implied import dc_matrix, implied_matrix
from football_prediction.output.analysis import devig, odds_dict
from football_prediction.output.derive import derive_markets
from football_prediction.output.report import upcoming_fixtures
from football_prediction.review.store import has_prediction, save_prediction
from football_prediction.services.live_round import (
    LEAGUES, SNAPSHOT_PATH, Clock, Log, markets_extra, match_ident, refresh_snapshot, round_clock,
    save_market,
)
from football_prediction.services.match_analysis import ModelCache

T1_HOURS = 1.5         # 临场档：开球前 1.5 小时内
T1_FRESH_MIN = 90      # 临场档只用 90 分钟内抓到的多家赔率
T1_MIN_BOOKS = 3       # 且至少 3 家公司
T2_HOURS = 0.6         # 第二临场档：存档时离开球 0.6 小时内（每 30 分钟一轮，存档约在开球前 0.3–0.6 小时）
T2_FRESH_MIN = 30      # 第二临场档只用本轮抓到的多家赔率（上一轮的已超过 30 分钟）


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


def _save_lineup(conn, r: dict, view: dict | None, rho: float, info: dict, at: datetime) -> int:
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
        extra = markets_extra(m, r["kickoff_utc"])
        extra.update(info, lam=[round(lam[0], 4), round(lam[1], 4)], rho=rho,
                     lineup={"home": view["f_h"], "away": view["f_a"]},
                     odds_vs_lineup=view["timing"], lineup_first_seen=view["lineup_at"])
        if save_prediction(conn, r["match_id"], name, ver, version.get("features"),
                           mk["home_win"], mk["draw"], mk["away_win"], extra, at=at):
            saved += 1
    return saved


def _final_view(r: dict, odds: dict, rho: float, view: dict | None) -> str:
    """临场最终看法（只输出，不存档）：有正式首发用阵容调整后的矩阵，否则用 T1 赔率的市场隐含。"""
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


def predict_near(conn: sqlite3.Connection, now: datetime, cache: ModelCache, log: Log = print,
                 clock: Clock | None = None) -> int:
    """开球前 T1_HOURS 小时内、且有 T1_FRESH_MIN 分钟内抓到的多家赔率的场次：存 *_t1 临场档；
    同时在 T2_HOURS 小时内、赔率在 T2_FRESH_MIN 分钟内的再存 *_t2（各档每场只存首次）。
    clock 是本轮时钟（默认从 now 起算）；每场在拟合之后取存档时刻，已开球的不存。"""
    clock = clock or round_clock(now)
    saved, lineup_models = 0, {}
    for r in upcoming_fixtures(conn, LEAGUES, clock()):
        if not r["kickoff_utc"]:
            continue
        if (datetime.fromisoformat(r["kickoff_utc"]) - clock()).total_seconds() / 3600 > T1_HOURS:
            continue
        cons = book_consensus(conn, r["match_id"])
        if not cons or cons["n_books"] < T1_MIN_BOOKS:
            continue
        rho = cache.get(r["league"]).inputs(r["home_team"], r["away_team"])["rho"]   # 首次拟合可能耗时
        at = clock()
        hours = (datetime.fromisoformat(r["kickoff_utc"]) - at).total_seconds() / 3600
        if hours <= 0:
            log(f"  已开球，不存临场档：{r['home_team']} vs {r['away_team']}")
            continue
        if at - datetime.fromisoformat(cons["fetched_at"]) > timedelta(minutes=T1_FRESH_MIN):
            continue
        info = {"horizon": "t1", "odds_source": "oddsportal_median", "n_books": cons["n_books"],
                "odds_fetched_at": cons["fetched_at"], "hours_to_ko": round(hours, 2), **match_ident(r)}
        saved += save_market(conn, r["match_id"], cons, rho, r["kickoff_utc"],
                             version.get("features"), "_t1", info, at=at)
        if hours <= T2_HOURS and at - datetime.fromisoformat(cons["fetched_at"]) <= timedelta(minutes=T2_FRESH_MIN):
            saved += save_market(conn, r["match_id"], cons, rho, r["kickoff_utc"],
                                 version.get("features"), "_t2", info | {"horizon": "t2"}, at=at)
        view = _lineup_view(conn, r, cons, rho, lineup_models, cache.cutoff)
        # 阵容模型首次拟合也耗时：存之前再取一次时刻，已开球时 save_prediction 不存
        saved += _save_lineup(conn, r, view, rho, info, clock())
        line = _final_view(r, cons, rho, view)
        if line:
            log(line)
    return saved


def run_near(conn: sqlite3.Connection, now: datetime, collect_odds=None, collect_lineups=None,
             log: Log = print, snapshot_path: str | None = SNAPSHOT_PATH) -> int:
    """临场一轮：抓开球前 T1_HOURS 小时内的多家赔率与阵容 → 存 *_t1 临场档 → 重写快照。返回新存档条数。
    collect_odds / collect_lineups 可替换（测试用）；不传时用 OddsHarvester 与 FotMob。
    窗口内没有场次时不重写快照；snapshot_path=None 时不写。
    抓阵容和赔率可能要二十多分钟：存档与快照按本轮时钟的当前时刻判断是否已开球，不用开头的 now。"""
    clock = round_clock(now)
    lo, hi = now.isoformat(), (now + timedelta(hours=T1_HOURS)).isoformat()
    n_fx = conn.execute("SELECT COUNT(*) FROM fixtures WHERE kickoff_utc > ? AND kickoff_utc <= ?",
                        (lo, hi)).fetchone()[0]
    log(f"  {T1_HOURS} 小时内开球 {n_fx} 场")
    if not n_fx:
        return 0
    # 先抓阵容再抓赔率：同一轮里赔率晚于首发，按合并规则算「赔率已含阵容」（COEF_POST）
    try:
        got = (collect_lineups or fotmob.collect_upcoming)(conn, now, T1_HOURS)
        log("  阵容：" + ("，".join(f"{m} {t}" for m, t in got) if got else "暂无"))
    except Exception as e:
        log(f"  阵容抓取失败（{type(e).__name__}: {e}）")
    if collect_odds is None and shutil.which(oddsportal.harvester_path()):
        collect_odds = oddsportal.collect
    if collect_odds:
        try:
            log(f"  多家赔率 {collect_odds(conn, list(LEAGUES), now, hours=T1_HOURS)} 行")
        except Exception as e:
            log(f"  多家赔率抓取失败（{type(e).__name__}: {e}），沿用已有数据")
    else:
        log("  未找到 OddsHarvester（.venv-scrape），只用已有多家赔率")
    cache = ModelCache(conn, now.date().isoformat())
    saved = predict_near(conn, now, cache, log, clock)
    if snapshot_path:
        n = refresh_snapshot(conn, now, cache, snapshot_path, clock)
        log(f"  接口快照已按最新赔率重写（{n} 场）：{snapshot_path}")
    return saved
