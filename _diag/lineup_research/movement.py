"""阵容研究第一步：阵容特征能否解释 赛前 → 收盘 的市场变动，以及叠在赛前赔率上对亚盘的效果。
输入：_diag/explore/lineup_fotmob_features.csv（lineup_fotmob_eval.py 生成，E0 / D1 / SP1 2324–2526）
     + football.db 的 match_odds 亚盘线。特征是开球后的正式首发算出的（相当于临场看到首发）。
一、变动检验：每行一支球队一场，y = log(收盘 λ / 赛前 λ)，X = adjust.design 的四个特征，
   OLS（按场聚类 SE），2324–2425 拟合，2526 看样本外 R²。收盘在正式首发公布之后，
   特征若能解释 y，说明阵容是市场在赛前价之后才定价的真信息。
二、留出季 2526：赛前 λ × exp(X·b)，b 取 (A) 进球泊松拟合（原做法）/ (B) 第一步的变动回归；
   胜平负与赛前亚盘线五种结算的 log loss，对比未调整的赛前；收盘作上限参照。
用法：PYTHONPATH=. python -u _diag/lineup_research/movement.py > _diag/lineup_research/result.txt
"""
import sqlite3

import numpy as np
import pandas as pd

from football_prediction.model_dc.market_dc import lambdas_from_odds
from football_prediction.model_lineup.adjust import FEATURES, fit_coef
from football_prediction.model_market.implied import dc_matrix
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf
from football_prediction.review.store import ah_settle
from football_prediction.validation.backtest import _log_loss_one, _outcome, paired_compare

CSV = "_diag/explore/lineup_fotmob_features.csv"
TRAIN = ("2324", "2425")
HOLD = "2526"
PRE = ("avg_h", "avg_d", "avg_a", "avg_over25", "avg_under25")
CLOSE = ("avgc_h", "avgc_d", "avgc_a", "avgc_over25", "avgc_under25")


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, dtype={"season": str})
    df = df.dropna(subset=list(PRE + CLOSE) + ["h_d_att", "a_d_att"]).reset_index(drop=True)
    conn = sqlite3.connect("file:football.db?mode=ro", uri=True)
    ah = pd.read_sql_query("SELECT match_id, ah_line FROM match_odds", conn)
    conn.close()
    df = df.merge(ah, on="match_id", how="left")
    df["lam_h"], df["lam_a"] = lambdas_from_odds(*(df[c].to_numpy() for c in PRE))
    df["lamc_h"], df["lamc_a"] = lambdas_from_odds(*(df[c].to_numpy() for c in CLOSE))
    return df.dropna(subset=["lam_h", "lamc_h"]).reset_index(drop=True)


def design(df: pd.DataFrame, side: str) -> np.ndarray:
    """与 adjust.design 同序：自己 d_att、rot，对手 rot_def、rot。"""
    o = "a" if side == "h" else "h"
    return df[[f"{side}_d_att", f"{side}_rot", f"{o}_rot_def", f"{o}_rot"]].to_numpy(float)


