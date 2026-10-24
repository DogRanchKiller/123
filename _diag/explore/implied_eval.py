"""第 0 步门槛：市场反推比分矩阵 vs dc_xg 比分矩阵（2324-2627，三联赛，赛前赔率=实盘可得）
评分：胜平负 / 大小 1.5 2.5 3.5 / 双方进球 / 精确比分 / 亚盘（按赛前亚盘线，走盘不计）logloss，配对差值±SE。
另做 market_1x2only（只用胜平负反推）看大小球、亚盘输入的增量。"""
import glob
import numpy as np
import pandas as pd

from _diag.explore.harness import load_all, run, BASE
from football_prediction.data.loader import _make_match_id, _normalize, _parse_date
from football_prediction.model_market.implied import implied_matrix, dc_matrix
from football_prediction.output.derive import ah_outcome, margin_pmf

fr = []
for p in glob.glob("_cache/fd_raw/*.csv"):
    d = pd.read_csv(p, encoding="latin-1")
    lg, s = p.replace("\\", "/").split("/")[-1][:-4].split("_")
    d = d.dropna(subset=["HomeTeam", "AwayTeam", "FTHG"])
    d["match_id"] = [_make_match_id(lg, s, _parse_date(r.Date), _normalize(r.HomeTeam), _normalize(r.AwayTeam))
                     for r in d.itertuples()]
    fr.append(d)
raw = pd.concat(fr).set_index("match_id")

df = load_all()
r = run(df, BASE).set_index("match_id")
r = r.join(raw[["FTHG", "FTAG", "AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5", "AHh", "AvgAHH", "AvgAHA"]], how="inner")
print("n =", len(r))

rows = []
for mid, x in r.iterrows():
    hg, ag = int(x.FTHG), int(x.FTAG)
    full = dict(h=x.AvgH, d=x.AvgD, a=x.AvgA, over=x["Avg>2.5"], under=x["Avg<2.5"],
                ah_line=x.AHh, ah_h=x.AvgAHH, ah_a=x.AvgAHA)
    mats = {"dc_xg": dc_matrix(x.lam_h, x.lam_a, x.rho)}
    a = implied_matrix(full, x.rho)
    b = implied_matrix(dict(h=x.AvgH, d=x.AvgD, a=x.AvgA), x.rho)
    if a is None or b is None:
        continue
    mats["market_implied"], mats["market_1x2only"] = a[0], b[0]
    line = x.AHh
    row = {"match_id": mid, "season": x.season, "rmse": a[1]["rmse"]}
    for k, m in mats.items():
        tot = np.add.outer(np.arange(9), np.arange(9))
        res = 0 if hg > ag else 1 if hg == ag else 2
        p1 = [np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()][res]
        row[f"{k}|1x2"] = -np.log(p1)
        for L in (1.5, 2.5, 3.5):
            po = m[tot > L].sum()
            row[f"{k}|ou{L}"] = -np.log(po if hg + ag > L else 1 - po)
        pb = m[1:, 1:].sum()
        row[f"{k}|btts"] = -np.log(pb if hg > 0 and ag > 0 else 1 - pb)
        row[f"{k}|score"] = -np.log(max(m[min(hg, 8), min(ag, 8)], 1e-9))
        # 亚盘：按两半注分别评分（赢/输二元，走盘半注跳过）
        if line == line:
            o = ah_outcome(margin_pmf(m), line)
            halves = [line - .25, line + .25] if np.isclose((line * 4) % 2, 1) else [line]
            s, c = 0.0, 0
            for hl in halves:
                v = (hg - ag) + hl
                if v == 0:
                    continue
                oh = ah_outcome(margin_pmf(m), hl)
                pw = oh["win"] / (oh["win"] + oh["lose"])
                s += -np.log(pw if v > 0 else 1 - pw)
                c += 1
            row[f"{k}|ah"] = s / c if c else np.nan
    rows.append(row)
R = pd.DataFrame(rows)
print("拟合残差 rmse 中位", round(R.rmse.median(), 4), " >0.02 占", f"{(R.rmse > 0.02).mean():.1%}")

mk = ["1x2", "ou1.5", "ou2.5", "ou3.5", "btts", "score", "ah"]
print(f"\n{'市场':8}{'dc_xg':>9}{'implied':>9}{'implied-dc_xg':>18}{'1x2only-dc_xg':>18}{'implied-1x2only':>18}")
for k in mk:
    a, b, c = R[f"dc_xg|{k}"], R[f"market_implied|{k}"], R[f"market_1x2only|{k}"]
    ok = a.notna() & b.notna()
    f = lambda d: f"{d.mean():+.4f}±{d.std(ddof=1)/np.sqrt(len(d)):.4f}"
    print(f"{k:8}{a[ok].mean():9.4f}{b[ok].mean():9.4f}{f(b[ok]-a[ok]):>18}{f(c[ok]-a[ok]):>18}{f(b[ok]-c[ok]):>18}")
print("\n分赛季 implied - dc_xg（score / ou2.5 / ah）")
for s, g in R.groupby("season"):
    print(" ", s, len(g), *[f"{(g[f'market_implied|{k}']-g[f'dc_xg|{k}']).mean():+.4f}" for k in ("score", "ou2.5", "ah")])
R.to_csv("_diag/explore/implied_eval.csv", index=False)
