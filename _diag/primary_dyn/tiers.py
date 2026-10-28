"""主模型换成 dc_dyn（用户 2026-10-28 决定）：按 dc_dyn 逐场赛前 λ 重标定判断流程的各档。
dc_dyn λ 用开发线 dynamic.run_league（与 model_dc/dynamic_dc.run_filter 逐场一致，W=0 q=0.016 c=1.0）；
rho 用 dev_model/rows_{lg}.csv 里 dc_market 同月拟合值（实盘 dc_dyn 自拟 rho，差别只在低比分修正）。
标定 2324–2526，留出 2627（与 _diag/fallback/tiers.py 同口径）。football.db 只读备份到内存，不写库。
  一、胜平负信心档：首选概率 ≥0.60 高 / ≥0.45 中 / 其余低，各档首选与前二命中；同场市场 Shin 档作对照。
  二、亚盘：dc_dyn 在市场线上的选择方等效赢盘概率分档（≥0.60 / ≥0.55 / 其余），选择方命中（赢 1、赢半 0.75、
      输半 0.25、输 0，走盘不计）；稳妥线（从市场线向选择方每次退 0.25，赢盘概率 ≥0.65）的实际命中。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/primary_dyn/tiers.py > _diag/primary_dyn/tiers.txt
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "dev_model"))
from dynamic import load, run_league   # noqa: E402  同开发线脚本
from football_prediction.model_market.devig import shin   # noqa: E402
from football_prediction.model_market.implied import dc_matrix   # noqa: E402
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf   # noqa: E402
from football_prediction.review.store import ah_settle   # noqa: E402

DEV = Path(__file__).parent.parent / "dev_model"
LGS = ["E0", "D1", "SP1", "I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
BEST = {"w": 0.0, "q": 0.016, "c": 1.0}
CUTS = [(0.60, "高"), (0.45, "中"), (0.00, "低")]
AH_CUTS = [(0.60, "高"), (0.55, "中"), (0.00, "低")]
SAFE, STEPS = 0.65, 12
HIT = {"win": 1.0, "half_win": 0.75, "half_lose": 0.25, "lose": 0.0}
KEYS = ("home_win", "draw", "away_win")


def actual(hg: int, ag: int) -> int:
    return 0 if hg > ag else 1 if hg == ag else 2


def per_match(r) -> dict:
    m = dc_matrix(r.v2_lh, r.v2_la, r.dc_rho)
    p = np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()])
    p = p / p.sum()
    y = actual(int(r.hg), int(r.ag))
    order = np.argsort(-p)
    ps = sorted(shin([r.avg_h, r.avg_d, r.avg_a]), reverse=True) if r.avg_h == r.avg_h else [np.nan]
    mo = np.argsort(-np.array([1 / r.avg_h, 1 / r.avg_d, 1 / r.avg_a])) if r.avg_h == r.avg_h else None
    out = {"season": r.season, "pmax": p.max(), "hit1": order[0] == y, "hit2": y in order[:2],
           "m_pmax": ps[0], "m_hit1": mo is not None and mo[0] == y,
           "m_hit2": mo is not None and y in mo[:2],
           "ah_p": np.nan, "ah_hit": np.nan, "safe_hit": np.nan, "safe_p": np.nan, "safe_steps": np.nan}
    if r.ah_line != r.ah_line:
        return out
    pmf, margin = margin_pmf(m), int(r.hg) - int(r.ag)
    fair = ah_fair_prob(ah_outcome(pmf, float(r.ah_line)))
    home = fair >= 0.5
    out["ah_p"] = fair if home else 1 - fair
    k = ah_settle(margin, float(r.ah_line))
    if k != "push":
        out["ah_hit"] = HIT[k] if home else 1 - HIT[k]
    step = 0.25 if home else -0.25
    for s in range(STEPS + 1):
        x = round(float(r.ah_line) + s * step, 2)
        f = ah_fair_prob(ah_outcome(pmf, x))
        pc = f if home else 1 - f
        if pc >= SAFE:
            k = ah_settle(margin, x)
            out["safe_p"], out["safe_steps"] = pc, s
            if k != "push":
                out["safe_hit"] = HIT[k] if home else 1 - HIT[k]
            break
    return out


def tier_lines(d: pd.DataFrame, pcol: str, h1: str, h2: str | None, cuts) -> list[str]:
    out, hi = [], np.inf
    for lo, name in cuts:
        m = (d[pcol] >= lo) & (d[pcol] < hi)
        if m.sum():
            s = f"    {name} n={m.sum():>5} ({m.mean():.0%})  均概率 {d[pcol][m].mean():.3f}  首选 {d[h1][m].mean():.3f}"
            if h2:
                s += f"  前二 {d[h2][m].mean():.3f}"
            out.append(s)
        hi = lo
    return out


def main() -> None:
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    lam = pd.concat([run_league(load(conn, lg), **BEST) for lg in LGS], ignore_index=True)
    rows = pd.concat([pd.read_csv(DEV / f"rows_{lg}.csv", dtype={"season": str}) for lg in LGS],
                     ignore_index=True).merge(lam, on="match_id")
    d = pd.DataFrame([per_match(r) for r in rows.itertuples()])
    text = [f"共 {len(d)} 场（11 联赛 2324–2627，有赛前赔率）；dc_dyn rho 用 dc_market 同月值"]
    for name, m in (("标定 2324–2526", d.season != "2627"), ("留出 2627", d.season == "2627")):
        x = d[m]
        text.append(f"\n== {name}（n={len(x)}）==")
        text.append("  一、胜平负信心档 dc_dyn（首选概率）")
        text += tier_lines(x, "pmax", "hit1", "hit2", CUTS)
        text.append("  对照：同场市场 Shin 最大概率")
        text += tier_lines(x.dropna(subset=["m_pmax"]), "m_pmax", "m_hit1", "m_hit2", CUTS)
        a = x.dropna(subset=["ah_p"])
        text.append(f"  二、亚盘 dc_dyn 市场线选择方（n={len(a)}，命中不含走盘）")
        text += tier_lines(a.dropna(subset=["ah_hit"]), "ah_p", "ah_hit", None, AH_CUTS)
        text.append(f"    全体选择方命中 {a.ah_hit.mean():.3f}")
        s = a.dropna(subset=["safe_p"])
        text.append(f"  稳妥线（≥{SAFE}）：有线 {len(s)} 场，均赢盘概率 {s.safe_p.mean():.3f}，"
                    f"实际命中 {s.safe_hit.mean():.3f}，平均退 {s.safe_steps.mean():.1f} 步")
    out = "\n".join(text)
    (Path(__file__).parent / "tiers.txt").write_text(out + "\n", encoding="utf-8")
    sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
