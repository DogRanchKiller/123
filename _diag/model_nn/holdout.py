"""model_nn 的 G1 留出：按 _diag/model_nn/prereg.md 里登记的检验，在冻结副本的 2526 上各跑一次。
口径与选参相同（evaluate.py），候选每月 1 日重训，训练历史从 2122 起；对照与配置都从 prereg.md 的 toml 块读，
本文件不另写一份。判定：同场 1X2 log loss 差值 + z×SE < 0 才算通过；Brier、比分、亚盘与按联赛 / 按月的结果只作描述。

运行前检查（任一不满足就退出，不评估）：
  - prereg.md 已提交，且它、model_nn 包、evaluate.py、本文件在工作区里都没有未提交的改动；
  - 冻结副本的 md5、FEATURES_VER、model_nn 的 LAYER_VERSION 与 prereg.md 一致；
  - holdout.log 里已有结果的检验不再跑（每个检验只跑一次；中途失败的检验没有结果，可以补跑）。
用法（仓库根目录）：
  PYTHONPATH=. .venv-ml/bin/python -u _diag/model_nn/holdout.py --smoke   # 只核对代码能跑：2425 前两个月，不打印指标
  PYTHONPATH=. .venv-ml/bin/python -u _diag/model_nn/holdout.py           # 正式留出，结果追加到 holdout.log
"""
import sys

# 同目录的 select.py 与标准库 select 同名：先把脚本目录移出 sys.path（同 select.py）
sys.path = [p for p in sys.path if p != "" and not p.endswith("_diag/model_nn")]

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

_spec = importlib.util.spec_from_file_location("nn_evaluate", Path(__file__).with_name("evaluate.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

from football_prediction import version  # noqa: E402
from football_prediction.model_nn.dataset import FEATURES_VER  # noqa: E402
from football_prediction.model_nn.model import FIVE, SIX  # noqa: E402
from football_prediction.model_nn.train import TrainConfig  # noqa: E402

PREREG = Path("_diag/model_nn/prereg.md")
LOG = Path("_diag/model_nn/holdout.log")
GUARDED = ["_diag/model_nn/prereg.md", "_diag/model_nn/evaluate.py", "_diag/model_nn/holdout.py",
           "football_prediction/model_nn"]
GROUPS = {"five": FIVE, "six": SIX}


def load_prereg() -> dict:
    """prereg.md 里唯一的 ```toml 块。"""
    m = re.findall(r"```toml\n(.*?)```", PREREG.read_text(encoding="utf-8"), re.S)
    if len(m) != 1:
        sys.exit("prereg.md 里应当正好有一个 toml 块")
    return tomllib.loads(m[0])


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def guard(reg: dict) -> str:
    sha = git("log", "-1", "--format=%h", "--", str(PREREG))
    if not sha:
        sys.exit("prereg.md 还没有提交，不能跑留出")
    dirty = git("status", "--porcelain", "--", *GUARDED)
    if dirty:
        sys.exit("下面的文件有未提交的改动，先提交再跑：\n" + dirty)
    checks = {"副本 md5": (ev.md5(reg["frozen"]["path"]), reg["frozen"]["md5"]),
              "FEATURES_VER": (FEATURES_VER, reg["frozen"]["features_ver"]),
              "model_nn LAYER_VERSION": (version.get("model_nn"), reg["frozen"]["layer_version"])}
    for k, (got, want) in checks.items():
        if got != want:
            sys.exit(f"{k} 与 prereg.md 不一致：{got} != {want}")
    return sha


def done_tests() -> set[str]:
    if not LOG.exists():
        return set()
    return set(re.findall(r"^RESULT (T\d)", LOG.read_text(encoding="utf-8"), re.M))


def config_of(t: dict) -> TrainConfig:
    kw = dict(t["config"])
    kw["hidden"] = tuple(kw["hidden"])
    return TrainConfig(**kw)


def run_test(conn, t: dict, season: str, smoke: bool, out, db_md5: str) -> None:
    cfg = config_of(t)
    table = ev.tables(conn, GROUPS[t["group"]])
    test = table[table["season"] == season].sort_values(["match_date", "match_id"])
    if smoke:
        test = test[test["match_date"] < test["match_date"].min()[:5] + "10-01"]
    if t["baseline"] == "market_implied":
        base = ev.market_rows(test)
    else:
        daily = t["dc_market_refit"] == "daily"
        tag = f"{db_md5[:8]}_{season}_{t['group']}" + ("_smoke" if smoke else "")
        base = ev.dc_market_rows(conn, test, tag, daily)
    t0 = time.time()
    rows, info = ev.candidate_rows(table, test, cfg)
    ev.log_eval(db_md5, rows, f"{'smoke ' if smoke else 'holdout '}{t['id']} {cfg.name()} vs {t['baseline']}")
    if smoke:
        print(f"  {t['id']} smoke ok：候选 {len(rows)} 场、对照 {len(base)} 场、{info['fits']} 次拟合、"
              f"{time.time() - t0:.0f} s（不打印指标）")
        return
    c = ev.compare(rows, base)
    ll, z = c["log_loss"], float(t["z"])
    bound = ll["diff"] + z * ll["se"]
    out(f"RESULT {t['id']} {'PASS' if bound < 0 else 'FAIL'} | {t['group']} {season} | {cfg.name()} vs {t['baseline']}"
        f" | n={ll['n']} | Δ1X2 LL {ll['diff']:+.5f} SE {ll['se']:.5f} z {z:.2f} | 差值+z×SE {bound:+.5f}")
    out("  参考（不参与判定）：" + "  ".join(f"Δ{k} {c[k]['diff']:+.5f}±{c[k]['se']:.5f} (n={c[k]['n']})"
                                    for k in ("brier", "score_ll", "ah_ll")))
    out(f"  候选 1X2 LL {rows.log_loss.mean():.5f}，对照 {base.log_loss.mean():.5f}；平均轮数 {info['epochs']:.1f}，"
        f"{info['fits']} 次拟合，训练 {info['seconds']} s，总用时 {time.time() - t0:.0f} s，峰值 {ev.peak_mb():.0f} MB，"
        f"{info['device']}")
    by = rows.merge(base[["match_id", "log_loss"]], on="match_id", suffixes=("", "_b"))
    by = by.assign(d=by.log_loss - by.log_loss_b, month=by.match_date.str[:7])
    for key, label in (("league", "按联赛"), ("month", "按月")):
        g = by.groupby(key)["d"].agg(["count", "mean"])
        out(f"  {label}（只作描述）" + "  ".join(f"{k} {r['mean']:+.4f}({int(r['count'])})" for k, r in g.iterrows()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="2425 前两个月，只核对代码能跑，不打印指标、不写 holdout.log")
    a = ap.parse_args()
    reg = load_prereg()
    season = "2425" if a.smoke else reg["holdout"]["season"]
    db_md5 = ev.md5(reg["frozen"]["path"])
    conn = ev.open_frozen(reg["frozen"]["path"])

    def out(line: str) -> None:
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    if a.smoke:
        for t in reg["tests"]:
            run_test(conn, t, season, True, out, db_md5)
        return
    sha = guard(reg)
    done = done_tests()
    todo = [t for t in reg["tests"] if t["id"] not in done]
    out(f"\n## {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  prereg 提交 {sha}  当前 {ev.commit()}  "
        f"副本 {db_md5}  留出 {season}  m={len(reg['tests'])}" + (f"  已有结果、跳过 {sorted(done)}" if done else ""))
    for t in todo:
        run_test(conn, t, season, False, out, db_md5)


if __name__ == "__main__":
    main()
