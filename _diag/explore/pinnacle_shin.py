"""Pinnacle vs average odds, each with proportional and Shin devig (1X2 log loss, same matches)."""
import numpy as np
from _diag.explore.unused_cols import load, ll, SPLIT
from football_prediction.model_market.devig import devig

df = load()
df = df[df[["av_h", "av_d", "av_a", "ps_h", "ps_d", "ps_a"]].notna().all(axis=1)].reset_index(drop=True)
y = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
P = {}
for src in ("av", "ps"):
    O = df[[f"{src}_h", f"{src}_d", f"{src}_a"]].to_numpy()
    for m in ("proportional", "shin"):
        P[(src, m)] = np.array([devig(o, m) for o in O])
P[("mix", "shin")] = (P[("av", "shin")] + P[("ps", "shin")]) / 2
base = ("av", "proportional")
for lab, sel in (("disc", (df.date < SPLIT).to_numpy()), ("conf", (df.date >= SPLIT).to_numpy())):
    b = ll(P[base][sel], y[sel])
    for k in [("av", "shin"), ("ps", "proportional"), ("ps", "shin"), ("mix", "shin")]:
        d = ll(P[k][sel], y[sel]) - b
        print(f"{lab} {k[0]}+{k[1]:<13} - av+prop  {d.mean():+.5f} +- {d.std(ddof=1)/np.sqrt(len(d)):.5f} n={len(d)}")
    d = ll(P[("ps", "shin")][sel], y[sel]) - ll(P[("av", "shin")][sel], y[sel])
    print(f"{lab} ps+shin - av+shin  {d.mean():+.5f} +- {d.std(ddof=1)/np.sqrt(len(d)):.5f}")
