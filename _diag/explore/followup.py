import pandas as pd
from _diag.explore.harness import load_all, run, paired, ll, hit
df = load_all(); base = run(df, {})
C = ["2526", "2627"]
for name, cfg in [("daily", dict(refit="daily")),
                  ("xi_shrink", dict(xi=0.004, shrink=0.1)),
                  ("red", dict(red_w=0.6)),
                  ("xi_shrink+red+daily", dict(xi=0.004, shrink=0.1, red_w=0.6, refit="daily")),
                  ("promoted0.1", dict(prom_c=0.1))]:
    r = run(df, cfg)
    out = [name]
    for ss in [["2324", "2425"], C]:
        n, d, se = paired(r[r.season.isin(ss)], base[base.season.isin(ss)])
        nh, dh, seh = paired(r[r.season.isin(ss)], base[base.season.isin(ss)], f=hit)
        out.append(f"n={n} LL {d:+.4f}±{se:.4f} hit {dh:+.3f}±{seh:.3f}")
    print(" | ".join(out), flush=True)
