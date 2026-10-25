"""赛季末动机（争冠 / 保级 / 欧战 / 无欲无求）是不是赔率没算进去的信息（research.db，只读）。
每场按赛前积分榜（同联赛同赛季，只用该场日期之前的比赛）给两队打标签，只看每队最后 10 场：
  争冠：离榜首 ≤ 剩余场次分；保级：在降级区，或领先降级区首位 ≤ 剩余场次分；
  欧战：离第 6 名 ≤ 剩余场次分；无欲：数学上已保级、够不到第 6、不争冠；其余为中游。
检验沿用 patterns.py：0001–1617 发现、1718–2526 复核，看 实际 − 市场去水概率，两段同向且各自 > 2 SE 才算；
再在复核段比较「市场 + 动机标签」多项 logit 与「只用市场」logit 的同场 log loss（两者都只在发现段拟合）。
用法：PYTHONPATH=. python -u _diag/explore/motivation.py  -> motivation.log
"""
import sqlite3

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

LAST = 10
SPLIT = "2017-07-01"
REL = 3
TAGS = ("争冠", "保级", "欧战", "无欲", "中游")


def load():
    c = sqlite3.connect("research.db")
    return pd.read_sql("""SELECT m.match_id, m.league, m.season, m.match_date, m.home_team, m.away_team,
                                 m.home_goals hg, m.away_goals ag, o.avg_h, o.avg_d, o.avg_a,
                                 o.avgc_h, o.avgc_d, o.avgc_a
                          FROM matches m LEFT JOIN match_odds o USING(match_id)
                          WHERE m.home_goals IS NOT NULL""", c)


def _tag(tab, team, n_games):
    rows = sorted(tab.items(), key=lambda kv: (-kv[1][0], -kv[1][1], -kv[1][2]))
    pts = [v[0] for _, v in rows]
    me = tab[team]
    rem = n_games - me[3]
    if rem > LAST:
        return None
    zone_i = len(rows) - REL                       # 降级区首位
    zone_pts, zone_rem = pts[zone_i], n_games - rows[zone_i][1][3]
    pos = [t for t, _ in rows].index(team)
    if pts[0] - me[0] <= rem:
        return "争冠"
    if pos >= zone_i or me[0] - zone_pts <= rem:
        return "保级"
    if pts[5] - me[0] <= rem:
        return "欧战"
    if me[0] > zone_pts + 3 * zone_rem and me[0] + 3 * rem < pts[5]:
        return "无欲"
    return "中游"


def label(df):
    out = {}
    for _, g in df.sort_values("match_date").groupby(["league", "season"]):
        teams = set(g.home_team) | set(g.away_team)
        n_games = 2 * (len(teams) - 1)
        tab = {t: [0, 0, 0, 0] for t in teams}     # 分、净胜、进球、已赛
        for _, day in g.groupby("match_date", sort=True):
            for r in day.itertuples():
                out[r.match_id] = (_tag(tab, r.home_team, n_games), _tag(tab, r.away_team, n_games))
            for r in day.itertuples():
                for t, gf, ga in ((r.home_team, r.hg, r.ag), (r.away_team, r.ag, r.hg)):
                    s = tab[t]
                    s[0] += 3 if gf > ga else (1 if gf == ga else 0)
                    s[1] += gf - ga
                    s[2] += gf
                    s[3] += 1
    lab = pd.DataFrame.from_dict(out, orient="index", columns=["h_tag", "a_tag"])
    return df.merge(lab, left_on="match_id", right_index=True)


def _probs(f, cols):
    inv = 1 / f[cols].to_numpy()
    return inv / inv.sum(1, keepdims=True)


def _cell(d):
    return f"{d.mean() * 100:+5.1f}±{d.std(ddof=1) / np.sqrt(len(d)) * 100:.1f}"


def resid_table(f, key, title, min_n=150):
    print(f"\n-- {title}（实际 − 市场开盘去水，pp；主胜 / 平 / 客胜）")
    hits = []
    for k, g in f.groupby(key):
        halves = dict(tuple(g.groupby("half")))
        if len(halves) < 2 or min(len(h) for h in halves.values()) < min_n:
            continue
        cells, ok = [], []
        for hname in ("前段", "后段"):
            h = halves[hname]
            ds = [h[a] - h[p] for a, p in (("hw", "mk_h"), ("dr", "mk_d"), ("aw", "mk_a"))]
            cells.append(f"{hname} n={len(h):>5} " + " / ".join(_cell(d) for d in ds))
            ok.append([(d.mean(), d.std(ddof=1) / np.sqrt(len(d))) for d in ds])
        print(f"  {str(k):<12}" + "   ".join(cells))
        for i, out in enumerate(("主胜", "平", "客胜")):
            (m1, s1), (m2, s2) = ok[0][i], ok[1][i]
            if m1 * m2 > 0 and abs(m1) > 2 * s1 and abs(m2) > 2 * s2:
                hits.append(f"{k} {out}")
    print("  两段同向且各自 > 2 SE：", hits or "无")


