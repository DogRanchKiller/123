"""
model_market/implied.py  v1.0.0
市场反推比分模型：用 胜平负 + 大小2.5 + 亚盘 三组盘口（去水后）反推两队预期进球 λ主/λ客，
再套 Dixon-Coles 比分矩阵（rho 取联赛模型拟合值），得到与市场一致的比分、大小球、让球分布。
  拟合：最小化 Σ(模型推导概率 − 市场去水概率)²，对 log λ 两参数用 Nelder-Mead。
  缺大小球或亚盘时只用可得的盘口；缺胜平负时返回 None（由调用方回退到 dc_xg）。
  去水方法由 method 参数选（model_market/devig.py），默认按比例，与 1.0.0 存档完全一致；
  method="shin" 的结果以 market_shin / model_market_shin 版本另行存档。
修改此文件后请同步更新 version.py 中 "model_market"（及 "model_market_shin"）的版本号。
"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from football_prediction.model_market.devig import devig
from football_prediction.output.derive import ah_fair_prob, ah_outcome, margin_pmf

LAYER_VERSION = "1.0.0"
MODEL_NAME = "market_implied"
MAX_GOALS = 8
DEFAULT_RHO = -0.05
_G = np.arange(MAX_GOALS + 1)


def dc_matrix(lam_h: float, lam_a: float, rho: float = DEFAULT_RHO) -> np.ndarray:
    """Dixon-Coles 比分矩阵（与 DixonColesModel.score_matrix 同算法）"""
    m = np.outer(poisson.pmf(_G, lam_h), poisson.pmf(_G, lam_a))
    m[0, 0] *= 1 - lam_h * lam_a * rho
    m[0, 1] *= 1 + lam_h * rho
    m[1, 0] *= 1 + lam_a * rho
    m[1, 1] *= 1 - rho
    return m / m.sum()


def _valid(*odds) -> bool:
    return all(o is not None and o == o and o > 1 for o in odds)


def fair_probs(odds: dict, method: str = "proportional") -> dict:
    """
    odds 键（均可缺）：h,d,a（胜平负）；over,under（大小2.5）；ah_line, ah_h, ah_a（亚盘线与主/客水位，欧赔）。
    返回去水概率：{"1x2": [ph,pd,pa], "over25": p, "ah": (line, p主赢盘)}
    """
    out = {}
    if _valid(odds.get("h"), odds.get("d"), odds.get("a")):
        out["1x2"] = devig([odds["h"], odds["d"], odds["a"]], method)
    if _valid(odds.get("over"), odds.get("under")):
        out["over25"] = float(devig([odds["over"], odds["under"]], method)[0])
    line = odds.get("ah_line")
    if line is not None and line == line and _valid(odds.get("ah_h"), odds.get("ah_a")):
        out["ah"] = (float(line), float(devig([odds["ah_h"], odds["ah_a"]], method)[0]))
    return out


def _implied(m: np.ndarray, fp: dict) -> list[tuple[float, float]]:
    """(模型概率, 市场概率) 对"""
    pairs = []
    if "1x2" in fp:
        mod = [np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()]
        pairs += list(zip(mod, fp["1x2"]))
    if "over25" in fp:
        tot = np.add.outer(_G, _G)
        pairs.append((m[tot > 2.5].sum(), fp["over25"]))
    if "ah" in fp:
        line, p = fp["ah"]
        pairs.append((ah_fair_prob(ah_outcome(margin_pmf(m), line)), p))
    return pairs


def fit_lambdas(odds: dict, rho: float = DEFAULT_RHO,
                method: str = "proportional") -> dict | None:
    """反推 λ；返回 {lam_h, lam_a, rmse, used}，缺胜平负返回 None。"""
    fp = fair_probs(odds, method)
    if "1x2" not in fp:
        return None
    ph, _, pa = fp["1x2"]
    tot0 = 2.6 + (fp["over25"] - 0.5) * 3 if "over25" in fp else 2.6
    sup0 = (ph - pa) * 2.0
    x0 = np.log(np.clip([(tot0 + sup0) / 2, (tot0 - sup0) / 2], 0.2, 5))

    def loss(x):
        lh, la = np.exp(np.clip(x, -3, 2))
        return sum((a - b) ** 2 for a, b in _implied(dc_matrix(lh, la, rho), fp))

    r = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-10})
    lh, la = np.exp(np.clip(r.x, -3, 2))
    n = len(_implied(dc_matrix(lh, la, rho), fp))
    return {"lam_h": float(lh), "lam_a": float(la), "rmse": float(np.sqrt(r.fun / n)),
            "used": [k for k in ("1x2", "over25", "ah") if k in fp]}


def implied_matrix(odds: dict, rho: float = DEFAULT_RHO,
                   method: str = "proportional") -> tuple[np.ndarray, dict] | None:
    """市场反推比分矩阵与拟合信息；缺胜平负返回 None。"""
    f = fit_lambdas(odds, rho, method)
    if f is None:
        return None
    return dc_matrix(f["lam_h"], f["lam_a"], rho), f
