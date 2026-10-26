"""
football_prediction/explain.py  v1.6.0（输出层的一部分）
单场判断说明：按判断流程逐步列出依据。
    python -m football_prediction.explain 英超 Arsenal Chelsea
    python -m football_prediction.explain E0 Arsenal Chelsea --odds 1.9 3.6 4.2 --ou 1.85 2.0 --ah -0.5 1.95 1.95
赔率与报告相同（services.latest_odds）；取数与判断在 services/match_analysis.explain_inputs，本文件只排版。
24 小时内有 ≥3 家的多家中位数时用它，否则用赛程表（fixtures）快照；
不在赛程表里的比赛可用 --odds/--ou/--ah 手动输入（欧赔）。
只读数据库，不保存任何预测。
v1.4.0: 赔率来源改用 latest_odds（多家中位数优先），[1] 写明来源与抓取时间。
v1.5.0: 亚盘为主：[2] 亚盘（数字线、五种结算、等效赢盘、该线水位去水、dc_xg 同线、线与水位轨迹），
        结论先写亚盘选择与亚盘信心，再写胜平负。
v1.6.0: 结论加亚盘稳妥线（赢盘 ≥ 65% 的最近一条线）与重点标记（胜平负市场档为高）。
"""
import argparse
import difflib
import sqlite3
import sys
from datetime import datetime, timezone

from football_prediction.data.loader import init_db
from football_prediction.output.analysis import SAFE_TARGET, ah_pick_text, ah_text, safe_text
from football_prediction.services import DB_PATH, LEAGUES, explain_inputs

LAYER_VERSION = "1.6.0"


def _league(s: str) -> str:
    for code, name in LEAGUES.items():
        if s in (code, name):
            return code
    sys.exit(f"未知联赛 {s}；可用：" + "、".join(f"{c}/{n}" for c, n in LEAGUES.items()))


def _team(conn: sqlite3.Connection, league: str, s: str) -> str:
    teams = sorted({r[0] for r in conn.execute(
        "SELECT home_team FROM matches WHERE league=? UNION SELECT home_team FROM fixtures "
        "WHERE league=?", (league, league))})
    if s in teams:
        return s
    low = {t.lower(): t for t in teams}
    hits = [t for k, t in low.items() if s.lower() in k]
    if len(hits) == 1:
        return hits[0]
    near = hits or difflib.get_close_matches(s, teams, n=5, cutoff=0.5)
    sys.exit(f"找不到球队 {s}" + (f"；是否指：{'、'.join(near)}" if near else ""))


