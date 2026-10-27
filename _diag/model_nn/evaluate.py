"""model_nn 的按月评估（select.py 选参、holdout.py 留出共用）。只读打开冻结副本，不写任何比赛库。
口径（docs/agent-plan.md 9.1）：
  候选：每月 cutoff = 该月 1 日，用 match_date < cutoff 的样本训练（窗口规则见 TrainConfig），预测该月的场次；
        每场特征按它自己的日期算好（样本表），同一个月的网络权重不变。
  dc_market：每个联赛每月 cutoff = 该联赛该月第一场的日期，与 run_backtest(refit_freq="monthly") 同一组拟合；
        取未取整的 score_matrix。该联赛 1 日到首场之间没有比赛，所以候选用的本联赛样本与它相同。
        daily=True 时每个比赛日重拟合（留出用这一种，见 prereg.md）。
  market_implied：同一行的赛前平均赔率反推 λ（rho = DEFAULT_RHO），不拟合，不用收盘价。
  指标：1X2 log loss / Brier（validation.backtest 的函数）、比分 log loss、亚盘五种结算 log loss（该场赛前市场线），
        同场差值 ± SE 用 paired_compare。
"""
import contextlib
import hashlib
import io
import resource
import sqlite3
import subprocess
from datetime import datetime, timezone
from math import log
from pathlib import Path

import numpy as np
import pandas as pd

from football_prediction.model_dc.market_dc import MarketDixonColesModel
from football_prediction.model_market.implied import dc_matrix
from football_prediction.model_nn.dataset import build_table
from football_prediction.model_nn.model import NNModel
from football_prediction.output.derive import ah_outcome, margin_pmf
from football_prediction.review.store import ah_settle
from football_prediction.validation.backtest import _brier_one, _log_loss_one, _outcome, paired_compare

FROZEN = "checkpoints/g1/football_20261027.db"
OUT = Path("checkpoints/nn_eval")
EVAL_LOG = Path("_diag/model_nn/eval_log.md")
METRICS = ("log_loss", "brier", "score_ll", "ah_ll")


def open_frozen(path: str = FROZEN) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def md5(path: str = FROZEN) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "football_prediction/model_nn", "_diag/model_nn"],
                           capture_output=True, text=True).stdout.strip()
    return head + ("+dirty" if dirty else "")


def tables(conn, leagues) -> pd.DataFrame:
    return pd.concat([build_table(conn, lg) for lg in leagues], ignore_index=True)


def metrics(m: np.ndarray, hg: int, ag: int, line) -> dict:
    p = {"home_win": float(np.tril(m, -1).sum()), "draw": float(np.trace(m)),
         "away_win": float(np.triu(m, 1).sum())}
    actual = _outcome(hg, ag)
    n = m.shape[0] - 1
    out = {"p_home_win": p["home_win"], "p_draw": p["draw"], "p_away_win": p["away_win"],
           "log_loss": _log_loss_one(p, actual), "brier": _brier_one(p, actual),
           "score_ll": -log(max(float(m[min(hg, n), min(ag, n)]), 1e-7)), "ah_ll": np.nan}
    if line is not None and line == line:
        o = ah_outcome(margin_pmf(m), float(line))
        out["ah_ll"] = -log(max(o[ah_settle(hg - ag, float(line))], 1e-7))
    return out


def _row(r, m) -> dict:
    return {"match_id": r["match_id"], "league": r["league"], "season": r["season"],
            "match_date": r["match_date"]} | metrics(m, int(r["home_goals"]), int(r["away_goals"]), r["ah_line"])


def market_rows(test: pd.DataFrame) -> pd.DataFrame:
    t = test[test["mk_lam_h"].notna()]
    return pd.DataFrame([_row(r, dc_matrix(r["mk_lam_h"], r["mk_lam_a"])) for r in t.to_dict("records")])


def dc_market_rows(conn, test: pd.DataFrame, tag: str, daily: bool = False) -> pd.DataFrame:
    """dc_market 基准。默认按联赛-月重拟合（同 run_backtest monthly）；daily=True 每个比赛日重拟合，
    与候选逐场更新的特征时效对齐（同日比赛互不可见）。"""
    path = OUT / f"dc_market_{tag}{'_daily' if daily else ''}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    rows = []
    key = test["match_date"] if daily else test["match_date"].str[:7]
    for (lg, _), g in test.groupby([test["league"], key]):
        mdl = MarketDixonColesModel()
        with contextlib.redirect_stdout(io.StringIO()):
            mdl.fit(conn, lg, g["match_date"].min())
        rows += [_row(r, mdl.score_matrix(r["home_team"], r["away_team"])) for r in g.to_dict("records")]
    out = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def candidate_rows(table: pd.DataFrame, test: pd.DataFrame, cfg) -> tuple[pd.DataFrame, dict]:
    """逐月训练、预测。返回逐场指标与训练信息（每月轮数、用时）。"""
    rows, info = [], []
    for month, g in test.groupby(test["match_date"].str[:7]):
        cutoff = f"{month}-01"
        if cfg.variant == "B":
            g = g[g["mk_lam_h"].notna()]
        groups = [(table, g)] if cfg.pool == "group" else \
            [(table[table["league"] == lg], gg) for lg, gg in g.groupby("league")]
        for tab, gg in groups:
            mdl = NNModel(cfg)
            mdl.fit_table(tab, cutoff)
            lh, la, rho = mdl.predict_rows(gg)
            info.append(mdl.fitted.info | {"cutoff": cutoff})
            rows += [_row(r, dc_matrix(float(h), float(a), rho))
                     for r, h, a in zip(gg.to_dict("records"), lh, la)]
    return pd.DataFrame(rows), {"epochs": float(np.mean([i["epochs"] for i in info])),
                                "seconds": round(sum(i["seconds"] for i in info), 1),
                                "device": info[0]["device"], "fits": len(info)}


def compare(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    out = {}
    for k in METRICS:
        x, y = a.dropna(subset=[k]), b.dropna(subset=[k])
        out[k] = paired_compare(x, y, k)
    return out


def peak_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 2**20 if r > 2**24 else r / 1024      # macOS 是字节，Linux 是 KB


def log_eval(db_md5: str, test: pd.DataFrame, config: str) -> None:
    """eval_log.md 追加一行：副本 md5、日期范围、配置、提交号。"""
    if not EVAL_LOG.exists():
        EVAL_LOG.write_text("# model_nn 评估记录\n\n每次评估一行（docs/agent-plan.md 9.1）。"
                            "新留出集登记前用它证明范围不重叠。\n\n"
                            "| 时间（UTC） | 副本 md5 | 日期范围 | 联赛 | 配置 | 提交 |\n|---|---|---|---|---|---|\n",
                            encoding="utf-8")
    t = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    rng = f"{test['match_date'].min()} – {test['match_date'].max()}"
    lgs = ",".join(sorted(test["league"].unique()))
    with EVAL_LOG.open("a", encoding="utf-8") as f:
        f.write(f"| {t} | {db_md5} | {rng} | {lgs} | {config} | {commit()} |\n")
