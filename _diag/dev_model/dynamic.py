"""自研模型单独开发线 · dev v0.2：动态攻防（按比赛日更新的状态空间近似）与负二项比分分布。
不改实盘：football.db 只读备份到内存，不写库；与 compute.py 的 dc_market 逐场 λ（rows_{lg}.csv）同场比较。

动态攻防（每个联赛一条滤波，按比赛日推进；同一天的比赛先全部预测，再一起更新）：
  λ主 = exp(a主 − d客 + H)，λ客 = exp(a客 − d主)；每个参数有均值和方差（参数之间不记协方差）。
  观测与 dc_market 相同：y = w·进球 + (1−w)·k·赔率反推 λ（收盘价齐全用收盘，否则赛前平均；缺赔率取进球），
  k = 本联赛此前累计 进球 / λ。每个进球观测按泊松做一次扩展卡尔曼（拉普拉斯）更新：
    S = Σ 相关参数方差，θᵢ += Pᵢ·hᵢ·(y − λ)/(S·λ + 1)，Pᵢ −= Pᵢ²·λ/(S·λ + 1)，hᵢ = +1（a、H）/ −1（d）。
  两场之间方差加 q × 间隔天数；换季时各队向联赛均值收缩到 c 倍并加方差 V_SEASON；
  上季不在本联赛的球队（升班马等）取上季离开本联赛那些球队的均值，方差 P_NEW。
负二项：比分边际换成 NB(r)，DC 低比分修正不变；r 越大越接近泊松。
选参只用 2324–2425（胜平负 log loss），留出 2526 与 2627；rho 用 dc_market 同月拟合值，只比较 λ。
用法：PYTHONPATH=. python -u _diag/dev_model/dynamic.py > _diag/dev_model/result_v02.txt
"""
import itertools
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from evaluate import LEAGUES, OLD, cmp, report, score, score_all, score_market   # 同目录脚本
from football_prediction.model_dc.market_dc import lambdas_from_odds
from football_prediction.model_market.implied import MAX_GOALS

HERE = Path(__file__).parent
SEL, HOLD = ("2324", "2425"), ("2526", "2627")
P0, P_NEW, V_SEASON = 0.10, 0.10, 0.02     # 首季初始方差、新来球队方差、换季加的方差
H0, P_H, Q_H = 0.25, 0.01, 1e-6            # 主场优势初值、初始方差、每场加的方差
# 网格按选参期结果外扩过两次（都只看 2324–2425）：w (0.3, 1.0) × q (3e-5…1e-3) × c (0.5…1.0) 最优 w=0.3 q=1e-3 c=1.0，
# w (0.1…0.5) × q (3e-4…4e-3) × c (0.75, 1.0) 最优 w=0.1 q=4e-3 c=1.0，都在边界
# 现网格最优 w=0 q=0.016 c=1.0；另查 w=0 c=1 时 q=0.032 / 0.064 / 0.128 的胜平负 LL 为 0.96787 / 0.96787 / 0.96825（0.016 为 0.96814），已平
GRID = {"w": (0.0, 0.1, 0.2), "q": (0.002, 0.004, 0.008, 0.016), "c": (0.9, 1.0)}
NB_R = (5, 10, 20, 50)
_G = np.arange(MAX_GOALS + 1)


