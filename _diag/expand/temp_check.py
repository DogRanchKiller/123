"""Is the OOS blend gain just market temperature (w_mk>1, model weights 0)? And does it move hit rate?"""
import runpy, numpy as np
from scipy.optimize import minimize_scalar
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path("_diag/expand/analyze.py")
df, P, Y, blend, ll, rows, seasons = (g[k] for k in ("df", "P", "Y", "blend", "ll", "rows", "seasons"))
dt, db, hit_b, hit_m = [], [], [], []
for r in rows:
    s = r[0]; w = np.array(r[2:5])
    tr = np.where(df.season.isin(seasons[:seasons.index(s)]))[0]; te = np.where(df.season == s)[0]
    t = minimize_scalar(lambda t: ll(blend([t, 0, 0], tr), tr).mean(), bounds=(0.5, 2), method="bounded").x
    base = ll(P["mk"][te], te)
    dt.append(ll(blend([t, 0, 0], te), te) - base); db.append(ll(blend(w, te), te) - base)
    hit_b.append(blend(w, te).argmax(1) == Y[te]); hit_m.append(P["mk"][te].argmax(1) == Y[te])
    print(f"{s} temp={t:.3f} temp-mk={dt[-1].mean():+.4f} blend-mk={db[-1].mean():+.4f}")
for name, d in (("temp only", dt), ("blend", db)):
    a = np.concatenate(d); b = np.concatenate(d[-3:])
    print(f"{name:<10} pooled {a.mean():+.4f}±{a.std(ddof=1)/np.sqrt(len(a)):.4f}   last3 {b.mean():+.4f}±{b.std(ddof=1)/np.sqrt(len(b)):.4f}")
hb, hm = np.concatenate(hit_b), np.concatenate(hit_m)
print(f"hit rate OOS: blend {hb.mean():.2%}  market {hm.mean():.2%}  picks differ {np.mean(hb != hm):.2%}")
