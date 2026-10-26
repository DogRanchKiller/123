"""亚盘「把握线」研究（research.db，只读）：市场隐含比分矩阵在【市场线以外】的亚盘线上，
等效赢盘概率是否仍然校准；以及「从市场线向选择方让步，直到赢盘概率 ≥ T」得到的把握线命中如何。
样本、命中定义与 ah_baseline.py 相同：1213–2425 标定，2526 留出；赢 / 赢半 记中，输 / 输半 记不中，走盘不计。
同时给胜平负（Shin 去水最大概率）在同一批场次上的分档命中，作为「重点标记」的对照。
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python -u _diag/explore/ah_confidence_line.py > _diag/explore/ah_confidence_line.log
"""
import numpy as np
import pandas as pd

from football_prediction.model_market.devig import shin
from football_prediction.model_market.implied import implied_matrix
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf

from _diag.explore.ah_baseline import HOLDOUT, load

OFFSETS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)   # 相对市场线（主队方向）
CAL_BINS = (0.0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 1.01)
TARGETS = (0.60, 0.65, 0.70)
MAX_STEPS = 8                                                     # 最多让 2 球


def hit_of(hg: int, ag: int, line: float) -> float | None:
    """主队按 line 的实际结果：1 赢 / 赢半，0 输 / 输半，走盘 None。"""
    res = ah_outcome({int(hg - ag): 1.0}, line)
    k = max(res, key=res.get)
    return None if k == "push" else float(k in ("win", "half_win"))


def rows(df: pd.DataFrame):
    for r in df.itertuples():
        od = {"h": r.avg_h, "d": r.avg_d, "a": r.avg_a, "over": r.avg_over25,
              "under": r.avg_under25, "ah_line": r.ah_line, "ah_h": r.avg_ahh, "ah_a": r.avg_aha}
        got = implied_matrix(od, -0.05)
        if got is None:
            continue
        pmf = margin_pmf(got[0])
        cal = []
        for off in OFFSETS:                                          # 各线上主队方向的校准样本
            line = r.ah_line + off
            cal.append((off, ah_fair_prob(ah_outcome(pmf, line)), hit_of(r.hg, r.ag, line)))
        fair0 = ah_fair_prob(ah_outcome(pmf, r.ah_line))
        home = fair0 >= 0.5
        step = 0.25 if home else -0.25                               # 向选择方让步
        conf = {}
        for t in TARGETS:
            for k in range(MAX_STEPS + 1):
                line = r.ah_line + k * step
                f = ah_fair_prob(ah_outcome(pmf, line))
                p = f if home else 1 - f
                if p >= t:
                    h = hit_of(r.hg, r.ag, line)
                    conf[t] = (k, p, None if h is None else (h if home else 1 - h))
                    break
            else:
                conf[t] = (None, None, None)
        ps = shin([r.avg_h, r.avg_d, r.avg_a])
        res1x2 = 0 if r.hg > r.ag else 1 if r.hg == r.ag else 2
        yield {"season": r.season, "cal": cal, "conf": conf, "pmax": float(max(ps)),
               "hit1x2": float(int(np.argmax(ps)) == res1x2)}


def calibration(d: list[dict], name: str) -> None:
    print(f"\n== {name}：各亚盘线上主队等效赢盘概率 vs 实际（相对市场线 −1 … +1，走盘不计）")
    for off in OFFSETS:
        pts = [(p, h) for x in d for o, p, h in x["cal"] if o == off and h is not None]
        p, h = np.array(pts).T
        print(f"  偏移 {off:+.2f}  n={len(p):>6}  平均概率 {p.mean():.3f}  实际 {h.mean():.3f}  "
              f"差 {h.mean() - p.mean():+.3f}")
    pts = np.array([(p, h) for x in d for o, p, h in x["cal"] if o != 0 and h is not None])
    b = pd.cut(pts[:, 0], CAL_BINS, right=False)
    t = pd.DataFrame({"p": pts[:, 0], "h": pts[:, 1], "b": b}).groupby("b", observed=True)
    print("  市场线以外合并分箱：")
    for k, g in t:
        se = np.sqrt(g.h.mean() * (1 - g.h.mean()) / len(g))
        print(f"    {str(k):<14} n={len(g):>6}  平均概率 {g.p.mean():.3f}  实际 {g.h.mean():.3f}±{se:.3f}")


def conf_line(d: list[dict], name: str) -> None:
    print(f"\n== {name}：把握线（从市场线向选择方每次让 0.25，直到赢盘概率 ≥ T，最多 2 球）")
    for t in TARGETS:
        c = [x["conf"][t] for x in d]
        found = [x for x in c if x[0] is not None]
        h = [x for x in found if x[2] is not None]
        steps = pd.Series([x[0] for x in found]).value_counts().sort_index()
        hit, p = np.mean([x[2] for x in h]), np.mean([x[1] for x in h])
        se = np.sqrt(hit * (1 - hit) / len(h))
        print(f"  T={t:.2f}  找到 {len(found)}/{len(c)}  平均概率 {p:.3f}  实际命中 {hit:.3f}±{se:.3f}"
              f"（不含走盘 n={len(h)}）  让步步数 {steps.to_dict()}")


def tiers_1x2(d: list[dict], name: str) -> None:
    print(f"\n== {name}：胜平负首选命中（Shin 最大概率分档，与 MARKET_TIERS 相同下限）")
    df = pd.DataFrame({"p": [x["pmax"] for x in d], "h": [x["hit1x2"] for x in d]})
    for lo, hi, tag in ((0.60, 1.01, "高"), (0.45, 0.60, "中"), (0.0, 0.45, "低")):
        g = df[(df.p >= lo) & (df.p < hi)]
        se = np.sqrt(g.h.mean() * (1 - g.h.mean()) / len(g))
        print(f"  {tag}  n={len(g):>6}（{len(g) / len(df):.1%}）  平均概率 {g.p.mean():.3f}  "
              f"实际 {g.h.mean():.3f}±{se:.3f}")


def main():
    df = load()
    d = list(rows(df))
    cal_d = [x for x in d if x["season"] != HOLDOUT]
    hold = [x for x in d if x["season"] == HOLDOUT]
    print(f"样本 {len(d)} 场；标定 {len(cal_d)}，留出 {HOLDOUT} {len(hold)}")
    for part, name in ((cal_d, "标定 1213–2425"), (hold, f"留出 {HOLDOUT}")):
        calibration(part, name)
        conf_line(part, name)
        tiers_1x2(part, name)


if __name__ == "__main__":
    main()
