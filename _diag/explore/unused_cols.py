"""football-data 原始 CSV 里系统没用上的列，逐个检验有没有赔率之外的信息（_cache/fd_research，只读）。
做法：残差 = 实际（0/1）− 市场平均赔率比例去水概率；对每个赛前可知的信号做残差 ~ 信号 的 OLS 斜率，
发现段（0506–1617 或该列起始的前半）与复核段（之后）分开算，两段同号且各自 |t| > 2 才算有用。
用法：PYTHONPATH=. python -u _diag/explore/unused_cols.py  -> unused_cols.log
"""
import glob
import os

import numpy as np
import pandas as pd

from football_prediction.data.loader import _parse_date

LEAGUES = ("E0", "D1", "SP1", "I1", "F1")


def _col(d, *names):
    for n in names:
        if n in d:
            return pd.to_numeric(d[n], errors="coerce")
    return pd.Series(np.nan, index=d.index)


def load() -> pd.DataFrame:
    out = []
    for f in glob.glob("_cache/fd_research/*.csv"):
        lg, s = os.path.basename(f)[:-4].split("_")
        if lg not in LEAGUES:
            continue
        d = pd.read_csv(f, encoding="latin1", on_bad_lines="skip")
        d.columns = [c.replace("ï»¿", "") for c in d.columns]
        d = d.dropna(subset=["HomeTeam", "FTHG"])
        r = pd.DataFrame({"league": lg, "season": s, "home": d.HomeTeam, "away": d.AwayTeam,
                          "date": pd.to_datetime(d.Date.map(_parse_date), errors="coerce"),
                          "hg": _col(d, "FTHG"), "ag": _col(d, "FTAG"),
                          "hthg": _col(d, "HTHG"), "htag": _col(d, "HTAG"),
                          "hst": _col(d, "HST"), "ast": _col(d, "AST"),
                          "hr": _col(d, "HR"), "ar": _col(d, "AR"),
                          "ref": d["Referee"] if "Referee" in d else np.nan,
                          "time": d["Time"] if "Time" in d else np.nan,
                          "nbooks": _col(d, "Bb1X2")})
        for k, names in {"av": ("AvgH", "BbAvH"), "mx": ("MaxH", "BbMxH"), "ps": ("PSH",)}.items():
            for i, side in enumerate("hda"):
                r[f"{k}_{side}"] = _col(d, *(n[:-1] + "HDA"[i] for n in names))
        r["ov"], r["un"] = _col(d, "Avg>2.5", "BbAv>2.5"), _col(d, "Avg<2.5", "BbAv<2.5")
        out.append(r)
    df = pd.concat(out, ignore_index=True).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for k in ("av", "mx", "ps"):
        inv = 1 / df[[f"{k}_h", f"{k}_d", f"{k}_a"]].to_numpy()
        p = inv / inv.sum(1, keepdims=True)
        for i, side in enumerate("hda"):
            df[f"p{k}_{side}"] = p[:, i]
    inv = 1 / df[["ov", "un"]].to_numpy()
    df["p_ov"] = inv[:, 0] / inv.sum(1)
    df["hw"], df["dr"] = (df.hg > df.ag) * 1.0, (df.hg == df.ag) * 1.0
    df["over"] = ((df.hg + df.ag) > 2.5) * 1.0
    df["r_hw"], df["r_dr"], df["r_ov"] = df.hw - df.pav_h, df.dr - df.pav_d, df.over - df.p_ov
    P = df[["pav_h", "pav_d", "pav_a"]].to_numpy()
    y = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
    # 实际 log loss − 市场自己预期的 log loss（熵）：市场校准时均值为 0；正 = 比赔率说的更难猜
    df["r_ll"] = -np.log(P[np.arange(len(df)), y]) + (P * np.log(P)).sum(1)
    return df


