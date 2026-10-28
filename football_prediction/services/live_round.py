"""
services/live_round.py  实盘一轮（中间层）
更新数据（含赔率快照）→ 赛后评分 → 对未开赛场次存档预测 → 预测报告 → 实盘成绩单 → 替换检查，
并把这一轮算好的看法与成绩单写成快照（SNAPSHOT_PATH），给接口读，接口不再按请求拟合。
快照的读函数（read_current / read_match / read_scorecard）在 services/match_read.py；
临场档（near_round）有场次时用 refresh_snapshot 按开球前的多家赔率重写快照。
命令行入口 live.py 只做参数和打印；行为与版本说明见 live.py 的文件头（版本号登记为 "live"）。
规则：
- 只对尚未开球的比赛预测，预测时间必定早于开球时间（无未来信息）。
- 每场每个模型版本只保存首次预测，之后重跑不会覆盖或追加，避免事后挑选。
- 同时保存当时的市场平均赔率（去抽水）作为基准 market_avg，赛后同场对比。
- 报告与快照按最新赔率现算（当前看法）；存档只认首次预测，二者互不影响。
- 主模型 dc_dyn（live 2.0.0）：本轮看法的概率与比分都是 dc_dyn；赔率只给市场对照（market_probabilities、
  亚盘的 market_home_cover / implied_home_cover）与亚盘线。dc_dyn 存档另记存档时的赛程表赔率。
进度输出走 log 参数（默认 print），本文件不渲染表格。
"""
import json
import math
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

from football_prediction import version
from football_prediction.data import fotmob
from football_prediction.data.fixtures import load_fixtures
from football_prediction.data.loader import load_season, season_of
from football_prediction.data.understat import US_LEAGUES, load_xg
from football_prediction.model_blend.blend import MODEL_NAME as BLEND_NAME
from football_prediction.model_dc.dynamic_dc import DynamicDixonColesModel, DynamicShotsDixonColesModel
from football_prediction.model_dc.market_dc import MODEL_NAME as DC_MARKET_NAME
from football_prediction.model_market.devig import SHIN_NAME
from football_prediction.model_market.implied import MODEL_NAME as IMPLIED_NAME, implied_matrix
from football_prediction.output.analysis import devig, odds_dict, safe_text
from football_prediction.output.derive import derive_markets
from football_prediction.output.report import upcoming_fixtures, write_report
from football_prediction.review.scorecard import closing_report, horizon_report, live_report, promotion_check
from football_prediction.review.store import (
    has_prediction, pending_fotmob, reconcile_results, save_prediction, score_predictions, started,
)
from football_prediction.services.match_analysis import (
    FIXTURE_ODDS, ModelCache, analyse_upcoming, build_report, fixture_odds,
)

Log = Callable[[str], None]
DYN_NAME, DYN_SHOTS_NAME = DynamicDixonColesModel.MODEL_NAME, DynamicShotsDixonColesModel.MODEL_NAME

DB_PATH = "football.db"
LEAGUES = {"E0": "英超", "D1": "德甲", "SP1": "西甲", "I1": "意甲", "F1": "法甲",
           "E1": "英冠", "N1": "荷甲", "P1": "葡超", "SC0": "苏超", "B1": "比甲", "T1": "土超"}
MARKET_VER = "1.1.0"   # 市场基准算法版本（1/赔率 按比例去抽水），算法变化时才改
SNAPSHOT_PATH = os.path.join("reports", "latest_round.json")   # 本轮看法与成绩单，每轮覆盖
SNAPSHOT_SCHEMA = 2   # 2：加 closing（对收盘参照），成绩单行加 base（同档市场基准）
REPLACE_TRIES, REPLACE_WAIT = 5, 0.2   # 替换快照被拒绝时的重试次数与间隔（秒）
Clock = Callable[[], datetime]


def round_clock(start: datetime) -> Clock:
    """一轮的时钟：start 加上本轮已过去的秒数。一轮里抓数据、拟合可能要几十分钟，
    存档前用它判断是否已开球；测试传合成的 start，时间只走几秒。"""
    t0 = time.monotonic()
    return lambda: start + timedelta(seconds=time.monotonic() - t0)