def load(conn: sqlite3.Connection, lg: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT m.match_id, m.season, m.match_date, m.home_team, m.away_team,
                  m.home_goals AS hg, m.away_goals AS ag,
                  o.avg_h, o.avg_d, o.avg_a, o.avgc_h, o.avgc_d, o.avgc_a,
                  o.avg_over25, o.avg_under25, o.avgc_over25, o.avgc_under25
           FROM matches m LEFT JOIN match_odds o ON m.match_id = o.match_id
           WHERE m.league = ? AND m.home_goals IS NOT NULL ORDER BY m.match_date""",
        conn, params=(lg,))
    # 与 market_dc._load 相同：收盘价齐全才用收盘价
    c1 = df[["avgc_h", "avgc_d", "avgc_a"]].notna().all(axis=1)
    c2 = df[["avgc_over25", "avgc_under25"]].notna().all(axis=1)
    pick = lambda cond, c, o: np.where(cond, df[c], df[o])
    df["sig_h"], df["sig_a"] = lambdas_from_odds(
        pick(c1, "avgc_h", "avg_h"), pick(c1, "avgc_d", "avg_d"), pick(c1, "avgc_a", "avg_a"),
        pick(c2, "avgc_over25", "avg_over25"), pick(c2, "avgc_under25", "avg_under25"))
    df["day"] = (pd.to_datetime(df.match_date) - pd.Timestamp("2000-01-01")).dt.days
    return df[["match_id", "season", "day", "home_team", "away_team", "hg", "ag", "sig_h", "sig_a"]]


def run_league(df: pd.DataFrame, w: float, q: float, c: float) -> pd.DataFrame:
    """逐比赛日：先给当天每场出赛前 λ，再用当天结果更新。返回 match_id, v2_lh, v2_la。"""
    mu, var, last = {}, {}, {}           # 键 ("a"|"d", 队)；last[队] = 上次比赛的 day
    H, PH = H0, P_H
    k_num = k_den = 0.0
    season, prev_teams, out = None, set(), []
    for (s, day), g in df.groupby(["season", "day"], sort=True):
        if s != season:                   # 换季
            teams = set(df.home_team[df.season == s]) | set(df.away_team[df.season == s])
            if season is None:
                for t in teams:
                    for p in "ad":
                        mu[p, t], var[p, t] = 0.0, P0
            else:
                gone = prev_teams - teams
                m_a = np.mean([mu["a", t] for t in prev_teams])
                m_d = np.mean([mu["d", t] for t in prev_teams])
                new_a = np.mean([mu["a", t] for t in gone]) if gone else m_a
                new_d = np.mean([mu["d", t] for t in gone]) if gone else m_d
                for t in teams:
                    if t in prev_teams:
                        mu["a", t] = m_a + c * (mu["a", t] - m_a)
                        mu["d", t] = m_d + c * (mu["d", t] - m_d)
                        var["a", t] += V_SEASON
                        var["d", t] += V_SEASON
                    else:
                        mu["a", t], mu["d", t] = new_a, new_d
                        var["a", t] = var["d", t] = P_NEW
                    last.pop(t, None)
            season, prev_teams = s, teams
        for t in set(g.home_team) | set(g.away_team):     # 过程噪声
            if t in last:
                for p in "ad":
                    var[p, t] += q * (day - last[t])
            last[t] = day
        PH += Q_H * len(g)
        rows = list(g.itertuples())
        lams = [(math.exp(mu["a", r.home_team] - mu["d", r.away_team] + H),
                 math.exp(mu["a", r.away_team] - mu["d", r.home_team])) for r in rows]
        out += [(r.match_id, lh, la) for r, (lh, la) in zip(rows, lams)]
        k = k_num / k_den if k_den > 0 else 1.0
        for r, (lh, la) in zip(rows, lams):
            for lam, goals, sig, keys in (
                    (lh, r.hg, r.sig_h, (("a", r.home_team, 1), ("d", r.away_team, -1), ("H", None, 1))),
                    (la, r.ag, r.sig_a, (("a", r.away_team, 1), ("d", r.home_team, -1)))):
                y = goals if sig != sig else w * goals + (1 - w) * k * sig
                S = sum(PH if p == "H" else var[p, t] for p, t, _ in keys)
                den = S * lam + 1.0
                for p, t, h in keys:
                    P = PH if p == "H" else var[p, t]
                    step, newP = P * h * (y - lam) / den, P - P * P * lam / den
                    if p == "H":
                        H, PH = H + step, newP
                    else:
                        mu[p, t], var[p, t] = mu[p, t] + step, newP
        ok = g.sig_h.notna()
        k_num += float((g.hg[ok] + g.ag[ok]).sum())
        k_den += float((g.sig_h[ok] + g.sig_a[ok]).sum())
    return pd.DataFrame(out, columns=["match_id", "v2_lh", "v2_la"])


def nb_matrix(lh: float, la: float, rho: float, r: float) -> np.ndarray:
    """负二项边际 + DC 低比分修正（与 implied.dc_matrix 同网格），归一化。"""
    ph = nbinom.pmf(_G, r, r / (r + lh))
    pa = nbinom.pmf(_G, r, r / (r + la))
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def score_nb(df: pd.DataFrame, lh, la, rho, r: float) -> pd.DataFrame:
    rows = [score(nb_matrix(a, b, c, r), int(x.hg), int(x.ag), x.ah_line)
            for x, a, b, c in zip(df.itertuples(), lh, la, rho)]
    return pd.DataFrame(rows).assign(match_id=df.match_id.to_numpy())


def main() -> None:
    src = sqlite3.connect("file:football.db?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    raw = {lg: load(conn, lg) for lg in LEAGUES}
    rows = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in LEAGUES],
                     ignore_index=True)
    sel, hold = rows[rows.season.isin(SEL)], rows[rows.season.isin(HOLD)]
    dc_sel = score_all(sel, sel.dc_lh, sel.dc_la, sel.dc_rho)
    print(f"选参 {'/'.join(SEL)}：{len(sel)} 场；留出 {'/'.join(HOLD)}：{len(hold)} 场")
    print("差值 = 前者 − 后者。LL 负 = 前者更好；命中正 = 前者更好。|差| > 2SE 记显著。")

    print("\n==== 一、dev v0.2 动态攻防选参（2324–2425，胜平负 LL；dc_market "
          f"{dc_sel.log_loss.mean():.5f}）====")
    res, best = [], None
    for w, q, c in itertools.product(GRID["w"], GRID["q"], GRID["c"]):
        lam = pd.concat([run_league(raw[lg], w, q, c) for lg in LEAGUES], ignore_index=True)
        d = sel.merge(lam, on="match_id")
        sc = score_all(d, d.v2_lh, d.v2_la, d.dc_rho)
        res.append((sc.log_loss.mean(), sc.ah_ll.mean(), w, q, c))
        print(f"  w={w:<4} q={q:<7g} c={c:<5} 胜平负 LL {res[-1][0]:.5f}  亚盘 LL {res[-1][1]:.5f}", flush=True)
        if best is None or res[-1][0] < best[0]:
            best = (res[-1][0], w, q, c, lam)
    _, w, q, c, lam = best
    print(f"  选中 w={w} q={q:g} c={c}")

    d_sel = sel.merge(lam, on="match_id")
    v2_sel = score_all(d_sel, d_sel.v2_lh, d_sel.v2_la, d_sel.dc_rho)
    report("选参期 2324–2425：dev v0.2（前者）对 dc_market（后者）（选参所在，偏乐观）",
           v2_sel, dc_sel, sel.match_id)

    print("\n==== 二、留出：dev v0.2（前者）对 dc_market（后者）====")
    d = hold.merge(lam, on="match_id")
    v2 = score_all(d, d.v2_lh, d.v2_la, d.dc_rho)
    dc = score_all(hold, hold.dc_lh, hold.dc_la, hold.dc_rho)
    report("留出 2526 + 2627 全部", v2, dc, hold.match_id)
    for s in HOLD:
        report(f"留出 {s}", v2, dc, hold.match_id[hold.season == s])
    report("留出 老五联赛", v2, dc, hold.match_id[hold.league.isin(OLD)])
    report("留出 新六联赛", v2, dc, hold.match_id[~hold.league.isin(OLD)])
    print("\n  按联赛（留出，dev v0.2 − dc_market）：")
    for lg in LEAGUES:
        ids = hold.match_id[hold.league == lg]
        a, b = v2[v2.match_id.isin(ids)], dc[dc.match_id.isin(ids)]
        print(f"    {lg:<4} 胜平负 LL {cmp(a, b, 'log_loss')}   亚盘 LL {cmp(a, b, 'ah_ll')}")
    mk = score_market(hold)
    report("留出：dev v0.2（前者）对 赛前市场（后者，参照）", v2, mk, hold.match_id)
    report("留出：dc_market（前者）对 赛前市场（后者，参照）", dc, mk, hold.match_id)

    print("\n==== 三、负二项比分分布（λ 用 dc_market；选 r 用 2324–2425 胜平负 + 比分 LL）====")
    nb_best = None
    for r in NB_R:
        sc = score_nb(sel, sel.dc_lh, sel.dc_la, sel.dc_rho, r)
        print(f"  r={r:<3} 胜平负 LL {sc.log_loss.mean():.5f}  比分 LL {sc.cs_ll.mean():.5f}"
              f"  大小 LL {sc.ou_ll.mean():.5f}   （泊松 {dc_sel.log_loss.mean():.5f} / "
              f"{dc_sel.cs_ll.mean():.5f} / {dc_sel.ou_ll.mean():.5f}）", flush=True)
        if nb_best is None or sc.cs_ll.mean() < nb_best[0]:
            nb_best = (sc.cs_ll.mean(), r)
    r = nb_best[1]
    nb = score_nb(hold, hold.dc_lh, hold.dc_la, hold.dc_rho, r)
    report(f"留出：负二项 r={r}（前者）对 泊松（后者），同为 dc_market λ", nb, dc, hold.match_id)


if __name__ == "__main__":
    main()
