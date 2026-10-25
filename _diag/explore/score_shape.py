"""比分分布形状（research.db，只读）：市场隐含比分矩阵的 rho 取固定值 vs 每场由盘口反推（第三个参数）。
现行 market_implied：λ主、λ客 两个参数拟合 1X2 + 大小 2.5 + 亚盘，rho 取联赛 DC 拟合值（实盘约 −0.02 ~ −0.08）。
评价：精确比分 / 1X2 / 大小 2.5 / 大小 1.5 / 大小 3.5 / 双方进球 的 log loss（后三项没有参与拟合）；
另列总进球数与 0-0、1-1 的预测频率 vs 实际，看形状偏在哪里。1213–2425 选参，2526 留出。
用法：PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/explore/score_shape.py > _diag/explore/score_shape.log
"""
import sqlite3
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from football_prediction.model_market.implied import MAX_GOALS, _implied, dc_matrix, fair_probs, fit_lambdas

DB = "research.db"
FROM = "2012-07-01"
HOLDOUT = "2526"
FIXED = (0.0, -0.05, -0.10)
RHO_MAX = 0.3
_G = np.arange(MAX_GOALS + 1)
_TOT = np.add.outer(_G, _G)


def _tau_ok(lh, la, rho) -> bool:
    return min(1 - lh * la * rho, 1 + lh * rho, 1 + la * rho, 1 - rho) > 0


def fit_free(odds: dict, start: dict) -> tuple[float, float, float]:
    """λ主、λ客、rho 三参数同时拟合（从固定 rho 的解出发）。"""
    fp = fair_probs(odds)

    def loss(x):
        lh, la = np.exp(np.clip(x[:2], -3, 2))
        rho = RHO_MAX * np.tanh(x[2])
        if not _tau_ok(lh, la, rho):
            return 1.0
        return sum((a - b) ** 2 for a, b in _implied(dc_matrix(lh, la, rho), fp))

    x0 = [np.log(start["lam_h"]), np.log(start["lam_a"]), np.arctanh(-0.05 / RHO_MAX)]
    r = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-11, "maxiter": 600})
    lh, la = np.exp(np.clip(r.x[:2], -3, 2))
    return float(lh), float(la), float(RHO_MAX * np.tanh(r.x[2]))


def metrics(m: np.ndarray, hg: int, ag: int) -> dict:
    hg, ag = min(hg, MAX_GOALS), min(ag, MAX_GOALS)
    res = 0 if hg > ag else 1 if hg == ag else 2
    p1x2 = [np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()]
    tot = hg + ag
    out = {"score": -np.log(m[hg, ag]), "1x2": -np.log(p1x2[res])}
    for line in (1.5, 2.5, 3.5):
        p = m[_TOT > line].sum()
        out[f"ou{line}"] = -np.log(p if tot > line else 1 - p)
    p = m[1:, 1:].sum()
    out["btts"] = -np.log(p if (hg > 0 and ag > 0) else 1 - p)
    pt = np.bincount(_TOT.ravel(), weights=m.ravel(), minlength=2 * MAX_GOALS + 1)
    for k in range(6):
        out[f"t{k}"] = pt[k] if k < 5 else pt[5:].sum()
    out["s00"], out["s11"] = m[0, 0], m[1, 1]
    return out


def one(row: tuple) -> dict | None:
    mid, season, hg, ag, *o = row
    odds = dict(zip(("h", "d", "a", "over", "under", "ah_line", "ah_h", "ah_a"), o))
    odds = {k: v for k, v in odds.items() if v is not None and v == v}
    out = {"match_id": mid, "season": season, "hg": hg, "ag": ag}
    base = None
    for rho in FIXED:
        f = fit_lambdas(odds, rho)
        if f is None:
            return None
        if rho == -0.05:
            base = f
        out.update({f"{k}@{rho:+.2f}": v for k, v in
                    metrics(dc_matrix(f["lam_h"], f["lam_a"], rho), hg, ag).items()})
    lh, la, rho = fit_free(odds, base)
    out.update({f"{k}@free": v for k, v in metrics(dc_matrix(lh, la, rho), hg, ag).items()})
    out["rho_free"] = rho
    return out


def load() -> list[tuple]:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """SELECT m.match_id, m.season, m.home_goals, m.away_goals,
                  o.avg_h, o.avg_d, o.avg_a, o.avg_over25, o.avg_under25, o.ah_line, o.avg_ahh, o.avg_aha
           FROM matches m JOIN match_odds o USING(match_id)
           WHERE m.match_date >= ? AND o.avg_h IS NOT NULL AND o.avg_over25 IS NOT NULL
             AND o.ah_line IS NOT NULL ORDER BY m.match_date""", (FROM,)).fetchall()
    conn.close()
    return rows


def pm(x) -> str:
    x = np.asarray(x)
    return f"{x.mean():+.5f}±{x.std(ddof=1) / np.sqrt(len(x)):.5f}"


def report(df: pd.DataFrame) -> None:
    variants = [f"{r:+.2f}" for r in FIXED] + ["free"]
    mets = ("score", "1x2", "ou2.5", "ou1.5", "ou3.5", "btts")
    for lab, part in (("选参 1213–2425", df[df.season != HOLDOUT]), ("留出 2526", df[df.season == HOLDOUT])):
        print(f"\n== {lab} n={len(part)}  各项 log loss 均值；括号内为对 rho=−0.05 的同场差（负=更好）")
        for v in variants:
            cells = []
            for k in mets:
                c = part[f"{k}@{v}"]
                cells.append(f"{k} {c.mean():.4f}" + ("" if v == "-0.05" else f"({pm(c - part[f'{k}@-0.05'])})"))
            print(f"  rho {v:<6} " + "  ".join(cells))
        tot = (part.hg + part.ag).clip(upper=5)
        print("  总进球 0/1/2/3/4/5+ 实际：" + " ".join(f"{(tot == k).mean():.3f}" for k in range(6)))
        for v in variants:
            print(f"    预测 rho {v:<6}：" + " ".join(f"{part[f't{k}@{v}'].mean():.3f}" for k in range(6))
                  + f"   0-0 {part[f's00@{v}'].mean():.3f}  1-1 {part[f's11@{v}'].mean():.3f}")
        print(f"    实际 0-0 {((part.hg == 0) & (part.ag == 0)).mean():.3f}  "
              f"1-1 {((part.hg == 1) & (part.ag == 1)).mean():.3f}")
        print(f"  free rho 分布：中位 {part.rho_free.median():+.3f}  四分位 "
              f"{part.rho_free.quantile(.25):+.3f} / {part.rho_free.quantile(.75):+.3f}  "
              f"贴边界 {(part.rho_free.abs() > RHO_MAX - 0.01).mean():.1%}")


def main():
    rows = load()
    print(f"共 {len(rows)} 场（1X2 + 大小 2.5 + 亚盘 都有，{FROM} 起）", flush=True)
    with Pool(16) as pool:
        out = [r for r in pool.map(one, rows, chunksize=200) if r]
    df = pd.DataFrame(out)
    df.to_csv("_diag/explore/score_shape.csv", index=False)
    report(df)


if __name__ == "__main__":
    main()
