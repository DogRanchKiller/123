"""自研模型单独开发线 · 打分：读 compute.py 的 rows_{lg}.csv，在胜平负、亚盘、大小 2.5、比分上逐场打分。
一、基线：dc_market（实盘兜底）对赛前市场，11 联赛 2324–2627。市场参照用 implied_matrix 只喂胜平负 + 大小 2.5
   （football-data 2526 的 AvgAHA 有坏行，见 docs/issues.md），亚盘线用 match_odds.ah_line。
二、dev v0.1 = dc_market × 阵容调整（model_lineup.adjust.design 的四个特征，offset 泊松 + 岭，fit_coef）。
   阵容特征只有 E0 / D1 / SP1 2324–2526（_diag/explore/lineup_fotmob_features.csv）；系数在 2324–2425 拟合，
   2526 留出。场景是「没有赔率、开球前看到正式首发」，所以只在进球上拟合，不用赔率。
亚盘命中：赢 1、赢半 0.75、输半 0.25、输 0，走盘不计；选择方按等效赢盘概率 ≥ 0.5。
用法：PYTHONPATH=. python -u _diag/dev_model/evaluate.py > _diag/dev_model/result.txt
"""
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_lineup.adjust import fit_coef
from football_prediction.model_market.implied import dc_matrix, implied_matrix
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf
from football_prediction.review.store import ah_settle
from football_prediction.validation.backtest import _log_loss_one, _outcome, paired_compare

HERE = Path(__file__).parent
LEAGUES = ["E0", "D1", "SP1", "I1", "F1", "E1", "N1", "P1", "SC0", "B1", "T1"]
OLD = LEAGUES[:5]
LINEUP_CSV = "_diag/explore/lineup_fotmob_features.csv"
TRAIN, HOLD = ("2324", "2425"), "2526"
METRICS = {"log_loss": "胜平负 LL", "ah_ll": "亚盘 LL", "ou_ll": "大小2.5 LL", "cs_ll": "比分 LL",
           "hit": "胜平负命中", "ah_hit": "亚盘命中"}
_HIT = {"win": 1.0, "half_win": 0.75, "half_lose": 0.25, "lose": 0.0}


def score(m: np.ndarray, hg: int, ag: int, line: float) -> dict:
    """一场一个比分矩阵的各盘口打分。"""
    p = {"home_win": np.tril(m, -1).sum(), "draw": np.trace(m), "away_win": np.triu(m, 1).sum()}
    out = _outcome(hg, ag)
    tot = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
    p_over = m[tot > 2.5].sum()
    cs = m[hg, ag] if hg < m.shape[0] and ag < m.shape[1] else 0.0
    row = {"log_loss": _log_loss_one(p, out), "hit": float(max(p, key=p.get) == out),
           "ou_ll": -np.log(max(p_over if hg + ag > 2.5 else 1 - p_over, 1e-7)),
           "cs_ll": -np.log(max(cs, 1e-7)), "ah_ll": np.nan, "ah_hit": np.nan}
    if line == line:
        o = ah_outcome(margin_pmf(m), line)
        k = ah_settle(hg - ag, line)
        row["ah_ll"] = -np.log(max(o[k], 1e-7))
        if k != "push":
            h = _HIT[k]
            row["ah_hit"] = h if ah_fair_prob(o) >= 0.5 else 1 - h
    return row


def score_all(df: pd.DataFrame, lh, la, rho) -> pd.DataFrame:
    rows = [score(dc_matrix(a, b, c), int(r.hg), int(r.ag), r.ah_line)
            for r, a, b, c in zip(df.itertuples(), lh, la, rho)]
    return pd.DataFrame(rows).assign(match_id=df.match_id.to_numpy())