def explain(conn, league, home, away, manual: dict | None = None,
            now: datetime | None = None) -> str:
    """返回多行说明文本"""
    now = now or datetime.now(timezone.utc)
    fx, odds, src, a = explain_inputs(conn, league, home, away, manual, now)

    L = [f"{LEAGUES[league]}  {home} vs {away}" + (f"  开球(UTC) {fx['kickoff_utc']}" if fx else "")]
    L.append(f"\n[1] 赔率来源：{src}")
    if odds:
        o = odds
        if o.get("avg_h"):
            L.append(f"    胜平负 {o['avg_h']} / {o.get('avg_d')} / {o.get('avg_a')}")
        if o.get("avg_over25"):
            L.append(f"    大小2.5 {o['avg_over25']} / {o.get('avg_under25')}")
        if o.get("ah_line") is not None:
            L.append(f"    亚盘 主{o['ah_line']:+.2f}  {o.get('avg_ahh')} / {o.get('avg_aha')}")
    ah, out, mk, fit = a["ah"], a["ah"]["outcome"], a["markets"], a["fit"]
    L.append(f"\n[2] 亚盘（{ah['line_src']}，比分来源 {a['source']}）：{ah_text(ah['line'], out)}")
    L.append(f"    主队方向五种结算：赢 {out['win']:.1%}  赢半 {out['half_win']:.1%}  走 {out['push']:.1%}  "
             f"输半 {out['half_lose']:.1%}  输 {out['lose']:.1%}")
    L.append(f"    等效赢盘（不计走盘）主 {ah['fair']:.1%} / 客 {1 - ah['fair']:.1%}" +
             (f"；该线水位去水后主 {ah['market_fair']:.1%}" if ah["market_fair"] is not None else "") +
             f"；dc_xg 同线主 {ah['self_fair']:.1%}")
    L.append(f"    亚盘变动：{a['ah_move'] or '暂无（只有一个阶段的亚盘）'}")
    p = a["p1x2"]
    L.append(f"\n[3] 胜平负（{a['p_src']}）：主 {p[0]:.1%}  平 {p[1]:.1%}  客 {p[2]:.1%}")
    L.append(f"\n[4] 比分分布（{a['source']}）" +
             (f"：用 {'+'.join(fit['used'])} 反推，拟合误差 {fit['rmse']:.3f}" if fit else ""))
    L.append(f"    预期进球 {mk['exp_home_goals']:.2f} - {mk['exp_away_goals']:.2f}   "
             f"大2.5 {mk['over_2.5']:.1%}  大1.5 {mk['over_1.5']:.1%}  大3.5 {mk['over_3.5']:.1%}  "
             f"双方进球 {mk['btts_yes']:.1%}")
    L.append("    比分 " + "  ".join(f"{s['score']} {s['prob']:.1%}" for s in mk["top5_scores"]))
    L.append("\n[5] 自研模型对照（主/平/客）：")
    for k, q in a["models"].items():
        L.append(f"    {k:<7}{q[0]:.1%} / {q[1]:.1%} / {q[2]:.1%}")
    L += [f"    ⚠ {h}" for h in a["hints"]] or ["    与市场无明显分歧"]
    L.append(f"\n[6] 胜平负盘口变动：{a['move'] or '只有一次快照，暂无变动信息'}")
    L.append("\n[7] 风险：" + ("；".join(a["risks"]) if a["risks"] else "无"))
    L.append(f"\n[8] 结论：亚盘选 {ah_pick_text(ah)}，亚盘信心 {ah['tier']}" +
             (f"（历史同档命中 {ah['hit']:.0%}，不含走盘）" if ah["hit"] is not None else "（无市场亚盘线，不分档）"))
    if ah.get("safe_line") is not None:
        L.append(f"    亚盘稳妥线：{safe_text(ah)}（赢盘 ≥ {SAFE_TARGET:.0%} 的最近一条线，线放宽了，命中高不代表判断更准）")
    L.append(f"    胜平负：倾向 {a['lean']}，双选 {a['double']}，信心 {a['tier']}"
             f"（历史同档首选命中 {a['hit1']:.0%}，双选命中 {a['hit2']:.0%}）")
    if a.get("est1") is not None:
        L.append(f"    本场命中估计（Shin 去水概率）：首选 {a['est1']:.0%}，双选 {a['est2']:.0%}")
    if a.get("highlight"):
        L.append("    ★ 重点：胜平负市场档为高（历史同档首选命中约 72%）；只表示胜平负把握高，"
                 "这类场次在市场亚盘线上的命中仍约 52–55%，亚盘看稳妥线")
    L.append("    概率是估计，足球结果随机性大；即使高信心档，历史上也约 1/4 不中。")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="单场判断说明")
    ap.add_argument("league")
    ap.add_argument("home")
    ap.add_argument("away")
    ap.add_argument("--odds", nargs=3, type=float, metavar=("主", "平", "客"))
    ap.add_argument("--ou", nargs=2, type=float, metavar=("大2.5", "小2.5"))
    ap.add_argument("--ah", nargs=3, type=float, metavar=("主队让球线", "主水", "客水"))
    a = ap.parse_args(argv)
    conn = init_db(DB_PATH)
    lg = _league(a.league)
    home, away = _team(conn, lg, a.home), _team(conn, lg, a.away)
    manual = None
    if a.odds or a.ou or a.ah:
        manual = {}
        if a.odds:
            manual.update(zip(("avg_h", "avg_d", "avg_a"), a.odds))
        if a.ou:
            manual.update(zip(("avg_over25", "avg_under25"), a.ou))
        if a.ah:
            manual.update(zip(("ah_line", "avg_ahh", "avg_aha"), a.ah))
    print(explain(conn, lg, home, away, manual))
    conn.close()


if __name__ == "__main__":
    main()
