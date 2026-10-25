"""Paired summary of dc_market vs dc_xg (and market) from _diag/explore/dc_market_{lg}.csv."""
import numpy as np, pandas as pd
df = pd.concat(pd.read_csv(f"_diag/explore/dc_market_{lg}.csv", dtype={"season": str})
               for lg in ("E0", "D1", "SP1", "I1", "F1"))
def pair(d, a, b):
    x = d[a] - d[b]
    return f"{x.mean():+.5f} +- {x.std(ddof=1) / np.sqrt(len(x)):.5f}"
for label, part in (("select 1718-2425", df[df.season != "2526"]), ("holdout 2526", df[df.season == "2526"])):
    print(f"== {label}  n={len(part)}")
    for w in ("0.0", "0.3", "0.6"):
        print(f"  w{w}: ll={part[f'll_w{w}'].mean():.5f}  vs dc_xg {pair(part, f'll_w{w}', 'log_loss_xg')}"
              f"  vs market {pair(part, f'll_w{w}', 'log_loss_mk')}")
    print(f"  dc_xg ll={part['log_loss_xg'].mean():.5f}  market ll={part['log_loss_mk'].mean():.5f}")
    if label.startswith("holdout"):
        for lg, g in part.groupby("league"):
            print(f"    {lg} w0.3 vs dc_xg {pair(g, 'll_w0.3', 'log_loss_xg')}  n={len(g)}")
