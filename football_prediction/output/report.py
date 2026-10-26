"""
output/report.py  v1.6.0（输出层的一部分）
预测报告：对未开赛场次，按判断流程（output/analysis.py）用【最新】赔率现算，
给出胜平负概率（市场为底）、倾向与双选、信心档（附历史命中率）、预期进球、最可能比分、
大 2.5 / 双方进球 / 亚盘、自研模型对照、盘口变动、风险提示。
报告是"当前看法"，随赔率更新；存档的预测记录（review 层）只保留首次，二者互不影响。
报告写入 reports/预测_YYYY-MM-DD.csv（utf-8-sig，Excel 可直接打开）。
v1.2.0: 改为市场为底的判断流程；信心档按市场概率重标定；新增亚盘、盘口变动、风险、自研对照。
v1.3.0: 信心档按 Shin 概率、5 联赛重标定；新增列「本场估计(首选/双选)」（无赔率时为空）。
v1.4.0: 赔率改由 pipeline.latest_odds 选（多家中位数优先），新增列「赔率来源」。
v1.5.0: 亚盘为主：主客队之后依次为「亚盘」（数字线 + 赢 / 赢半 / 走 / 输半 / 输）、「亚盘选择」、
        「亚盘信心」（档[历史命中]）、「亚盘变动」（线与水位轨迹）；控制台第一行是亚盘。
v1.6.0: 新增列「亚盘稳妥」（选择方赢盘 ≥ 65% 的最近一条线）与「重点」（胜平负市场档为高时写「★」）。
拟合与取赔率的编排（原 build_report、pipeline）在 services/match_analysis.py；本文件只管行格式与写文件。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from football_prediction.output.analysis import (   # noqa: F401  confidence_tier 供外部/测试使用
    confidence_tier, double_label as _double_label, MARKET_TIERS as CONFIDENCE_TIERS,
    ah_pick_text, ah_text, safe_text,
)

LAYER_VERSION = "1.6.0"

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
    ph, pdraw, pa = a["p1x2"]
    return {
        "联赛": league_names.get(r["league"], r["league"]),
        "开球(北京)": ko,
        "主队": r["home_team"],
        "客队": r["away_team"],
        "亚盘": ah_text(ah["line"], ah["outcome"])
                + ("" if ah["line_src"] == "市场线" else f"（{ah['line_src']}）"),
        "亚盘选择": ah_pick_text(ah),
        "亚盘信心": ah["tier"] if ah["hit"] is None else f"{ah['tier']}[{ah['hit']:.0%}]",
        "亚盘稳妥": safe_text(ah),
        "亚盘变动": a["ah_move"],
        "主胜": _pct(ph), "平": _pct(pdraw), "客胜": _pct(pa),
        "概率来源": a["p_src"],
        "倾向": a["lean"],
        "双选": a["double"],
        "信心": a["tier"],
        "重点": "★" if a["highlight"] else "",
        "历史命中(首选/双选)": f"{a['hit1']:.0%}/{a['hit2']:.0%}",
        "本场估计(首选/双选)": f"{a['est1']:.0%}/{a['est2']:.0%}" if a.get("est1") is not None else "",
        "预期进球": f"{mk['exp_home_goals']:.1f}-{mk['exp_away_goals']:.1f}",
        "最可能比分": " ".join(f"{s['score']}({s['prob']:.0%})" for s in mk["top5_scores"][:3]),
        "大2.5球": _pct(mk["over_2.5"]),
        "双方进球": _pct(mk["btts_yes"]),
        "自研 主/平/客": "  ".join(f"{k} " + "/".join(f"{x:.0%}" for x in md[k])
                                for k in ("dc_xg", "blend") if k in md),
        "盘口变动": a["move"],
        "提示": "；".join(a["hints"] + a["risks"]),
        "比分来源": a["source"],
        "_kickoff": r.get("kickoff_utc") or r["match_date"],
    }


def write_report(df: pd.DataFrame, now: datetime) -> str:
    """写入 reports/预测_YYYY-MM-DD.csv（同日重跑覆盖报告文件；预测记录本身不受影响），返回路径。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"预测_{now.astimezone(_BJ):%Y-%m-%d}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def format_row(r: pd.Series) -> str:
    """控制台展示：第一行亚盘，第二行胜平负，第三行比分盘口，之后是变动与提示。"""
    s = (f"  [{r['联赛']}] {r['开球(北京)']} {r['主队']} vs {r['客队']}  "
         f"{r['亚盘']}  → 选 {r['亚盘选择']}  亚盘信心 {r['亚盘信心']}\n"
         f"      主{r['主胜']} 平{r['平']} 客{r['客胜']}（{r['概率来源']}）  "
         f"倾向 {r['倾向']}（双选 {r['双选']}）  信心 {r['信心']}[{r['历史命中(首选/双选)']}]"
         + (f" 本场[{r['本场估计(首选/双选)']}]" if r.get("本场估计(首选/双选)") else "") + "\n"
         f"      预期进球 {r['预期进球']}  比分 {r['最可能比分']}  大2.5 {r['大2.5球']}  "
         f"双方进球 {r['双方进球']}  | 自研 {r['自研 主/平/客']}")
    if r["亚盘变动"]:
        s += f"\n      亚盘变动：{r['亚盘变动']}"
    if r["盘口变动"] and r["盘口变动"] != "平稳":
        s += f"\n      盘口变动：{r['盘口变动']}"
    if r.get("赔率来源", "").startswith("多家"):
        s += f"\n      赔率：{r['赔率来源']}"
    if r["提示"]:
        s += f"\n      提示：{r['提示']}"
    return s
