"""单场分析演示：把主模型对一场比赛的判断过程逐步展开。
用法: python analyze_match.py <联赛> <主队> <客队>   例: SP1 Barcelona "Real Madrid"
只读数据库，不写预测记录。"""
import sqlite3, sys
import numpy as np
import pandas as pd
from football_prediction.model_dc.xg_dc import XgDixonColesModel
from football_prediction.output.derive import derive_markets
from football_prediction.output.report import confidence_tier, _double_label

lg, home, away = sys.argv[1], sys.argv[2], sys.argv[3]
conn = sqlite3.connect("football.db")
fx = pd.read_sql_query("SELECT * FROM fixtures WHERE league=? AND home_team=? AND away_team=?",
                       conn, params=(lg, home, away)).iloc[0]
cut = fx.match_date
M = pd.read_sql_query(
    """SELECT m.season, m.match_date, m.home_team, m.away_team, m.home_goals hg, m.away_goals ag,
              x.home_xg xh, x.away_xg xa
       FROM matches m LEFT JOIN match_xg x USING(match_id)
       WHERE m.league=? AND m.match_date<? AND m.home_goals IS NOT NULL ORDER BY m.match_date""",
    conn, params=(lg, cut))
season = M.season.iloc[-1]
pd.set_option("display.width", 200)
print(f"=== {home} vs {away}  {cut}  ({lg})  训练数据截至开赛前 {len(M)} 场 ===\n")

print("【1】近 6 场联赛（xG = 机会质量，比比分更能反映真实表现）")
for t in (home, away):
    g = M[(M.home_team == t) | (M.away_team == t)].tail(6)
    rows = []
    for r in g.itertuples():
        h = r.home_team == t
        rows.append({"日期": r.match_date, "主客": "主" if h else "客",
                     "对手": r.away_team if h else r.home_team,
                     "比分": f"{r.hg if h else r.ag}-{r.ag if h else r.hg}",
                     "xG": f"{(r.xh if h else r.xa):.2f}-{(r.xa if h else r.xh):.2f}"})
    print(f"  {t}"); print(pd.DataFrame(rows).to_string(index=False)); print()

print(f"【2】本赛季（{season}）场均")
S = M[M.season == season]
for t in (home, away):
    hs, as_ = S[S.home_team == t], S[S.away_team == t]
    gf = pd.concat([hs.hg, as_.ag]).mean(); ga = pd.concat([hs.ag, as_.hg]).mean()
    xf = pd.concat([hs.xh, as_.xa]).mean(); xa = pd.concat([hs.xa, as_.xh]).mean()
    print(f"  {t:14s} {len(hs) + len(as_)} 场  进 {gf:.2f} 失 {ga:.2f} | xG {xf:.2f} 被xG {xa:.2f}")

print("\n【3】交锋记录（仅作参考：样本太少、阵容已变，模型不单独使用）")
h2h = M[((M.home_team == home) & (M.away_team == away)) | ((M.home_team == away) & (M.away_team == home))].tail(5)
for r in h2h.itertuples():
    print(f"  {r.match_date} {r.home_team} {r.hg}-{r.ag} {r.away_team}  (xG {r.xh:.2f}-{r.xa:.2f})")

m = XgDixonColesModel(); m.fit(conn, lg, cut)
teams = sorted(m.teams, key=lambda t: -(m.attack[t] + m.defence[t]))
cur = set(S.home_team) | set(S.away_team) | {home, away}
rank = [t for t in teams if t in cur]
base = np.exp(m._mean_attack - m._mean_defence)
print("\n【4】模型实力评分（全部历史比赛加权拟合，近期权重高，已扣除对手强弱）")
for t in (home, away):
    a, d = m.attack[t], m.defence[t]
    print(f"  {t:14s} 进攻 {a:+.3f}  防守 {d:+.3f}  综合排名 {rank.index(t) + 1}/{len(rank)}"
          f"  | 对阵平均球队(中立场)：进 {np.exp(a - m._mean_defence):.2f} 失 {np.exp(m._mean_attack - d):.2f}")
print(f"  联赛平均球队对平均球队(中立场)进球 {base:.2f}；主场优势 ×{np.exp(m.home_adv):.2f}")

lh, la = m._lambda(home, away)
print("\n【5】本场预期进球")
print(f"  {home} = exp(进攻 {m.attack[home]:+.3f} − 对手防守 {m.defence[away]:+.3f} + 主场 {m.home_adv:+.3f}) = {lh:.2f}")
print(f"  {away} = exp(进攻 {m.attack[away]:+.3f} − 对手防守 {m.defence[home]:+.3f}) = {la:.2f}")

S_ = m.score_matrix(home, away); d = derive_markets(S_)
print(f"\n【6】比分概率表（%，行={home}进球，列={away}进球；低比分 ρ={m.rho:+.3f} 修正）")
print(pd.DataFrame((S_[:5, :5] * 100).round(1), index=[f"主{i}" for i in range(5)],
                   columns=[f"客{j}" for j in range(5)]).to_string())

ph, pdr, pa = d["home_win"], d["draw"], d["away_win"]
btts = 1 - S_[0, :].sum() - S_[:, 0].sum() + S_[0, 0]
push0 = np.trace(S_)
print("\n【7】从比分表推出的各项结果")
print(f"  胜平负   主胜 {ph:.1%}  平 {pdr:.1%}  客胜 {pa:.1%}")
print(f"  大小球   大1.5 {d['over_1.5']:.1%}  大2.5 {d['over_2.5']:.1%}  大3.5 {d['over_3.5']:.1%}   双方进球 {btts:.1%}")
for line in (-0.5, -0.75, -1.0, -1.25, -1.5):
    w, hw, pu, hl, lo = d[f"ah_{line:+.2f}"]
    print(f"  让球 主{line:+.2f}  赢 {w:.1%}  赢半 {hw:.1%}  走 {pu:.1%}  输半 {hl:.1%}  输 {lo:.1%}")
print(f"  公平盘口（最接近五五开）主 {d['ah_fair_line']:+.2f}")
print("  最可能比分 " + "  ".join(f"{s['score']} {s['prob']:.1%}" for s in d["top5_scores"]))

inv = 1 / np.array([fx.avg_h, fx.avg_d, fx.avg_a]); mk = inv / inv.sum()
print("\n【8】与市场赔率对照（市场含伤停/首发等模型不知道的信息）")
print(f"  市场     主胜 {mk[0]:.1%}  平 {mk[1]:.1%}  客胜 {mk[2]:.1%}")
diff = np.array([ph, pdr, pa]) - mk
print(f"  模型−市场 {diff[0]:+.1%}  {diff[1]:+.1%}  {diff[2]:+.1%}"
      + ("   ← 分歧较大，优先查伤停/阵容" if np.abs(diff).max() > 0.06 else "   分歧不大"))

P = np.array([ph, pdr, pa]); lab = ["主胜", "平", "客胜"]; o = P.argsort()[::-1]
tier, h1, h2 = confidence_tier(P.max())
print("\n【9】结论")
print(f"  倾向 {lab[o[0]]}（{P[o[0]]:.1%}），双选 {_double_label([["home_win", "draw", "away_win"][i] for i in o[:2]])}（{P[o[0]] + P[o[1]]:.1%}）")
print(f"  信心 {tier}：历史上这一档首选命中 {h1:.0%}，双选命中 {h2:.0%}")
print(f"  预期总进球 {lh + la:.2f}，{'倾向大 2.5' if d['over_2.5'] > 0.5 else '倾向小 2.5'}（{max(d['over_2.5'], d['under_2.5']):.1%}）")
