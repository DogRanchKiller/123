"""
output/report.py  v1.1.0（输出层 1.1.0 的一部分）
预测报告：对未开赛场次，只展示主预测模型（version.PRIMARY_MODEL）的首次预测，
给出胜平负概率、倾向与双选、信心档（附历史命中率）、最可能比分、大 2.5 球概率，市场赔率作参考。
报告写入 reports/预测_YYYY-MM-DD.csv（utf-8-sig，Excel 可直接打开）。
修改此文件后请同步更新 version.py 中 "output" 的版本号。
"""
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

LAYER_VERSION = "1.1.0"

REPORT_DIR = "reports"
_BJ = ZoneInfo("Asia/Shanghai")
_LABEL = {"home_win": "主胜", "draw": "平", "away_win": "客胜"}

# 信心档：按主模型最大概率分档。命中率来自 xG 版 DC 月度回测
# （2324–2526，E0/D1/SP1 共 3198 场）：首选=概率最高的一项，前二=概率最高的两项之一。
CONFIDENCE_TIERS = [
    # (下限, 档名, 首选命中, 前二命中)
    (0.60, "高", 0.73, 0.90),
    (0.45, "中", 0.52, 0.76),
    (0.00, "低", 0.41, 0.71),
]


def confidence_tier(p_max: float) -> tuple[str, float, float]:
    """按最大概率返回 (档名, 历史首选命中率, 历史前二命中率)。"""
    for lo, name, hit1, hit2 in CONFIDENCE_TIERS:
        if p_max >= lo:
            return name, hit1, hit2
    raise ValueError(p_max)


def _double_label(top2: list[str]) -> str:
    s = set(top2)
    if s == {"home_win", "away_win"}:
        return "不平局"
    return "或".join(_LABEL[k] for k in ("home_win", "draw", "away_win") if k in s)


def build_report(conn: sqlite3.Connection, league_names: dict[str, str],
                 model_name: str, model_ver: str, now: datetime) -> pd.DataFrame:
    """未开赛场次的主模型预测报告，按开球时间排序。"""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='predictions'").fetchone():
        return pd.DataFrame()   # 新库尚未保存过任何预测
    rows = conn.execute(
        """SELECT f.match_id, f.league, f.match_date, f.kickoff_utc,
                  f.home_team, f.away_team, f.avg_h, f.avg_d, f.avg_a,
                  p.p_home_win, p.p_draw, p.p_away_win, p.extra_markets, p.generated_at
           FROM fixtures f JOIN predictions p ON p.match_id = f.match_id
           WHERE p.model_name = ? AND p.model_ver = ?
           ORDER BY p.generated_at""",
        (model_name, model_ver),
    ).fetchall()

    today = now.date().isoformat()
    seen, out = set(), []
    for (mid, lg, mdate, kickoff, home, away, oh, od, oa,
         ph, pd_, pa, extra, _) in rows:
        if mid in seen:      # 只用首次预测
            continue
        seen.add(mid)
        if kickoff:
            ko = datetime.fromisoformat(kickoff)
            if ko <= now:
                continue
            ko_txt = ko.astimezone(_BJ).strftime("%m-%d %H:%M")
        else:
            if mdate < today:
                continue
            ko_txt = mdate[5:]

        probs = {"home_win": ph, "draw": pd_, "away_win": pa}
        order = sorted(probs, key=probs.get, reverse=True)
        tier, hit1, hit2 = confidence_tier(probs[order[0]])
        ex = json.loads(extra) if extra else {}
        scores = " ".join(f"{s['score']}({s['prob']:.0%})"
                          for s in ex.get("top5_scores", [])[:3])
        mkt = ""
        if oh and od and oa:
            inv = [1 / oh, 1 / od, 1 / oa]
            mkt = "/".join(f"{x / sum(inv):.0%}" for x in inv)

        out.append({
            "联赛": league_names.get(lg, lg),
            "开球(北京)": ko_txt,
            "主队": home,
            "客队": away,
            "主胜": f"{ph:.0%}",
            "平": f"{pd_:.0%}",
            "客胜": f"{pa:.0%}",
            "倾向": _LABEL[order[0]],
            "双选": _double_label(order[:2]),
            "信心": tier,
            "历史命中(首选/双选)": f"{hit1:.0%}/{hit2:.0%}",
            "最可能比分": scores,
            "大2.5球": f"{ex['over_2.5']:.0%}" if "over_2.5" in ex else "",
            "市场 主/平/客": mkt,
            "模型": f"{model_name} {model_ver}",
            "_kickoff": kickoff or mdate,
        })
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("_kickoff").drop(columns="_kickoff") \
        .reset_index(drop=True)


def write_report(df: pd.DataFrame, now: datetime) -> str:
    """写入 reports/预测_YYYY-MM-DD.csv（同日重跑覆盖报告文件；预测记录本身不受影响），返回路径。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"预测_{now.astimezone(_BJ):%Y-%m-%d}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def format_row(r: pd.Series) -> str:
    """控制台一行展示。"""
    return (f"  [{r['联赛']}] {r['开球(北京)']} {r['主队']} vs {r['客队']}  "
            f"主{r['主胜']} 平{r['平']} 客{r['客胜']}  "
            f"倾向 {r['倾向']}（双选 {r['双选']}）  信心 {r['信心']}"
            f"[{r['历史命中(首选/双选)']}]  比分 {r['最可能比分']}  "
            f"大2.5 {r['大2.5球']}  | 市场 {r['市场 主/平/客']}")