def update_data(conn: sqlite3.Connection, today: str, db_path: str = DB_PATH,
                log: Log = print) -> None:
    """刷新当前赛季结果和未开赛赛程（同时追加赔率快照）；网络失败时沿用本地数据。"""
    season = season_of(today)
    for lg, name in LEAGUES.items():
        try:
            n = load_season(lg, season, conn, db_path)
            log(f"  [{name}] {season} 新增赛果 {n} 场")
        except Exception as e:
            log(f"  [{name}] {season} 下载失败（{type(e).__name__}），使用本地数据")
        if lg not in US_LEAGUES:   # understat 没有的联赛，xG 只靠下面的 FotMob 补
            continue
        # xG 依赖 matches 已有赛果，必须在 load_season 之后
        try:
            n, miss = load_xg(conn, lg, season)
            log(f"  [{name}] {season} 新增 xG {n} 场" + (f"（{miss} 场未对齐）" if miss else ""))
        except Exception as e:
            log(f"  [{name}] {season} xG 下载失败（{type(e).__name__}），xG 版对缺失场次用进球兜底")
    # understat 完赛数天仍缺的场次，用已抓的 FotMob 全队 xG 补（不联网）
    n = fotmob.backfill_xg(conn, date.fromisoformat(today))
    if n:
        log(f"  FotMob xG 补入 {n} 场（understat 缺）")
    try:
        n = load_fixtures(conn, list(LEAGUES))
        log(f"  未开赛赛程 {n} 场（赔率快照已追加）")
    except Exception as e:
        log(f"  赛程下载失败（{type(e).__name__}），使用上次缓存的赛程")
    # football-data 赛果常晚几天；FotMob 联赛页的完赛比分只用于先评分，不进 matches
    try:
        n = fotmob.collect_results(conn, list(LEAGUES), season)
        log(f"  FotMob 赛果 新增 {n} 场（只用于评分，football-data 到达后核对）")
    except Exception as e:
        log(f"  FotMob 赛果抓取失败（{type(e).__name__}），评分只用 football-data")


def score_round(conn: sqlite3.Connection, log: Log = print) -> int:
    """赛后评分：先按 football-data 核对用 FotMob 比分评过的行，再评新完赛的场次。返回本次评分条数。"""
    n, bad = reconcile_results(conn)
    if n:
        log(f"  football-data 赛果核对 {n} 条先用 FotMob 比分评过的预测，比分不一致 {len(bad)} 场"
            + ("（已按 football-data 重评）" if bad else ""))
    for b in bad:
        log(f"    {b['match_id']}: FotMob {b['fotmob']} → football-data {b['fd']}")
    scored = score_predictions(conn)
    log(f"  本次评分 {scored} 条")
    n = pending_fotmob(conn)
    if n:
        log(f"  其中 {n} 场暂用 FotMob 比分，等 football-data 核对")
    return scored


def markets_extra(m, kickoff) -> dict:
    """比分矩阵派生的各盘口 + 展平的比分矩阵（赛后评精确比分用）"""
    mk = derive_markets(m)
    extra = {k: v for k, v in mk.items() if k not in ("home_win", "draw", "away_win", "layer_ver")}
    extra["score_matrix"] = [round(float(x), 6) for x in m.ravel()]
    extra["kickoff_utc"] = kickoff
    return extra


def match_ident(r: dict) -> dict:
    """存档里记下对阵：fixtures 每次刷新整表替换，football-data 赛果到之前被换掉的场次靠它查对阵。"""
    return {"match": {"league": r["league"], "home": r["home_team"], "away": r["away_team"],
                      "match_date": r["match_date"]}}


def predict_upcoming(conn: sqlite3.Connection, now: datetime, cache: ModelCache | None = None,
                     log: Log = print, clock: Clock | None = None) -> int:
    """对未开球的比赛存档 DC / 射正 DC / xG DC / 市场版 DC / 动态 DC 两版 / Elo / blend / 市场 / 市场隐含，返回新保存条数。
    clock 是本轮时钟（默认从 now 起算）：每场拟合之后、存档之前再取一次时刻，已开球的跳过。"""
    clock = clock or round_clock(now)
    cache = cache or ModelCache(conn, now.date().isoformat())
    feat_ver = version.get("features")
    vers = {"dixon_coles": version.get("model_dc"), "dc_sot": version.get("model_sot"),
            "dc_xg": version.get("model_xg"), "elo": version.get("model_elo"),
            BLEND_NAME: version.get("model_blend"), DC_MARKET_NAME: version.get("model_dc_market"),
            DYN_NAME: version.get("model_dc_dyn"), DYN_SHOTS_NAME: version.get("model_dc_dyn")}
    saved = 0

    def save(mid, name, ver, p, extra):
        nonlocal saved
        if not has_prediction(conn, mid, name, ver) and \
                save_prediction(conn, mid, name, ver, feat_ver, p[0], p[1], p[2], extra, at=at):
            saved += 1

    for r in upcoming_fixtures(conn, LEAGUES, clock()):
        mid, lg, home, away, kickoff = (r["match_id"], r["league"], r["home_team"],
                                        r["away_team"], r["kickoff_utc"])
        lm, ident = cache.get(lg), match_ident(r)   # 首次取某联赛时拟合，可能耗时
        at = clock()
        if started({"kickoff_utc": kickoff}, at):
            log(f"  已开球，不存档：{home} vs {away}")
            continue
        for t in (home, away):
            if not lm.known(t):
                log(f"  ⚠ {t} 不在 {lg} 历史数据中，DC 用联赛均值兜底")

        for name, model in (("dixon_coles", lm.dc), ("dc_sot", lm.sot), ("dc_xg", lm.xg),
                            (DC_MARKET_NAME, lm.market), (DYN_NAME, lm.dyn), (DYN_SHOTS_NAME, lm.dyn_shots)):
            if has_prediction(conn, mid, name, vers[name]):
                continue
            m = model.score_matrix(home, away)
            mk = derive_markets(m)
            extra = markets_extra(m, kickoff) | ident
            if name == DYN_NAME:   # 主模型另记存档时的赛程表赔率：页面显示市场线，评分用本行亚盘线
                extra["odds"] = fixture_odds(r)
            save(mid, name, vers[name], (mk["home_win"], mk["draw"], mk["away_win"]), extra)

        inp = lm.inputs(home, away)
        save(mid, "elo", vers["elo"], inp["models"]["elo"], {"kickoff_utc": kickoff, **ident})
        save(mid, BLEND_NAME, vers[BLEND_NAME], inp["models"]["blend"], {"kickoff_utc": kickoff, **ident})

        saved += save_market(conn, mid, fixture_odds(r), inp["rho"], kickoff, feat_ver, info=ident, at=at)
    return saved


