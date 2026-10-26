"""汇总 compute.py 的 rows_{lg}.csv：ahou / ah1x2h 对 base 的同场差值（负 = 变体更好；命中率差为正 = 变体更好）。
标定期 = 开球日期 < 2025-07-01（research.db 老五联赛 2425 及以前；新六联赛 2122–2425），留出 = 2526 起。
2000 年前的赛季代码按字符串会排在 2526 之后，所以按日期分段，不按赛季字符串。结果写 result.txt。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OLD = ["E0", "D1", "SP1", "I1", "F1"]
NEW = ["E1", "N1", "P1", "SC0", "B1", "T1"]
SPLIT = "2025-07-01"
METRICS = [("ll1", "1X2 LL"), ("llah", "亚盘 LL"), ("llou", "大小 LL"), ("hitah", "亚盘命中")]


def stat(d):
    d = np.asarray(d, float)
    d = d[~np.isnan(d)]
    se = d.std(ddof=1) / np.sqrt(len(d))
    return f"{d.mean():+.5f}±{se:.5f}{'*' if abs(d.mean()) > 2 * se else ' '}", len(d)


def block(df, label):
    out = [f"{label}（n={len(df)}；* = |差| > 2SE）"]
    if len(df) < 2:
        return out
    base = "  ".join(f"{t}={df[f'base_{k}'].mean():.4f}" for k, t in METRICS)
    out.append(f"  base 平均：{base}")
    for v in ("ahou", "ah1x2h"):
        cells = []
        for k, t in METRICS:
            s, n = stat(df[f"{v}_{k}"] - df[f"base_{k}"])
            cells.append(f"{t} {s}" + (f"(n={n})" if k == "hitah" else ""))
        out.append(f"  {v:<7}− base：" + "  ".join(cells))
    return out


def main():
    lgs = [lg for lg in OLD + NEW if (HERE / f"rows_{lg}.csv").exists()]
    df = pd.concat([pd.read_csv(HERE / f"rows_{lg}.csv", dtype={"season": str}) for lg in lgs])
    out = [f"只用亚盘 + 大小球反推 vs 现行（1X2 + 大小 + 亚盘）；联赛：{' '.join(lgs)}", ""]
    for name, part in (("标定期", df.match_date < SPLIT), ("留出期", df.match_date >= SPLIT)):
        d = df[part]
        out += [f"== {name} ==", *block(d, "全部")]
        out += block(d[d.league.isin(OLD)], "老五联赛（research.db）")
        out += block(d[d.league.isin(NEW)], "新六联赛（football.db）")
        out.append("")
    out.append("== 按联赛（全时段，亚盘 LL：ahou − base）==")
    for lg in lgs:
        s, n = stat((df.ahou_llah - df.base_llah)[df.league == lg])
        out.append(f"  {lg:<4} n={n:>5}  {s}")
    text = "\n".join(out)
    (HERE / "result.txt").write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
