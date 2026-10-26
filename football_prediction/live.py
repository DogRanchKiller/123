"""
football_prediction/live.py  v1.10.1
实盘预测闭环：更新数据（含赔率快照）→ 赛后评分 → 对未开赛场次存档预测 → 预测报告 → 实盘成绩单。
每轮比赛前后各跑一次即可（开赛前多跑几次可记录盘口变动）：
    python -m football_prediction.live
单场说明：python -m football_prediction.explain 英超 主队 客队
规则：
- 只对尚未开球的比赛预测，预测时间必定早于开球时间（无未来信息）。
- 每场每个模型版本只保存首次预测，之后重跑不会覆盖或追加，避免事后挑选。
- 同时保存当时的市场平均赔率（去抽水）作为基准 market_avg，赛后同场对比。
- 报告按最新赔率现算（当前看法）；存档只认首次预测，二者互不影响。
编排在 services/live_round.py（每日一轮，另写给接口读的快照 reports/latest_round.json）与
services/near_round.py（--near）；本文件只做参数和打印。
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
v1.10.0: 成绩单加亚盘三列（review 1.6.0）：按存档时的市场亚盘线评五种结算 log loss 与赢盘命中（不含走盘）；
        报告与 explain 改为亚盘优先（output 1.5.0）。
v1.10.1: 一轮用 round_clock 计时，存档前（拟合之后）再取时刻，已开球的不存档（之前用轮开头的 now，
        临场档抓阵容和赔率二十多分钟后仍存了开球后的 lineup_t1）；OddsPortal fetched_at 记每组抓回时刻、
        抓回时已开球的不入库（data 1.8.0）；成绩单不计开球后才存的旧行（review 1.7.0）。概率算法不变。
"""
import argparse
from datetime import datetime, timezone

from football_prediction import version
from football_prediction.data import fotmob
from football_prediction.data.loader import init_db
from football_prediction.output.report import format_row
from football_prediction.services import DB_PATH, LEAGUES, T1_HOURS, run_near, run_round

__all__ = ["LEAGUES", "main"]


def _print_scorecard(rep) -> None:
    print(f"  {'模型':<16}{'版本':<8}{'场数':>5}{'LogLoss':>9}{'Brier':>8}{'命中率':>7}"
          f"{'同场':>6}{'差值':>9}{'SE':>8}{'大小2.5':>9}{'比分':>8}"
          f"{'亚盘场':>7}{'亚盘LL':>8}{'赢盘命中':>9}")
    for _, r in rep.iterrows():
        print(f"  {r['model_name']:<16}{r['model_ver']:<8}{r['matches']:>5}"
              f"{r['log_loss']:>9.4f}{r['brier']:>8.4f}{r['hit_rate']:>7.1%}"
              f"{r['paired_n']:>6}{r['diff_vs_base']:>+9.4f}{r['se']:>8.4f}"
              f"{r['ou25_ll']:>9.4f}{r['score_ll']:>8.4f}"
              f"{r['ah_n']:>7}{r['ah_ll']:>8.4f}{r['ah_hit']:>9.1%}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="实盘预测闭环")
    ap.add_argument("--near", action="store_true",
                    help=f"只跑临场档：开球前 {T1_HOURS} 小时内的多家赔率 + 阵容 → *_t1 存档")
    ns = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    print(f"系统版本: {version.SYSTEM_VERSION}  当前时间(UTC): {now:%Y-%m-%d %H:%M}")
    conn = init_db(DB_PATH)
    fotmob.attach(conn)
    if ns.near:
        print("\n>>> 临场档（T1）...")
        print(f"  新保存 {run_near(conn, now)} 条临场预测")
        conn.close()
        return

    out = run_round(conn, now, DB_PATH)
    p_name, p_ver = out["primary"]
    print("\n>>> [4] 预测报告（最新赔率；胜平负=市场去水，比分=市场隐含，自研模型作对照；"
          "信心档后为历史命中率 首选/双选）...")
    rpt = out["report"]
    if rpt.empty:
        print("  暂无未开赛场次。")
    else:
        for _, r in rpt.iterrows():
            print(format_row(r))
        print(f"  报告已写入 {out['report_path']}")
        print("  概率是估计，足球结果随机性大：即使'高'信心档，历史上也约有 1/4 不中。")
    print(f"  接口快照已写入 {out['snapshot_path']}")

    print("\n>>> [5] 实盘成绩单（同场对比市场，差值负=优于市场；|差值| < 2×SE 视为无显著差异；"
          "大小2.5/比分/亚盘为对应 log loss，亚盘按存档时的市场线）...")
    rep = out["scorecard"]
    if rep.empty:
        print("  暂无已评分的实盘预测，比赛结束、数据源更新后再运行即可。")
    else:
        _print_scorecard(rep)
        print(f"\n>>> [6] 主模型替换检查（主模型 {p_name} {p_ver}；"
              f"规则：同场 ≥ {version.PROMOTE_MIN_N} 场且 差值+2×SE < 0）...")
        for _, r in out["promotion"].iterrows():
            print(f"  {r['model_name']:<16}{r['model_ver']:<8} 对主模型 {r['diff']:+.4f}±{r['se']:.4f}"
                  f"  → {r['verdict']}")
        hz = out["horizon"]
        if not hz.empty:
            print("\n>>> [7] 临场档（开球前约 1 小时）对赛前档，同场 log loss 差（负=临场更好）...")
            for _, r in hz.iterrows():
                print(f"  {r['model_name']:<20}{r['model_ver']:<8} 对 {r['base']:<16}"
                      f"{r['paired_n']:>5} 场 {r['diff']:+.4f}±{r['se']:.4f}")
    conn.close()


if __name__ == "__main__":
    main()
