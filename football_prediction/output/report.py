"""
output/report.py  v1.2.0（输出层的一部分）
预测报告：对未开赛场次，按判断流程（output/analysis.py）用【最新】赔率现算，
给出胜平负概率（市场为底）、倾向与双选、信心档（附历史命中率）、预期进球、最可能比分、
大 2.5 / 双方进球 / 亚盘、自研模型对照、盘口变动、风险提示。
报告是"当前看法"，随赔率更新；存档的预测记录（review 层）只保留首次，二者互不影响。
报告写入 reports/预测_YYYY-MM-DD.csv（utf-8-sig，Excel 可直接打开）。
v1.2.0: 改为市场为底的判断流程；信心档按市场概率重标定；新增亚盘、盘口变动、风险、自研对照。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from football_prediction.output.analysis import (   # noqa: F401  confidence_tier 供外部/测试使用
    confidence_tier, double_label as _double_label, MARKET_TIERS as CONFIDENCE_TIERS,
)
from football_prediction.output.pipeline import ModelCache, analyse_match, fixture_odds

LAYER_VERSION = "1.2.0"

REPORT_DIR = "reports"
_BJ = ZoneInfo("Asia/Shanghai")


def upcoming_fixtures(conn: sqlite3.Connection, leagues, now: datetime) -> list[dict]:
    """未开球的赛程行（dict），按开球时间排序；无开球时间的按日期判断。"""
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM fixtures ORDER BY COALESCE(kickoff_utc, match_date)")]
    finally:
        conn.row_factory = None
    today, out = now.date().isoformat(), []
    for r in rows:
        if r["league"] not in leagues:
            continue
        if r["kickoff_utc"]:
            if datetime.fromisoformat(r["kickoff_utc"]) <= now:
                continue
        elif r["match_date"] < today:
            continue
        out.append(r)
    return out


def _pct(x) -> str:
    return "" if x is None else f"{x:.0%}"


def report_row(r: dict, a: dict, league_names: dict[str, str]) -> dict:
    """一场的判断结果 -> 报告一行"""
    if r.get("kickoff_utc"):
        ko = datetime.fromisoformat(r["kickoff_utc"]).astimezone(_BJ).strftime("%m-%d %H:%M")
    else:
        ko = r["match_date"][5:]
    mk, ah, md = a["markets"], a["ah"], a["models"]
    ah_txt = ""
    if ah:
        ah_txt = f"主{ah['line']:+.2f} 赢盘{ah['fair']:.0%}"
        if ah["outcome"]["push"] > 0.005:
            ah_txt += f" 走{ah['outcome']['push']:.0%}"
    ph, pdraw, pa = a["p1x2"]
    return {
        "联赛": league_names.get(r["league"], r["league"]),
        "开球(北京)": ko,
        "主队": r["home_team"],
        "客队": r["away_team"],
        "主胜": _pct(ph), "平": _pct(pdraw), "客胜": _pct(pa),
        "概率来源": a["p_src"],
        "倾向": a["lean"],
        "双选": a["double"],
        "信心": a["tier"],
        "历史命中(首选/双选)": f"{a['hit1']:.0%}/{a['hit2']:.0%}",
        "预期进球": f"{mk['exp_home_goals']:.1f}-{mk['exp_away_goals']:.1f}",
        "最可能比分": " ".join(f"{s['score']}({s['prob']:.0%})" for s in mk["top5_scores"][:3]),
        "大2.5球": _pct(mk["over_2.5"]),
        "双方进球": _pct(mk["btts_yes"]),
        "亚盘": ah_txt,
        "自研 主/平/客": "  ".join(f"{k} " + "/".join(f"{x:.0%}" for x in md[k])
                                for k in ("dc_xg", "blend") if k in md),
        "盘口变动": a["move"],
        "提示": "；".join(a["hints"] + a["risks"]),
        "比分来源": a["source"],
        "_kickoff": r.get("kickoff_utc") or r["match_date"],
    }


def build_report(conn: sqlite3.Connection, league_names: dict[str, str], now: datetime,
                 cache: ModelCache | None = None) -> pd.DataFrame:
    """未开赛场次的预测报告（按最新赔率现算），按开球时间排序。"""
    cache = cache or ModelCache(conn, now.date().isoformat())
    out = []
    for r in upcoming_fixtures(conn, league_names, now):
        a = analyse_match(conn, cache, r["league"], r["home_team"], r["away_team"],
                          fixture_odds(r), r["match_id"])
        out.append(report_row(r, a, league_names))
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("_kickoff", kind="stable").drop(columns="_kickoff") \
        .reset_index(drop=True)


def write_report(df: pd.DataFrame, now: datetime) -> str:
    """写入 reports/预测_YYYY-MM-DD.csv（同日重跑覆盖报告文件；预测记录本身不受影响），返回路径。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"预测_{now.astimezone(_BJ):%Y-%m-%d}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def format_row(r: pd.Series) -> str:
    """控制台展示：第一行结论，第二行比分盘口，有提示时第三行。"""
    s = (f"  [{r['联赛']}] {r['开球(北京)']} {r['主队']} vs {r['客队']}  "
         f"主{r['主胜']} 平{r['平']} 客{r['客胜']}（{r['概率来源']}）  "
         f"倾向 {r['倾向']}（双选 {r['双选']}）  信心 {r['信心']}[{r['历史命中(首选/双选)']}]\n"
         f"      预期进球 {r['预期进球']}  比分 {r['最可能比分']}  大2.5 {r['大2.5球']}  "
         f"双方进球 {r['双方进球']}  {r['亚盘']}  | 自研 {r['自研 主/平/客']}")
    if r["盘口变动"] and r["盘口变动"] != "平稳":
        s += f"\n      盘口变动：{r['盘口变动']}"
    if r["提示"]:
        s += f"\n      提示：{r['提示']}"
    return s