def score_market(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in df.itertuples():
        got = implied_matrix({"h": r.avg_h, "d": r.avg_d, "a": r.avg_a,
                              "over": r.avg_over25, "under": r.avg_under25})
        if got is not None:
            rows.append({**score(got[0], int(r.hg), int(r.ag), r.ah_line), "match_id": r.match_id})
    return pd.DataFrame(rows)


def cmp(a: pd.DataFrame, b: pd.DataFrame, metric: str) -> str:
    c = paired_compare(a.dropna(subset=[metric]), b.dropna(subset=[metric]), metric)
    flag = "显著" if abs(c["diff"]) > 2 * c["se"] else "不显著"
    return f"{c['diff']:+.5f} ± {c['se']:.5f}  n={c['n']:>5}  {flag}"


def report(title: str, a: pd.DataFrame, b: pd.DataFrame, ids) -> None:
    a, b = a[a.match_id.isin(ids)], b[b.match_id.isin(ids)]
    print(f"\n{title}")
    for k, name in METRICS.items():
        print(f"  {name:<10} 前者 {a[k].mean():.4f}  后者 {b[k].mean():.4f}  差 {cmp(a, b, k)}")


def design(df: pd.DataFrame, side: str) -> np.ndarray:
    """与 adjust.design 同序：自己 d_att、rot，对手 rot_def、rot。"""
    o = "a" if side == "h" else "h"
    return df[[f"{side}_d_att", f"{side}_rot", f"{o}_rot_def", f"{o}_rot"]].to_numpy(float)


def main() -> None:
    df = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in LEAGUES],
                   ignore_index=True)
    dc = score_all(df, df.dc_lh, df.dc_la, df.dc_rho)
    mk = score_market(df)
    print(f"共 {len(df)} 场；有赛前胜平负赔率 {len(mk)}；有亚盘线 {df.ah_line.notna().sum()}")
    print("差值 = 前者 − 后者。LL 负 = 前者更好；命中正 = 前者更好。|差| > 2SE 记显著。")

    print("\n==== 一、基线：dc_market（前者）对 赛前市场（后者）====")
    report("全部 11 联赛 2324–2627", dc, mk, df.match_id)
    report("老五联赛", dc, mk, df.match_id[df.league.isin(OLD)])
    report("新六联赛", dc, mk, df.match_id[~df.league.isin(OLD)])
    print("\n  亚盘 LL / 命中，按联赛（dc_market − 市场）：")
    for lg in LEAGUES:
        ids = df.match_id[df.league == lg]
        a, b = dc[dc.match_id.isin(ids)], mk[mk.match_id.isin(ids)]
        print(f"    {lg:<4} 亚盘 LL {cmp(a, b, 'ah_ll')}   dc 亚盘命中 {a.ah_hit.mean():.3f}"
              f"  市场 {b.ah_hit.mean():.3f}")
    print("\n  按赛季（全部联赛，dc_market − 市场）：")
    for s in sorted(df.season.unique()):
        ids = df.match_id[df.season == s]
        a, b = dc[dc.match_id.isin(ids)], mk[mk.match_id.isin(ids)]
        print(f"    {s}  胜平负 LL {cmp(a, b, 'log_loss')}   亚盘 LL {cmp(a, b, 'ah_ll')}")

    print("\n==== 二、dev v0.1：dc_market × 阵容调整（E0 / D1 / SP1）====")
    lu = pd.read_csv(LINEUP_CSV, dtype={"season": str})
    lu = lu.dropna(subset=["h_d_att", "a_d_att"])[["match_id", *[c for c in lu.columns if c[:2] in ("h_", "a_")]]]
    sub = df.merge(lu, on="match_id")
    tr, ho = sub[sub.season.isin(TRAIN)], sub[sub.season == HOLD]
    X = np.vstack([design(tr, "h"), design(tr, "a")])
    off = np.log(np.concatenate([tr.dc_lh, tr.dc_la]))
    goals = np.concatenate([tr.hg, tr.ag]).astype(float)
    coef = fit_coef(X, off, goals)
    b = np.array(list(coef.values()))
    print(f"训练 {len(tr)} 场、留出 {len(ho)} 场。系数：" + "  ".join(f"{k}={v:+.4f}" for k, v in coef.items()))
    dev = score_all(ho, ho.dc_lh * np.exp(design(ho, "h") @ b), ho.dc_la * np.exp(design(ho, "a") @ b),
                    ho.dc_rho)
    report("留出 2526：dev v0.1（前者）对 dc_market（后者）", dev, dc, ho.match_id)
    report("留出 2526：dev v0.1（前者）对 赛前市场（后者，参照）", dev, mk, ho.match_id)


if __name__ == "__main__":
    main()
