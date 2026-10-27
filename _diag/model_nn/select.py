"""model_nn 选参：只在 2425 上按月评估，训练历史从 2122 起，五联赛，冻结副本只读。
不碰 2526（脚本里断言）。每个配置：同场对 dc_market（变体 A）和 market_implied（变体 B）的差值 ± SE，
以及另一个基准的差值作参考。结果追加到 _diag/model_nn/select.log，每次评估在 eval_log.md 记一行。
用法（仓库根目录）：
  PYTHONPATH=. .venv-ml/bin/python -u _diag/model_nn/select.py A            # 变体 A 的 48 个配置（B 同理），种子 0
  PYTHONPATH=. .venv-ml/bin/python -u _diag/model_nn/select.py one variant=B feature_set=no_xg seed=1 ...
  ... select.py one ... base=daily   # 诊断：dc_market 每个比赛日重拟合（默认按月）
  ... select.py one variant=B ... mask=all|team   # 诊断：输入全置 0（只校准市场 λ 与 rho）/ 只留市场列
逐场结果在 checkpoints/nn_eval/（gitignore）。
"""
import sys

# 本文件名与标准库 select 同名：先把脚本目录移出 sys.path，否则 subprocess 等会导入到这里
_HERE = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path = [p for p in sys.path if p not in ("", _HERE) and not p.endswith("_diag/model_nn")]

import importlib.util  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from itertools import product  # noqa: E402
from pathlib import Path  # noqa: E402

_spec = importlib.util.spec_from_file_location("nn_evaluate", Path(__file__).with_name("evaluate.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

from football_prediction.model_nn.model import FIVE  # noqa: E402
from football_prediction.model_nn.train import TrainConfig  # noqa: E402

SEASON = "2425"
LOG = Path("_diag/model_nn/select.log")


def grid(variant: str) -> list[TrainConfig]:
    """一个变体的网格：特征集 × 结构 × 权重衰减 × dropout × 学习率，种子 0（48 个）。"""
    return [TrainConfig(variant=variant, feature_set=f, hidden=h, weight_decay=wd, dropout=d, lr=lr)
            for f, h, wd, d, lr in product(("full", "no_xg"), ((32,), (64, 32), (128, 64)),
                                           (1e-4, 1e-2), (0.1, 0.3), (1e-3, 3e-4))]


def parse(args: list[str]) -> TrainConfig:
    kw = {}
    for a in args:
        k, v = a.split("=", 1)
        cur = getattr(TrainConfig(), k)
        kw[k] = (tuple(int(x) for x in v.split("-")) if isinstance(cur, tuple)
                 else type(cur)(v) if not isinstance(cur, bool) else v == "True")
    return TrainConfig(**kw)


def out(line: str) -> None:
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fmt(c: dict) -> str:
    return f"{c['diff']:+.5f}±{c['se']:.5f}"


def masked(table, cfg: TrainConfig, mask: str):
    """诊断：mask=all 把全部输入置 0（B 只能学偏置和 rho，即只校准市场 λ）；mask=team 只留市场列。"""
    from football_prediction.model_nn.dataset import MARKET_COLS, feature_columns
    cols = [c for c in feature_columns(cfg.feature_set, cfg.variant)
            if mask == "all" or c not in MARKET_COLS]
    return table.assign(**{c: 0.0 for c in cols})


def main(cfgs: list[TrainConfig], mask: str = "", daily: bool = False) -> None:
    db_md5 = ev.md5()
    conn = ev.open_frozen()
    table = ev.tables(conn, FIVE)
    if mask:
        table = masked(table, cfgs[0], mask)
    test = table[table["season"] == SEASON].sort_values(["match_date", "match_id"])
    assert test["match_date"].max() < "2025-07-01" and set(test["season"]) == {SEASON}, "选参只用 2425"
    base = {"dc_market": ev.dc_market_rows(conn, test, f"{db_md5[:8]}_{SEASON}", daily),
            "market_implied": ev.market_rows(test)}
    out(f"\n## {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  副本 {db_md5}  提交 {ev.commit()}  "
        f"测试 {SEASON} 五联赛 {len(test)} 场" + ("  dc_market 逐比赛日重拟合" if daily else ""))
    for k, b in base.items():
        out(f"  基准 {k}: n={len(b)} 1X2 LL {b.log_loss.mean():.5f}  Brier {b.brier.mean():.5f}  "
            f"比分 LL {b.score_ll.mean():.5f}  亚盘 LL {b.ah_ll.mean():.5f}")
    ev.log_eval(db_md5, test, "baselines dc_market / market_implied")
    out("  配置 | n | 1X2 LL | Δ1X2 对主对照 | Δ1X2 对另一基准 | ΔBrier | Δ比分 LL | Δ亚盘 LL | 轮数 | 用时 s | 峰值 MB")
    for cfg in cfgs:
        t0 = time.time()
        rows, info = ev.candidate_rows(table, test, cfg)
        own, other = ("market_implied", "dc_market") if cfg.variant == "B" else ("dc_market", "market_implied")
        c, o = ev.compare(rows, base[own]), ev.compare(rows, base[other])
        out(f"  {cfg.name()}{' mask=' + mask if mask else ''} | {len(rows)} | {rows.log_loss.mean():.5f} | {fmt(c['log_loss'])} (n={c['log_loss']['n']}) | "
            f"{fmt(o['log_loss'])} | {fmt(c['brier'])} | {fmt(c['score_ll'])} | {fmt(c['ah_ll'])} | "
            f"{info['epochs']:.0f} | {time.time() - t0:.0f} | {ev.peak_mb():.0f}")
        ev.OUT.mkdir(parents=True, exist_ok=True)
        tag = (cfg.name() + (f" mask={mask}" if mask else "")).replace("/", "_").replace(" ", "_")
        rows.to_parquet(ev.OUT / f"select_{tag}.parquet", index=False)
        ev.log_eval(db_md5, rows, cfg.name() + (f" mask={mask}" if mask else ""))
        by = rows.merge(base[own][["match_id", "log_loss"]], on="match_id", suffixes=("", "_b"))
        per = by.assign(d=by.log_loss - by.log_loss_b).groupby("league")["d"].agg(["count", "mean"])
        out("    按联赛（只作描述） " + "  ".join(f"{lg} {r['mean']:+.4f}({int(r['count'])})" for lg, r in per.iterrows()))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "A"
    daily = "base=daily" in sys.argv
    args = [a for a in sys.argv[2:] if not a.startswith(("mask=", "base="))]
    mask = next((a.split("=", 1)[1] for a in sys.argv[2:] if a.startswith("mask=")), "")
    main(grid(mode) if mode in ("A", "B") else [parse(args)], mask, daily)