def save_market(conn: sqlite3.Connection, mid: str, odds: dict, rho: float, kickoff, feat_ver: str,
                suffix: str = "", info: dict | None = None, at: datetime | None = None) -> int:
    """市场基准 market_avg + 市场隐含（按比例去水 / Shin 去水）。suffix="_t1" 为临场存档。
    at 为生成时刻（默认当前 UTC），已开球时 save_prediction 不存。"""
    saved = 0

    def save(name, ver, p, extra):
        nonlocal saved
        if not has_prediction(conn, mid, name, ver) and save_prediction(
                conn, mid, name, ver, feat_ver, p[0], p[1], p[2], {**extra, **(info or {})}, at=at):
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
        extra = markets_extra(m, kickoff)
        extra.update(fit={k: fit[k] for k in ("lam_h", "lam_a", "rmse", "used")}, rho=rho,
                     odds={k: odds.get(k) for k in FIXTURE_ODDS})
        save(name + suffix, ver, (mk["home_win"], mk["draw"], mk["away_win"]), extra)
    return saved


def run_round(conn: sqlite3.Connection, now: datetime, db_path: str = DB_PATH,
              snapshot_path: str = SNAPSHOT_PATH, log: Log = print) -> dict:
    """实盘一轮。返回 report（DataFrame）、report_path、scorecard / closing / promotion / horizon（DataFrame 或 None）、
    primary（主模型名, 版本）；报告 CSV 只在有场次时写，快照每轮都写（没有场次时 matches 为空）。"""
    today, clock = now.date().isoformat(), round_clock(now)
    log("\n>>> [1] 更新数据 ...")
    update_data(conn, today, db_path, log)
    log("\n>>> [2] 赛后评分 ...")
    score_round(conn, log)
    log("\n>>> [3] 未开赛场次预测存档（所有模型，首次预测为准）...")
    cache = ModelCache(conn, today)
    log(f"  新保存 {predict_upcoming(conn, now, cache, log, clock)} 条预测")

    p_name, p_key = version.PRIMARY_MODEL
    primary = (p_name, version.get(p_key))
    analysed = analyse_upcoming(conn, LEAGUES, clock(), cache)   # 本轮期间开球的不进报告和快照
    report = build_report(conn, LEAGUES, now, analysed=analysed)
    rep = live_report(conn)
    out = {"report": report, "report_path": None if report.empty else write_report(report, now),
           "scorecard": rep, "primary": primary, "closing": None, "promotion": None, "horizon": None}
    if not rep.empty:
        out["closing"] = closing_report(conn)
        out["promotion"] = promotion_check(conn, primary, version.PROMOTE_MIN_N)
        out["horizon"] = horizon_report(conn)
    write_snapshot(snapshot_path, now, [match_view(r, a, src) for r, a, src in analysed],
                   scorecard_rows(rep), scorecard_rows(out["closing"]))
    out["snapshot_path"] = snapshot_path
    return out


def refresh_snapshot(conn: sqlite3.Connection, now: datetime, cache: ModelCache | None = None,
                     snapshot_path: str = SNAPSHOT_PATH, clock: Clock | None = None) -> int:
    """按最新赔率重算未开赛场次的本轮看法并重写快照（临场档用：开球前的多家赔率进网站）。
    不存档、不写报告 CSV、不评分；成绩单按库里现有评分重算。返回快照里的场次数。
    快照的生成时间记 now（本轮开始），场次按 clock 的当前时刻筛未开球的。"""
    analysed = analyse_upcoming(conn, LEAGUES, (clock or round_clock(now))(), cache)
    rep = live_report(conn)
    write_snapshot(snapshot_path, now, [match_view(r, a, src) for r, a, src in analysed],
                   scorecard_rows(rep), scorecard_rows(None if rep.empty else closing_report(conn)))
    return len(analysed)


