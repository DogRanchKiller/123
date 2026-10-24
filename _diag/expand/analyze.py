"""Analyse _diag/expand/probs_*.csv (research.db, 5 leagues, test seasons 1718..2526).
1) model - market log loss, paired SE, by league / season
2) out-of-sample log-linear blend: weights fitted on earlier test seasons only (expanding), applied to next
3) hit rate overall, when models disagree with market, and by market top-prob bucket
"""
import glob
import numpy as np
import pandas as pd
from scipy.optimize import minimize

df = pd.concat(pd.read_csv(p) for p in glob.glob("_diag/expand/probs_*.csv"))
df["season"] = df["season"].astype(str).str.zfill(4)
Y = df["actual"].map({"home_win": 0, "draw": 1, "away_win": 2}).to_numpy()
P = {k: df[[f"p_home_win_{k}", f"p_draw_{k}", f"p_away_win_{k}"]].to_numpy()
     for k in ("mk", "xg", "elo")}
print(f"matches {len(df)}  leagues {df.league.nunique()}  seasons {df.season.nunique()}\n")


def paired(a, b):
    d = a - b
    return d.mean(), d.std(ddof=1) / np.sqrt(len(d))


print("== model - market (log loss; negative = better than market) ==")
print(f"{'group':<10}{'n':>6}{'mk':>8}{'xg-mk':>9}{'se':>7}{'elo-mk':>9}{'se':>7}")
for name, g in [("ALL", df)] + list(df.groupby("league")) + list(df.groupby("season")):
    dx, sx = paired(g.log_loss_xg, g.log_loss_mk)
    de, se_ = paired(g.log_loss_elo, g.log_loss_mk)
    print(f"{name:<10}{len(g):>6}{g.log_loss_mk.mean():>8.4f}{dx:>+9.4f}{sx:>7.4f}{de:>+9.4f}{se_:>7.4f}")


def blend(w, idx):
    z = w[0] * np.log(P["mk"][idx]) + w[1] * np.log(P["xg"][idx]) + w[2] * np.log(P["elo"][idx])
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


def ll(p, idx):
    return -np.log(p[np.arange(len(idx)), Y[idx]])


print("\n== out-of-sample blend (weights from earlier seasons only) ==")
seasons = sorted(df.season.unique())
rows = []
for i, s in enumerate(seasons[2:], start=2):
    tr = np.where(df.season.isin(seasons[:i]))[0]
    te = np.where(df.season == s)[0]
    w = minimize(lambda w: ll(blend(w, tr), tr).mean(), [1, 0, 0], method="Nelder-Mead").x
    d = ll(blend(w, te), te) - ll(P["mk"][te], te)
    rows.append((s, len(te), *np.round(w, 3), d.mean(), d.std(ddof=1) / np.sqrt(len(d))))
    print(f"{s}  n={len(te)}  w_mk={w[0]:.3f} w_xg={w[1]:+.3f} w_elo={w[2]:+.3f}  "
          f"blend-mk={d.mean():+.4f} se={d.std(ddof=1) / np.sqrt(len(d)):.4f}")
allte = np.where(df.season.isin(seasons[2:]))[0]
d_all = np.concatenate([ll(blend(r[2:5], np.where(df.season == r[0])[0]), np.where(df.season == r[0])[0])
                        - ll(P["mk"][np.where(df.season == r[0])[0]], np.where(df.season == r[0])[0])
                        for r in rows])
print(f"pooled OOS blend-mk = {d_all.mean():+.4f} se={d_all.std(ddof=1) / np.sqrt(len(d_all)):.4f}  n={len(d_all)}")
w_full = minimize(lambda w: ll(blend(w, np.arange(len(df))), np.arange(len(df))).mean(),
                  [1, 0, 0], method="Nelder-Mead").x
print(f"in-sample weights on all data: w_mk={w_full[0]:.3f} w_xg={w_full[1]:+.3f} w_elo={w_full[2]:+.3f}")

print("\n== hit rate (pick = top prob) ==")
pick = {k: P[k].argmax(axis=1) for k in P}
for k in P:
    print(f"{k:<4} {np.mean(pick[k] == Y):.1%}")
dis = pick["xg"] != pick["mk"]
print(f"xg disagrees with market on {dis.mean():.1%} of matches: "
      f"market right {np.mean(pick['mk'][dis] == Y[dis]):.1%}, xg right {np.mean(pick['xg'][dis] == Y[dis]):.1%}")
print(f"market picks draw: {np.mean(pick['mk'] == 1):.2%}")

print("\n== market top prob bucket: share of matches / hit rate (by league) ==")
top = P["mk"].max(axis=1)
hdr = "bucket      " + "".join(f"{lg:>14}" for lg in ["ALL"] + sorted(df.league.unique()))
print(hdr)
for lo, hi in [(0, .45), (.45, .5), (.5, .6), (.6, .7), (.7, 1.01)]:
    cells = []
    for lg in ["ALL"] + sorted(df.league.unique()):
        m = (top >= lo) & (top < hi) & ((df.league == lg).to_numpy() if lg != "ALL" else True)
        base = len(df) if lg == "ALL" else (df.league == lg).sum()
        cells.append(f"{m.sum() / base:>6.0%} {np.mean(pick['mk'][m] == Y[m]):>6.1%}" if m.sum() else " " * 14)
    print(f"[{lo:.2f},{min(hi, 1):.2f})  " + "".join(f"{c:>14}" for c in cells))
for thr in (.6, .7):
    m = top >= thr
    print(f"top >= {thr}: {m.mean():.1%} of matches, hit {np.mean(pick['mk'][m] == Y[m]):.1%}; "
          f"by season hit min/max {min(np.mean(pick['mk'][m & (df.season == s).to_numpy()] == Y[m & (df.season == s).to_numpy()]) for s in seasons):.1%}"
          f"/{max(np.mean(pick['mk'][m & (df.season == s).to_numpy()] == Y[m & (df.season == s).to_numpy()]) for s in seasons):.1%}")
