"""
model_nn/net.py  v0.1.0
表格网络：特征 -> 主客队进球率 λ（softplus，恒为正）和一个 Dixon-Coles rho。
  变体 A：λ = softplus(f(x))，输出层偏置初始化为联赛场均进球。
  变体 B：λ = softplus(softplus⁻¹(市场 λ) + f(x))，输出层初始化为 0，起点就是市场，学市场之外的残差。
  损失：实际比分在 DC 比分矩阵（0..MAX_GOALS，归一化，与 model_market.implied.dc_matrix 同算法）上的负对数似然。
  模块顶层不 import torch（docs/ml-stack.md）：类和损失在函数里构造。
修改此文件后请同步更新 version.py 中 "model_nn" 的版本号。
"""
import math

LAYER_VERSION = "0.1.0"
MAX_GOALS = 8               # 与 model_market.implied.MAX_GOALS 相同；更多进球按 8 计
RHO_BOUND = 0.25            # rho = 0.25·tanh(r)


def inv_softplus(y: float) -> float:
    return y + math.log(-math.expm1(-y))


def build_net(n_in: int, hidden: tuple[int, ...], dropout: float, variant: str,
              init_lam: tuple[float, float] = (1.5, 1.2)):
    """返回 torch.nn.Module：forward(x, base) -> (λ主, λ客, rho)。base 是市场 λ（变体 B），A 传 None。"""
    import torch
    from torch import nn

    class LambdaNet(nn.Module):
        def __init__(self):
            super().__init__()
            layers, d = [], n_in
            for h in hidden:
                layers += [nn.Linear(d, h), nn.GELU(), nn.Dropout(dropout)]
                d = h
            self.body = nn.Sequential(*layers)
            self.head = nn.Linear(d, 2)
            self.rho_raw = nn.Parameter(torch.tensor(-0.2))     # tanh(-0.2)·0.25 ≈ −0.05
            with torch.no_grad():
                if variant == "B":
                    self.head.weight.zero_()
                    self.head.bias.zero_()
                else:
                    self.head.weight.mul_(0.1)
                    self.head.bias.copy_(torch.tensor([inv_softplus(v) for v in init_lam]))

        def forward(self, x, base=None):
            z = self.head(self.body(x))
            if base is not None:
                z = z + base                                    # base 已是 softplus⁻¹(市场 λ)
            lam = nn.functional.softplus(z) + 1e-4
            return lam[:, 0], lam[:, 1], RHO_BOUND * torch.tanh(self.rho_raw)

    return LambdaNet()


def dc_nll(lam_h, lam_a, rho, hg, ag):
    """逐场负对数似然（张量）：归一化的 DC 比分矩阵上实际比分的 -log p。"""
    import torch
    g = torch.arange(MAX_GOALS + 1, dtype=lam_h.dtype, device=lam_h.device)
    lp_h = g * torch.log(lam_h)[:, None] - lam_h[:, None] - torch.lgamma(g + 1)
    lp_a = g * torch.log(lam_a)[:, None] - lam_a[:, None] - torch.lgamma(g + 1)
    logm = lp_h[:, :, None] + lp_a[:, None, :]                  # (n, G, G)
    tau = torch.ones_like(logm)
    tau[:, 0, 0] = 1 - lam_h * lam_a * rho
    tau[:, 0, 1] = 1 + lam_h * rho
    tau[:, 1, 0] = 1 + lam_a * rho
    tau[:, 1, 1] = 1 - rho
    logm = logm + torch.log(tau.clamp_min(1e-6))
    log_z = torch.logsumexp(logm.flatten(1), dim=1)
    i = hg.long().clamp(max=MAX_GOALS)
    j = ag.long().clamp(max=MAX_GOALS)
    return log_z - logm[torch.arange(len(i)), i, j]