def _X(f, P, with_tags):
    X = np.log(P)
    if not with_tags:
        return X
    d = [((f[c] == t).to_numpy() * 1.0) for c in ("h_tag", "a_tag") for t in TAGS[:-1]]
    return np.column_stack([X, *d])


def logit_test(f):
    y = np.select([f.hg > f.ag, f.hg == f.ag], [0, 1], 2)
    P = _probs(f, ["avg_h", "avg_d", "avg_a"])
    tr, te = (f.half == "前段").to_numpy(), (f.half == "后段").to_numpy()
    ll = {}
    for name, tags in (("只用市场", False), ("市场 + 动机", True)):
        X = _X(f, P, tags)
        m = LogisticRegression(C=1e4, max_iter=2000).fit(X[tr], y[tr])
        ll[name] = -np.log(m.predict_proba(X[te])[np.arange(te.sum()), y[te]])
    raw = -np.log(P[te][np.arange(te.sum()), y[te]])
    d = ll["市场 + 动机"] - ll["只用市场"]
    print(f"\n-- 复核段 log loss（最后 {LAST} 场，n={te.sum()}）：市场原始 {raw.mean():.4f}  "
          f"只用市场 logit {ll['只用市场'].mean():.4f}  市场 + 动机 {ll['市场 + 动机'].mean():.4f}")
    print(f"   市场 + 动机 − 只用市场 = {d.mean():+.4f} ± {d.std(ddof=1) / np.sqrt(len(d)):.4f}（负 = 动机有用）")


def main():
    f = label(load())
    f = f[f.h_tag.notna() | f.a_tag.notna()].copy()
    f["h_tag"], f["a_tag"] = f.h_tag.fillna("中游"), f.a_tag.fillna("中游")
    f = f.dropna(subset=["avg_h", "avg_d", "avg_a"])
    f["half"] = np.where(f.match_date < SPLIT, "前段", "后段")
    f["hw"], f["dr"], f["aw"] = (f.hg > f.ag) * 1.0, (f.hg == f.ag) * 1.0, (f.hg < f.ag) * 1.0
    f[["mk_h", "mk_d", "mk_a"]] = _probs(f, ["avg_h", "avg_d", "avg_a"])
    print(f"赛季最后 {LAST} 场、有开盘均赔：{len(f)} 场（前段 0001–1617 {(f.half == '前段').sum()}，"
          f"后段 1718–2526 {(f.half == '后段').sum()}）")
    print("标签分布（主队）：", f.h_tag.value_counts().to_dict())

    f["pair"] = f.h_tag + "-" + f.a_tag
    resid_table(f, "h_tag", "主队标签")
    resid_table(f, "a_tag", "客队标签")
    resid_table(f, "pair", "主-客标签组合")
    mot = {"争冠", "保级", "欧战"}
    f["gap"] = np.select([f.h_tag.isin(mot) & (f.a_tag == "无欲"), (f.h_tag == "无欲") & f.a_tag.isin(mot)],
                         ["主有动机-客无欲", "主无欲-客有动机"], "其他")
    resid_table(f, "gap", "动机差")
    logit_test(f)

    c = f[(f.half == "后段")].dropna(subset=["avgc_h", "avgc_d", "avgc_a"]).copy()
    c[["mk_h", "mk_d", "mk_a"]] = _probs(c, ["avgc_h", "avgc_d", "avgc_a"])
    print(f"\n-- 对照：后段改用收盘赔率（n={len(c)}），动机差（实际 − 收盘去水）")
    for k, g in c.groupby("gap"):
        print(f"  {k:<14} n={len(g):>5} " + " / ".join(
            _cell(g[a] - g[p]) for a, p in (("hw", "mk_h"), ("dr", "mk_d"), ("aw", "mk_a"))))


if __name__ == "__main__":
    main()