def team_history(df: pd.DataFrame) -> pd.DataFrame:
    """每队每场一行（按日期），算出该队「上一场」的信号与此前的累计残差，再并回主客两侧。"""
    rows = []
    for side, o in (("h", "a"), ("a", "h")):
        sgn = 1 if side == "h" else -1
        rows.append(pd.DataFrame({
            "idx": df.index, "league": df.league, "date": df.date,
            "team": df["home" if side == "h" else "away"],
            "red": df[f"{side}r"], "gd": sgn * (df.hg - df.ag), "sotd": sgn * (df.hst - df.ast),
            "ht_lead_lost": ((sgn * (df.hthg - df.htag) > 0) & (sgn * (df.hg - df.ag) <= 0)) * 1.0,
            "res_win": (df.hw if side == "h" else (df.hg < df.ag) * 1.0) - df[f"pav_{side}"],
            "res_dr": df.r_dr, "res_ov": df.r_ov, "side": side}))
    t = pd.concat(rows).sort_values(["date", "idx"]).reset_index(drop=True)
    g = t.groupby(["league", "team"])
    t["luck"] = t.gd - t.sotd / 3                     # 净胜球比射正差 /3 多出来的部分
    for c in ("red", "luck", "ht_lead_lost"):
        t[f"prev_{c}"] = g[c].shift(1)
    for c, k in (("res_win", 50), ("res_dr", 50), ("res_ov", 50)):  # 此前全部场次残差，向 0 收缩（k 场先验）
        s = g[c].transform(lambda x: x.shift(1).fillna(0).cumsum())
        n = g.cumcount()
        t[f"hist_{c}"] = s / (n + k)
    keep = ["prev_red", "prev_luck", "prev_ht_lead_lost", "hist_res_win", "hist_res_dr", "hist_res_ov"]
    h = t[t.side == "h"].set_index("idx")[keep].add_prefix("h_")
    a = t[t.side == "a"].set_index("idx")[keep].add_prefix("a_")
    return df.join(h).join(a)


def referee(df: pd.DataFrame, k: int = 50) -> pd.DataFrame:
    """裁判此前执法场次的主胜残差 / 大球残差均值（收缩）；只用该场之前的比赛。"""
    d = df[df.ref.notna()].sort_values("date")
    g = d.groupby("ref")
    n = g.cumcount()
    for c in ("r_hw", "r_ov"):
        df.loc[d.index, f"ref_{c}"] = g[c].transform(lambda x: x.shift(1).fillna(0).cumsum()) / (n + k)
    df.loc[d.index, "ref_n"] = n
    return df


SPLIT = pd.Timestamp("2017-07-01")


CONTROLS = ["pav_h", "pav_a"]


def _partial(d, c, cols):
    """c 对市场概率（主胜、客胜及其平方）回归后的残差：去掉「热门-冷门偏差」的部分。"""
    X = np.column_stack([np.ones(len(d))] + [d[k] ** p for k in cols for p in (1, 2)])
    return d[c] - X @ np.linalg.lstsq(X, d[c].to_numpy(), rcond=None)[0]


def slope(df, y, x, control=False):
    """残差 y 对信号 x（标准化）的 OLS 斜率，单位：信号每 +1 SD 残差变化几个百分点。
    control=True 时先把 x、y 都对市场概率做偏回归（Frisch–Waugh），看去掉热门偏差后还剩多少。"""
    out = []
    for part in (df[df.date < SPLIT], df[df.date >= SPLIT]):
        d = part[[y, x] + CONTROLS].dropna()
        if len(d) < 300 or d[x].std() == 0:
            out.append(None)
            continue
        xv = _partial(d, x, CONTROLS) if control else d[x] - d[x].mean()
        yv = _partial(d, y, CONTROLS) if control else d[y] - d[y].mean()
        z = xv / xv.std()
        b = (z * yv).sum() / (z * z).sum()
        e = yv - b * z
        se = np.sqrt((e ** 2).sum() / (len(d) - 2) / (z * z).sum())
        out.append((b * 100, se * 100, len(d)))
    ok = all(out) and np.sign(out[0][0]) == np.sign(out[1][0]) and all(abs(b / s) > 2 for b, s, _ in out)
    cells = ["      —            " if o is None else f"{o[0]:+5.2f}±{o[1]:.2f} n={o[2]:<6}" for o in out]
    return f"{cells[0]}  {cells[1]}  {'★ 两段都显著' if ok else ''}"


def ll(P, y):
    return -np.log(np.clip(P[np.arange(len(P)), y], 1e-9, None))


