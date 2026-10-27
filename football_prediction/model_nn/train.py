"""
model_nn/train.py  v0.1.0
训练循环。配置（含种子）是 TrainConfig，开训时打印。
  早停只用训练集内部按时间切出来的最后 val_days 天（cutoff 之前），不用被评估的月份。
  refit=True 时再用全部训练样本按早停选出的轮数重训一遍（同一种子），让最近的比赛也进模型。
  标准化的均值 / 方差只用参与训练的样本。训练不调 save_prediction，不写任何比赛库。
  模块顶层不 import torch。
修改此文件后请同步更新 version.py 中 "model_nn" 的版本号。
"""
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from football_prediction.model_nn.dataset import feature_columns
from football_prediction.model_nn.net import build_net, dc_nll, inv_softplus

LAYER_VERSION = "0.1.0"


@dataclass(frozen=True)
class TrainConfig:
    variant: str = "A"                  # A 无赔率；B 带赔率，学市场残差
    feature_set: str = "full"           # full 含 xG；no_xg
    hidden: tuple[int, ...] = (64, 32)
    dropout: float = 0.1
    weight_decay: float = 1e-4
    lr: float = 1e-3
    batch_size: int = 256
    max_epochs: int = 200
    patience: int = 15
    val_days: int = 120                 # 早停用的最后一段（天）
    refit: bool = True
    first_season: str = "2122"          # 训练窗口：从这一季起全量（与实盘一致）
    pool: str = "group"                 # group：同一联赛组合并训练；league：分联赛
    seed: int = 0
    device: str = "cpu"                 # cpu / mps / cuda / auto

    def name(self) -> str:
        h = "-".join(map(str, self.hidden))
        return (f"{self.variant}/{self.feature_set} h{h} d{self.dropout} wd{self.weight_decay:g} "
                f"lr{self.lr:g} {self.pool} s{self.seed}")


def resolve_device(name: str) -> str:
    import torch
    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def training_rows(table: pd.DataFrame, cfg: TrainConfig, cutoff_date: str) -> pd.DataFrame:
    """窗口规则：first_season 起、match_date < cutoff；变体 B 只要有赛前 1X2 赔率的场次。"""
    t = table[(table["match_date"] < cutoff_date) & (table["season"] >= cfg.first_season)]
    if cfg.variant == "B":
        t = t[t["mk_lam_h"].notna()]
    return t.sort_values(["match_date", "match_id"])


class Fitted:
    """训练好的网络 + 标准化参数；predict 返回 numpy 的 (λ主, λ客) 与 rho。"""

    def __init__(self, net, cfg: TrainConfig, cols: list[str], mu, sd, epochs: int, info: dict):
        self.net, self.cfg, self.cols, self.mu, self.sd = net, cfg, cols, mu, sd
        self.epochs, self.info = epochs, info

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float]:
        import torch
        x, base = _tensors(df, self.cols, self.mu, self.sd, self.cfg, "cpu")
        self.net.eval()
        with torch.no_grad():
            lh, la, rho = self.net.to("cpu")(x, base)
        return lh.detach().cpu().numpy(), la.detach().cpu().numpy(), float(rho.detach().cpu())


def _tensors(df, cols, mu, sd, cfg, device):
    import torch
    x = (df[cols].to_numpy(dtype=np.float64) - mu) / sd
    if not np.isfinite(x).all():
        raise ValueError("特征里有 NaN / inf：" + ", ".join(c for c in cols if df[c].isna().any()))
    xt = torch.tensor(x, dtype=torch.float32, device=device)
    if cfg.variant != "B":
        return xt, None
    b = np.vectorize(inv_softplus)(df[["mk_lam_h", "mk_lam_a"]].to_numpy(dtype=np.float64))
    return xt, torch.tensor(b, dtype=torch.float32, device=device)


def _run(rows, val, cfg, cols, mu, sd, device, epochs=None):
    """训练一个网络；val 不为空时按 val 的平均 NLL 早停。返回 (net, 最佳轮数, val NLL)。"""
    import torch
    torch.manual_seed(cfg.seed)
    gen = torch.Generator().manual_seed(cfg.seed)
    x, base = _tensors(rows, cols, mu, sd, cfg, device)
    y = torch.tensor(rows[["home_goals", "away_goals"]].to_numpy(), device=device)
    init = (float(rows["home_goals"].mean()), float(rows["away_goals"].mean()))
    net = build_net(len(cols), cfg.hidden, cfg.dropout, cfg.variant, init).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    if val is not None and len(val):
        xv, bv = _tensors(val, cols, mu, sd, cfg, device)
        yv = torch.tensor(val[["home_goals", "away_goals"]].to_numpy(), device=device)
    best, best_ep, best_state, bad = float("inf"), 0, None, 0
    for ep in range(1, (epochs or cfg.max_epochs) + 1):
        net.train()
        for idx in torch.randperm(len(x), generator=gen).split(cfg.batch_size):
            idx = idx.to(device)
            lh, la, rho = net(x[idx], None if base is None else base[idx])
            loss = dc_nll(lh, la, rho, y[idx, 0], y[idx, 1]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        if epochs is not None or val is None or not len(val):
            continue
        net.eval()
        with torch.no_grad():
            v = float(dc_nll(*net(xv, bv), yv[:, 0], yv[:, 1]).mean())
        if v < best - 1e-6:
            best, best_ep, bad = v, ep, 0
            best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    return net, (epochs or best_ep or cfg.max_epochs), best


def train(table: pd.DataFrame, cfg: TrainConfig, cutoff_date: str, verbose: bool = True) -> Fitted:
    """在 table（可多联赛拼接）里 match_date < cutoff_date 的样本上训练。"""
    t0 = time.time()
    if verbose:
        print(f"  训练配置 {asdict(cfg)}  cutoff={cutoff_date}", flush=True)
    device = resolve_device(cfg.device)
    cols = feature_columns(cfg.feature_set, cfg.variant)
    rows = training_rows(table, cfg, cutoff_date)
    if len(rows) < 200:
        raise ValueError(f"训练样本只有 {len(rows)} 场")
    split = (date.fromisoformat(cutoff_date) - timedelta(days=cfg.val_days)).isoformat()
    fit_rows, val = rows[rows["match_date"] < split], rows[rows["match_date"] >= split]
    mu = fit_rows[cols].to_numpy(dtype=np.float64).mean(0)
    sd = fit_rows[cols].to_numpy(dtype=np.float64).std(0) + 1e-6
    net, ep, v = _run(fit_rows, val, cfg, cols, mu, sd, device)
    if cfg.refit:
        mu = rows[cols].to_numpy(dtype=np.float64).mean(0)
        sd = rows[cols].to_numpy(dtype=np.float64).std(0) + 1e-6
        net, _, _ = _run(rows, None, cfg, cols, mu, sd, device, epochs=max(ep, 1))
    info = {"n_train": len(rows), "n_val": len(val), "val_nll": v, "epochs": ep,
            "seconds": round(time.time() - t0, 1), "device": device}
    return Fitted(net.to("cpu"), cfg, cols, mu, sd, ep, info)