def _num(x, nd: int = 4):
    """numpy / float → JSON 可写的 float；None、NaN、无穷 → None"""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def view_model(a: dict) -> tuple[str, str]:
    """本轮看法对应的模型（名, 版本）：主模型 dc_dyn，有没有赔率都是它（live 2.0.0）。"""
    name, key = version.PRIMARY_MODEL
    return name, version.get(key)


def match_view(r: dict, a: dict, odds_source: str) -> dict:
    """一场的本轮看法（JSON 可写，不含比分矩阵），字段取自判断结果 analyse()；亚盘在前。"""
    ah, mk = a["ah"], a["markets"]
    name, ver = view_model(a)
    recommended = bool(a["highlight"])
    note = None
    if recommended:
        note = f"胜平负高把握 · {a['lean']} {a['est1']:.0%}"
        note += f" · 亚盘稳妥 {safe_text(ah)}" if ah["safe_line"] is not None else ""
    return {
        "match_id": r["match_id"], "league": r["league"],
        "league_name": LEAGUES.get(r["league"], r["league"]),
        "home": r["home_team"], "away": r["away_team"],
        "kickoff_utc": r.get("kickoff_utc"), "match_date": r["match_date"],
        "model_name": name, "model_version": ver,
        "recommended": recommended,
        "recommendation_note": note,
        "odds_source": odds_source if a["market"] is not None else None,
        "asian": {
            "line": round(float(ah["line"]) + 0.0, 2),
            "line_source": "市场线" if ah["line_src"] == "市场线" else "公平线",
            "outcome": {k: _num(v) for k, v in ah["outcome"].items()},
            "side": ah["side"], "p_cover": _num(ah["p_cover"]), "tier": ah["tier"],
            "historical_hit": _num(ah["hit"]),
            "safe_line": None if ah["safe_line"] is None else round(ah["safe_line"] + 0.0, 2),
            "safe_cover": _num(ah["safe_cover"]), "self_home_cover": _num(ah["self_fair"]),
            "market_home_cover": _num(ah["market_fair"]),
            "implied_home_cover": _num(ah["implied_fair"]),
            "movement": a["ah_move"] or None,
        },
        "probabilities": [_num(x) for x in a["p1x2"]],
        "market_probabilities": None if a["market"] is None else [_num(x) for x in a["market"]],
        "probability_source": a["p_src"], "score_source": a["source"],
        "lean": a["lean"], "double": a["double"], "confidence": a["tier"],
        "historical_first_hit": _num(a["hit1"]), "historical_double_hit": _num(a["hit2"]),
        "estimated_first_hit": _num(a.get("est1")), "estimated_double_hit": _num(a.get("est2")),
        "expected_goals": [_num(mk["exp_home_goals"], 2), _num(mk["exp_away_goals"], 2)],
        "likely_scores": [{"score": s["score"], "prob": _num(s["prob"])} for s in mk["top5_scores"]],
        "over25": _num(mk["over_2.5"]), "btts": _num(mk["btts_yes"]),
        "self_models": {k: [_num(x) for x in v] for k, v in a["models"].items()},
        "movement": a["move"] or None,
        "hints": list(a["hints"]), "risks": list(a["risks"]),
    }


_INT_COLS = ("matches", "ah_n", "paired_n")
_STR_COLS = ("model_name", "model_ver", "base")


def scorecard_rows(rep) -> list[dict]:
    """live_report / closing_report 的行（JSON 可写；NaN → None），保持其排序。"""
    if rep is None or rep.empty:
        return []
    return [{k: str(v) if k in _STR_COLS
             else (int(v) if k in _INT_COLS and v == v else _num(v)) for k, v in r.items()}
            for r in rep.to_dict("records")]


def write_snapshot(path: str, now: datetime, matches: list[dict], scorecard: list[dict],
                   closing: list[dict] | None = None) -> None:
    """原子写入（先写临时文件再替换），接口读到的总是完整的一轮。closing 为对收盘参照的行。"""
    p_name, p_key = version.PRIMARY_MODEL
    data = {"schema": SNAPSHOT_SCHEMA, "generated_at": now.isoformat(),
            "system_version": version.SYSTEM_VERSION,
            "primary_model": {"name": p_name, "version": version.get(p_key)},
            "leagues": LEAGUES, "matches": matches, "scorecard": scorecard,
            "closing": closing or []}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows：接口正好在读旧快照时，替换会被拒绝
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_WAIT)