def main():
    df = referee(team_history(load()))
    print(f"共 {len(df)} 场，{df.date.min().date()} – {df.date.max().date()}；"
          f"发现段 < {SPLIT.date()}，复核段之后")
    print("\n== 列覆盖（有值的场次）")
    for c in ("ref", "time", "hr", "hthg", "hst", "nbooks", "mx_h", "ps_h", "pav_h", "p_ov"):
        print(f"  {c:<8}{df[c].notna().sum():>6}  从 {df.loc[df[c].notna(), 'date'].min().date()}")

    print("\n== 一、哪家赔率更准（1X2 log loss，同场）")
    y = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
    m = df[["pav_h", "pps_h"]].notna().all(1).to_numpy()
    for lab, sel in (("发现段", (df.date < SPLIT).to_numpy() & m), ("复核段", (df.date >= SPLIT).to_numpy() & m)):
        Pav = df.loc[sel, ["pav_h", "pav_d", "pav_a"]].to_numpy()
        Pps = df.loc[sel, ["pps_h", "pps_d", "pps_a"]].to_numpy()
        Pmx = df.loc[sel, ["pmx_h", "pmx_d", "pmx_a"]].to_numpy()
        base = ll(Pav, y[sel])
        for name, P in (("Pinnacle", Pps), ("最高赔率", Pmx), ("平均+Pinnacle 各半", (Pav + Pps) / 2)):
            d = ll(P, y[sel]) - base
            d = d[~np.isnan(d)]
            print(f"  {lab} {name:<16} − 平均  {d.mean():+.5f} ± {d.std(ddof=1) / np.sqrt(len(d)):.5f}  n={len(d)}")

    print("\n== 二、赛前信号 → 残差（每 +1 SD 的百分点；发现段 | 复核段）")
    df["ps_minus_av"] = df.pps_h - df.pav_h
    df["disp"] = np.log(df.mx_h / df.av_h) + np.log(df.mx_d / df.av_d) + np.log(df.mx_a / df.av_a)
    df["red_d"] = df.h_prev_red.fillna(0) - df.a_prev_red.fillna(0)
    df["luck_d"] = df.h_prev_luck - df.a_prev_luck
    df["htlost_d"] = df.h_prev_ht_lead_lost - df.a_prev_ht_lead_lost
    df["hist_win_d"] = df.h_hist_res_win - df.a_hist_res_win
    df["hist_dr_s"] = df.h_hist_res_dr + df.a_hist_res_dr
    df["hist_ov_s"] = df.h_hist_res_ov + df.a_hist_res_ov
    df["ref_hw"] = df.ref_r_hw.where(df.ref_n >= 20)
    df["ref_ov"] = df.ref_r_ov.where(df.ref_n >= 20)
    hour = pd.to_numeric(df.time.astype(str).str[:2], errors="coerce")
    df["late_ko"] = (hour >= 19).astype(float).where(hour.notna())
    df["midweek"] = df.date.dt.dayofweek.between(1, 3).astype(float)
    tests = [
        ("Pinnacle 比平均更看好主队", "r_hw", "ps_minus_av"),
        ("各家分歧大（最高/平均）", "r_ll", "disp"),
        ("开出赔率的公司多", "r_ll", "nbooks"),
        ("上一场红牌（主 − 客）", "r_hw", "red_d"),
        ("上一场运气（净胜球 − 射正差/3）", "r_hw", "luck_d"),
        ("上一场半场领先被追平/逆转", "r_hw", "htlost_d"),
        ("球队此前一直被市场低估", "r_hw", "hist_win_d"),
        ("两队此前平局比市场多", "r_dr", "hist_dr_s"),
        ("两队此前大球比市场多", "r_ov", "hist_ov_s"),
        ("裁判此前主胜偏多（≥20 场）", "r_hw", "ref_hw"),
        ("裁判此前大球偏多（≥20 场）", "r_ov", "ref_ov"),
        ("晚场（19 点后开球）", "r_hw", "late_ko"),
        ("周中比赛", "r_hw", "midweek"),
        ("周中比赛", "r_ov", "midweek"),
    ]
    for lab, y_, x in tests:
        print(f"  {lab:<26}{y_:<5} {slope(df, y_, x)}")
    print("\n== 三、同样的信号，控制市场概率（去掉热门-冷门偏差）后")
    for lab, y_, x in tests:
        print(f"  {lab:<26}{y_:<5} {slope(df, y_, x, control=True)}")


if __name__ == "__main__":
    main()