def team_rows(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(X, y=log 收盘/赛前, log 赛前 λ, 进球, 场序号)，每场两行。"""
    X = np.vstack([design(df, "h"), design(df, "a")])
    y = np.concatenate([np.log(df.lamc_h / df.lam_h), np.log(df.lamc_a / df.lam_a)])
    off = np.log(np.concatenate([df.lam_h, df.lam_a]))
    g = np.concatenate([df.hg, df.ag]).astype(float)
    grp = np.tile(np.arange(len(df)), 2)
    return X, y, off, g, grp


def ols_cluster(X, y, grp):
    """带截距 OLS，按场聚类的稳健 SE；返回 (系数, SE, R²)。"""
    X1 = np.column_stack([np.ones(len(X)), X])
    inv = np.linalg.inv(X1.T @ X1)
    b = inv @ X1.T @ y
    e = y - X1 @ b
    s = np.zeros((len(np.unique(grp)), X1.shape[1]))
    np.add.at(s, grp, X1 * e[:, None])
    se = np.sqrt(np.diag(inv @ (s.T @ s) @ inv))
    return b, se, 1 - e.var() / y.var()


def score(df: pd.DataFrame, lh: np.ndarray, la: np.ndarray) -> pd.DataFrame:
    """每场胜平负 LL、赛前亚盘线五种结算 LL 与选择方命中（赢半 / 输半按半场计，走盘不计）。"""
    rows = []
    for r, h, a in zip(df.itertuples(), lh, la):
        m = dc_matrix(h, a)
        p = {"home_win": np.tril(m, -1).sum(), "draw": np.trace(m), "away_win": np.triu(m, 1).sum()}
        row = {"match_id": r.match_id, "log_loss": _log_loss_one(p, _outcome(r.hg, r.ag))}
        if r.ah_line == r.ah_line:
            o = ah_outcome(margin_pmf(m), r.ah_line)
            k = ah_settle(int(r.hg - r.ag), r.ah_line)
            row["ah_ll"] = -np.log(max(o[k], 1e-7))
            if k != "push":
                won = {"win": 1, "half_win": .5, "half_lose": -.5, "lose": -1}[k]
                row["ah_hit"] = .5 + (won if ah_fair_prob(o) >= .5 else -won) / 2
        rows.append(row)
    return pd.DataFrame(rows)


def cmp(a: pd.DataFrame, b: pd.DataFrame, metric: str) -> str:
    a, b = a.dropna(subset=[metric]), b.dropna(subset=[metric])
    c = paired_compare(a, b, metric)
    return f"{c['diff']:+.5f} ± {c['se']:.5f} (n={c['n']})"


def main() -> None:
    df = load()
    tr, ho = df[df.season.isin(TRAIN)], df[df.season == HOLD]
    print(f"场次：训练 {len(tr)}，留出 {len(ho)}；有赛前亚盘线 {ho.ah_line.notna().sum()}")

    print("\n== 一、阵容特征 vs 赛前→收盘 log λ 变动（每行一队一场）==")
    Xt, yt, offt, gt, grpt = team_rows(tr)
    Xh, yh, offh, gh, grph = team_rows(ho)
    print(f"y 标准差：训练 {yt.std():.4f}，留出 {yh.std():.4f}")
    for name, (X, y, grp) in {"训练": (Xt, yt, grpt), "留出": (Xh, yh, grph)}.items():
        b, se, r2 = ols_cluster(X, y, grp)
        print(f"{name} R²={r2:.4f}  " + "  ".join(
            f"{k}={b[i + 1]:+.4f}±{se[i + 1]:.4f}" for i, k in enumerate(FEATURES)))
    b_mv, _, _ = ols_cluster(Xt, yt, grpt)
    e = yh - np.column_stack([np.ones(len(Xh)), Xh]) @ b_mv
    print(f"留出季用训练系数的样本外 R²：{1 - (e ** 2).mean() / ((yh - yh.mean()) ** 2).mean():.4f}")

    coef_goal = fit_coef(Xt, offt, gt)
    coef_move = dict(zip(FEATURES, b_mv[1:]))
    print("\n系数 (A) 进球泊松：" + "  ".join(f"{k}={v:+.4f}" for k, v in coef_goal.items()))
    print("系数 (B) 变动回归：" + "  ".join(f"{k}={v:+.4f}" for k, v in coef_move.items()))

    print("\n== 二、留出季 2526：赛前 λ × exp(X·b)，对比未调整的赛前 ==")
    base = score(ho, ho.lam_h.to_numpy(), ho.lam_a.to_numpy())
    close = score(ho, ho.lamc_h.to_numpy(), ho.lamc_a.to_numpy())
    variants = {"(A) 进球泊松": coef_goal, "(B) 变动回归": coef_move, "收盘（上限参照）": None}
    print(f"赛前基准：胜平负 LL {base.log_loss.mean():.4f}  亚盘 LL {base.ah_ll.mean():.4f}  "
          f"亚盘命中 {base.ah_hit.mean():.3f}")
    for name, coef in variants.items():
        if coef is None:
            s = close
        else:
            b = np.array([coef[k] for k in FEATURES])
            n = len(ho)
            s = score(ho, ho.lam_h.to_numpy() * np.exp(Xh[:n] @ b),
                      ho.lam_a.to_numpy() * np.exp(Xh[n:] @ b))
        print(f"{name}：胜平负 {cmp(s, base, 'log_loss')}  亚盘 {cmp(s, base, 'ah_ll')}  "
              f"命中 {s.ah_hit.mean():.3f}（差 {cmp(s, base, 'ah_hit')}）")


if __name__ == "__main__":
    main()
