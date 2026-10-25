"""评级特征 + LightGBM 的样本外检验（research.db，5 联赛 9394–2526；只读）。
问题 1（无赔率）：Elo / pi-rating（进球、射正、xG 三版）/ Berrar 评级 + 近况特征接 LightGBM，
         能否胜过现在的兜底 dc_xg、候选 dc_market？对照：同样特征的多项 logistic（看树模型是否有额外增益）。
问题 2（有赔率）：以市场去水概率的 log 为 init_score，评级特征只学残差，能否胜过市场本身？
走步：测试赛季 1718..2526 逐季；训练 = 9697 起到测试季之前（评级从 9394 连续滚动，每行只用赛前信息）。
树的轮数在训练集最后一季上早停选出，再在全部训练集上按该轮数重拟合；超参固定，2526 不参与任何选择。
dc_xg / dc_market 的逐场 log loss 取自 _diag/explore/dc_market_{lg}.csv（同一批场次）。
用法：PYTHONPATH=. python -u _diag/explore/ratings_gbm.py  -> ratings_gbm.log / ratings_gbm_pred.csv
"""
import sqlite3
from collections import defaultdict, deque
from math import copysign, exp, log10

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from football_prediction.validation.backtest import _brier_one, _log_loss_one, paired_compare

SEED = 42
BURN_IN = "9697"        # 前三季只用来让评级收敛，不进训练
FIRST_TEST = "1718"
LEAGUES = ("E0", "D1", "SP1", "I1", "F1")
OUT = "_diag/explore/ratings_gbm_pred.csv"
OUTCOMES = ("home_win", "draw", "away_win")
PARAMS = dict(objective="multiclass", num_class=3, learning_rate=0.03, num_leaves=15,
              min_data_in_leaf=200, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
              lambda_l2=5.0, seed=SEED, deterministic=True, num_threads=4, verbose=-1)


def load(conn) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT m.match_id, m.league, m.season, m.match_date, m.home_team, m.away_team,
                  m.home_goals AS hg, m.away_goals AS ag, o.avg_h, o.avg_d, o.avg_a,
                  s.home_sot, s.away_sot, x.home_xg, x.away_xg
           FROM matches m LEFT JOIN match_odds o USING (match_id)
           LEFT JOIN match_stats s USING (match_id) LEFT JOIN match_xg x USING (match_id)
           WHERE m.home_goals IS NOT NULL AND m.league IN ('E0','D1','SP1','I1','F1')
           ORDER BY m.match_date, m.match_id""", conn)


class Ratings:
    """按联赛分开的球队参数；第一次出现的球队（升级队）取该联赛当前最弱 3 队的均值。"""
    def __init__(self, init, strength):
        self.r, self.init, self.strength = {}, init, strength

    def get(self, lg, team):
        if (lg, team) not in self.r:
            pool = sorted((v for (l, _), v in self.r.items() if l == lg), key=self.strength)[:3]
            self.r[(lg, team)] = (np.mean(pool, axis=0) if len(pool) == 3 else np.array(self.init, float))
        return self.r[(lg, team)]


def _psi(x):           # pi-rating：评级 -> 预期进球差
    return copysign(10 ** (abs(x) / 3) - 1, x)


class Pi:
    """pi-rating（Constantinou & Fenton 2013）：每队主 / 客两个评级，λ=0.035、γ=0.7（原文参数）。"""
    LAM, GAM = 0.035, 0.7

    def __init__(self):
        self.t = Ratings([0.0, 0.0], strength=lambda v: v.sum())

    def predict(self, lg, h, a):
        return _psi(self.t.get(lg, h)[0]) - _psi(self.t.get(lg, a)[1])

    def update(self, lg, h, a, gd):
        rh, ra = self.t.get(lg, h), self.t.get(lg, a)
        e = gd - self.predict(lg, h, a)
        step = copysign(3 * log10(1 + abs(e)), e) * self.LAM
        rh[0] += step; rh[1] += step * self.GAM
        ra[1] -= step; ra[0] -= step * self.GAM


class Elo:
    """净胜球加权 Elo（K=20，主场 60 分）。"""
    K, HFA = 20.0, 60.0

    def __init__(self):
        self.t = Ratings([1500.0], strength=lambda v: v[0])

    def predict(self, lg, h, a):
        return self.t.get(lg, h)[0] + self.HFA - self.t.get(lg, a)[0]

    def update(self, lg, h, a, gd):
        d = self.predict(lg, h, a)
        w = 1.0 if gd > 0 else 0.5 if gd == 0 else 0.0
        g = 1.0 if abs(gd) <= 1 else 1.5 if abs(gd) == 2 else (11 + abs(gd)) / 8
        delta = self.K * g * (w - 1 / (1 + 10 ** (-d / 400)))
        self.t.get(lg, h)[0] += delta
        self.t.get(lg, a)[0] -= delta


class Berrar:
    """Berrar ratings（2017 挑战赛）：主 / 客 攻防 4 个参数，预期进球 = α / (1 + exp(−(攻 + 对手防) − γ))。
    α=5，γ 取联赛平均进球 1.5 / 1.15 时的值，学习率 ω=0.05（固定，未调参）。"""
    ALPHA, OMEGA = 5.0, 0.05
    G_H, G_A = -np.log(5 / 1.5 - 1), -np.log(5 / 1.15 - 1)

    def __init__(self):   # [主攻, 主防, 客攻, 客防]，防越大越容易丢球
        self.t = Ratings([0.0] * 4, strength=lambda v: v[0] + v[2] - v[1] - v[3])

    def predict(self, lg, h, a):
        rh, ra = self.t.get(lg, h), self.t.get(lg, a)
        return (self.ALPHA / (1 + exp(-(rh[0] + ra[3]) - self.G_H)),
                self.ALPHA / (1 + exp(-(ra[2] + rh[1]) - self.G_A)))

    def update(self, lg, h, a, hg, ag):
        eh, ea = self.predict(lg, h, a)
        rh, ra = self.t.get(lg, h), self.t.get(lg, a)
        rh[0] += self.OMEGA * (hg - eh); ra[3] += self.OMEGA * (hg - eh)
        ra[2] += self.OMEGA * (ag - ea); rh[1] += self.OMEGA * (ag - ea)


def features(df: pd.DataFrame) -> pd.DataFrame:
    """逐比赛日：先算当天所有场次的赛前特征，再用当天赛果更新（同日比赛互不泄漏）。"""
    elo, pi, pi_sot, pi_xg, ber = Elo(), Pi(), Pi(), Pi(), Berrar()
    n_sot, n_xg = defaultdict(int), defaultdict(int)          # 该队已有多少场射正 / xG 更新
    form = defaultdict(lambda: deque(maxlen=5))               # 最近 5 场 (得分, 进, 失)
    last = {}
    season_pts = defaultdict(lambda: [0, 0])
    rows = []
    for d, g in df.groupby("match_date", sort=True):
        day = pd.Timestamp(d)
        for r in g.itertuples():
            lg, h, a = r.league, r.home_team, r.away_team
            bh, ba = ber.predict(lg, h, a)
            f = {"match_id": r.match_id, "elo_d": elo.predict(lg, h, a), "pi_gd": pi.predict(lg, h, a),
                 "pi_h": pi.t.get(lg, h)[0], "pi_a": pi.t.get(lg, a)[1],
                 "pisot_gd": pi_sot.predict(lg, h, a) if min(n_sot[lg, h], n_sot[lg, a]) >= 5 else np.nan,
                 "pixg_gd": pi_xg.predict(lg, h, a) if min(n_xg[lg, h], n_xg[lg, a]) >= 5 else np.nan,
                 "ber_h": bh, "ber_a": ba, "ber_d": bh - ba}
            for s, t in (("h", h), ("a", a)):
                q = form[lg, t]
                f[f"{s}_f5_pts"] = np.mean([x[0] for x in q]) if q else np.nan
                f[f"{s}_f5_gd"] = np.mean([x[1] - x[2] for x in q]) if q else np.nan
                f[f"{s}_rest"] = min((day - last[lg, t]).days, 30) if (lg, t) in last else np.nan
                p, n = season_pts[r.season, lg, t]
                f[f"{s}_ppg"] = p / n if n else np.nan
                f[f"{s}_n"] = n
            rows.append(f)
        for r in g.itertuples():
            lg, h, a, gd = r.league, r.home_team, r.away_team, r.hg - r.ag
            elo.update(lg, h, a, gd)
            pi.update(lg, h, a, gd)
            ber.update(lg, h, a, r.hg, r.ag)
            if pd.notna(r.home_sot) and pd.notna(r.away_sot):
                pi_sot.update(lg, h, a, (r.home_sot - r.away_sot) / 3)   # 约 3 次射正 ≈ 1 球
                n_sot[lg, h] += 1; n_sot[lg, a] += 1
            if pd.notna(r.home_xg) and pd.notna(r.away_xg):
                pi_xg.update(lg, h, a, r.home_xg - r.away_xg)
                n_xg[lg, h] += 1; n_xg[lg, a] += 1
            ph = 3 if gd > 0 else 1 if gd == 0 else 0
            for t, pts, gf, ga in ((h, ph, r.hg, r.ag), (a, 3 - ph if ph != 1 else 1, r.ag, r.hg)):
                form[lg, t].append((pts, gf, ga))
                last[lg, t] = day
                season_pts[r.season, lg, t][0] += pts
                season_pts[r.season, lg, t][1] += 1
    return pd.DataFrame(rows)


RATING_COLS = ["elo_d", "pi_gd", "pi_h", "pi_a", "pisot_gd", "pixg_gd", "ber_h", "ber_a", "ber_d",
               "h_f5_pts", "h_f5_gd", "h_rest", "h_ppg", "h_n", "a_f5_pts", "a_f5_gd", "a_rest", "a_ppg", "a_n"]
LINEAR_COLS = ["elo_d", "pi_gd", "ber_d"]                 # logistic 对照只用三个评级差（无缺失）
MK = ["mk_h", "mk_d", "mk_a"]


def _softmax(z):
    e = np.exp(z - z.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def _gbm(tr, va, te, cols, init=False):
    """tr 上训练、va 上早停定轮数，再在 tr+va 上按该轮数重拟合；init=True 时以市场 log 概率为起点。"""
    s = (lambda x: np.log(x[MK].to_numpy())) if init else (lambda x: None)
    dtr = lgb.Dataset(tr[cols], tr.y, init_score=s(tr))
    dva = lgb.Dataset(va[cols], va.y, init_score=s(va), reference=dtr)
    b = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    n = max(b.best_iteration, 1)
    both = pd.concat([tr, va])
    full = lgb.train(PARAMS, lgb.Dataset(both[cols], both.y, init_score=s(both)), n)
    raw = full.predict(te[cols], raw_score=True)
    return _softmax(raw + (s(te) if init else 0)), n, full


def _metrics(P, y):
    probs = [dict(zip(OUTCOMES, p)) for p in P]
    return ([_log_loss_one(p, OUTCOMES[k]) for p, k in zip(probs, y)],
            [_brier_one(p, OUTCOMES[k]) for p, k in zip(probs, y)])


def walk_forward(feat: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    order = feat.groupby("season")["match_date"].min().sort_values().index.tolist()
    use = order[order.index(BURN_IN):]
    out, model = [], None
    for s in use[use.index(FIRST_TEST):]:
        prev = use[:use.index(s)]
        tr, va, te = (feat[feat.season.isin(prev[:-1])], feat[feat.season == prev[-1]],
                      feat[feat.season == s])
        pA, nA, model = _gbm(tr, va, te, RATING_COLS)
        both = pd.concat([tr, va])
        mu, sd = both[LINEAR_COLS].mean(), both[LINEAR_COLS].std()
        lr = LogisticRegression(C=1.0, max_iter=2000).fit((both[LINEAR_COLS] - mu) / sd, both.y)
        pL = lr.predict_proba((te[LINEAR_COLS] - mu) / sd)
        has = lambda x: x[x[MK].notna().all(axis=1)]
        teo = has(te)
        pB, nB, _ = _gbm(has(tr), has(va), teo, RATING_COLS + MK, init=True)
        res = te[["match_id", "league", "season", "y"] + MK].copy()
        for name, P, rows in (("gbm", pA, te), ("logit", pL, te), ("resid", pB, teo), ("market", teo[MK].to_numpy(), teo)):
            ll, br = _metrics(P, rows.y.to_numpy())
            res.loc[rows.index, f"ll_{name}"] = ll
            res.loc[rows.index, f"br_{name}"] = br
            res.loc[rows.index, f"hit_{name}"] = (P.argmax(1) == rows.y.to_numpy()).astype(float)
        out.append(res)
        print(f"{s}: n={len(te)} 有赔率 {len(teo)}  轮数 无赔率={nA} 残差={nB}  "
              f"ll gbm={res.ll_gbm.mean():.4f} logit={res.ll_logit.mean():.4f} "
              f"resid={res.ll_resid.mean():.4f} market={res.ll_market.mean():.4f}", flush=True)
    return pd.concat(out, ignore_index=True), model


def _cmp(df, a, b, label):
    r = paired_compare(df.rename(columns={a: "log_loss"}), df.rename(columns={b: "log_loss"}))
    flag = "显著" if abs(r["diff"]) > 2 * r["se"] else "不显著"
    print(f"  {label:<26}{r['diff']:+.5f} ± {r['se']:.5f}  n={r['n']}  {flag}")


def report(res: pd.DataFrame) -> None:
    dc = pd.concat([pd.read_csv(f"_diag/explore/dc_market_{lg}.csv") for lg in LEAGUES])
    dc = dc.rename(columns={"log_loss_xg": "ll_dcxg", "ll_w0.3": "ll_dcmarket", "log_loss_mk": "ll_mk_csv"})
    res = res.merge(dc[["match_id", "ll_dcxg", "ll_dcmarket", "ll_mk_csv"]], on="match_id", how="left")
    res.to_csv(OUT, index=False)
    for label, part in (("选参期 1718–2425", res[res.season != "2526"]), ("留出 2526", res[res.season == "2526"])):
        both = part.dropna(subset=["ll_dcxg", "ll_resid"])
        print(f"\n== {label}  n={len(part)}（与 dc 同场 {len(both)}）")
        print("  log loss  " + "  ".join(f"{k}={both[f'll_{k}'].mean():.4f}" for k in
                                       ("gbm", "logit", "dcxg", "dcmarket", "resid", "market")))
        print("  命中率    " + "  ".join(f"{k}={both[f'hit_{k}'].mean():.3f}" for k in
                                       ("gbm", "logit", "resid", "market")))
        print(f"  （自算市场与 dc_market 脚本里的市场 ll 差：{(both.ll_market - both.ll_mk_csv).abs().max():.5f}）")
        print(" 问题 1 无赔率：")
        _cmp(both, "ll_gbm", "ll_dcxg", "评级+GBM − dc_xg")
        _cmp(both, "ll_gbm", "ll_dcmarket", "评级+GBM − dc_market")
        _cmp(both, "ll_logit", "ll_dcxg", "评级 logistic − dc_xg")
        _cmp(both, "ll_gbm", "ll_logit", "GBM − logistic")
        _cmp(both, "ll_gbm", "ll_market", "评级+GBM − 市场")
        print(" 问题 2 有赔率：")
        _cmp(both, "ll_resid", "ll_market", "市场+评级残差 − 市场")
        if label.startswith("留出"):
            for lg, g in both.groupby("league"):
                print(f"   {lg}:")
                _cmp(g, "ll_gbm", "ll_dcxg", "GBM − dc_xg")
                _cmp(g, "ll_resid", "ll_market", "残差 − 市场")
    sel = res[res.season != "2526"].dropna(subset=["ll_dcxg"])
    print("\n逐季 评级+GBM − dc_xg：" + "  ".join(
        f"{s}:{(g.ll_gbm - g.ll_dcxg).mean():+.4f}" for s, g in sel.groupby("season")))
    print("逐季 残差 − 市场：     " + "  ".join(
        f"{s}:{(g.ll_resid - g.ll_market).mean():+.4f}" for s, g in res.dropna(subset=["ll_resid"]).groupby("season")))


if __name__ == "__main__":
    conn = sqlite3.connect("research.db")
    df = load(conn)
    feat = df.merge(features(df), on="match_id")
    feat["y"] = np.where(feat.hg > feat.ag, 0, np.where(feat.hg == feat.ag, 1, 2))
    inv = 1 / feat[["avg_h", "avg_d", "avg_a"]].to_numpy()
    feat[MK] = inv / inv.sum(1, keepdims=True)
    print(f"共 {len(feat)} 场，{feat.season.nunique()} 季，种子 {SEED}", flush=True)
    res, model = walk_forward(feat)
    report(res)
    imp = pd.Series(model.feature_importance("gain"), index=RATING_COLS).sort_values(ascending=False)
    print("\n最后一季 无赔率 GBM 特征重要性（gain 占比）：" + "  ".join(
        f"{k}={v / imp.sum():.2f}" for k, v in imp.head(10).items()))
