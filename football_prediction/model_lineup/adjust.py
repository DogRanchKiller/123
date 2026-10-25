"""
model_lineup/adjust.py  v1.1.0
阵容调整：在市场隐含 λ 上乘 exp(特征·系数)，只用于开球前已公布正式首发的场次（临场档 lineup_t1）。
  主队 log λ' = log λ + b1·d_att(主) + b2·rot(主) + b3·rot_def(客) + b4·rot(客)，客队对称。
  系数用研究脚本以进球泊松似然拟合（岭回归），2324–2425 训练、2526 起留出确认
  （_diag/explore/lineup_fotmob_eval.py）；实盘不在线重拟合，改系数必须升版本。
v1.1.0: 合并规则——系数分两套，按赔率与首发的先后选用，避免重复计入阵容信息：
  赔率抓取早于首次看到正式首发 → COEF_PRE（赔率里还没有阵容，系数在赛前赔率上估）；
  赔率晚于首发 → COEF_POST（赔率已部分消化阵容，系数在收盘赔率上估，预期接近 0）。
  一场只叠一次：临场的最终看法 = 最新赔率的市场隐含 × 对应那套系数，不在 T24 结果上再乘。
修改此文件后请同步更新 version.py 中 "model_lineup" 的版本号。
"""
import numpy as np
from scipy.optimize import minimize

LAYER_VERSION = "1.1.0"
MODEL_NAME = "lineup"            # 存档名 lineup_t1；同时刻未调整的市场隐含存 lineup_base_t1
FEATURES = ("d_att", "rot", "opp_rot_def", "opp_rot")
# 研究确认前为 0（不调整）；见 docs/issues.md「阵容调整系数还没有定」
COEF_PRE = {"d_att": 0.0, "rot": 0.0, "opp_rot_def": 0.0, "opp_rot": 0.0}
COEF_POST = {"d_att": 0.0, "rot": 0.0, "opp_rot_def": 0.0, "opp_rot": 0.0}
COEF = COEF_PRE                  # 兼容旧调用：不给时机时按「赔率早于首发」处理
RIDGE = 1.0


def odds_timing(odds_at: str | None, lineup_at: str | None) -> str:
    """赔率相对正式首发的先后："pre"（赔率早于首发或时间未知）/ "post"（赔率不早于首次看到首发）。
    时间都是 ISO 8601 UTC 字符串。"""
    if not odds_at or not lineup_at:
        return "pre"
    return "post" if odds_at >= lineup_at else "pre"


def coef_for(timing: str) -> dict:
    return COEF_POST if timing == "post" else COEF_PRE


def design(f_self: dict, f_opp: dict) -> np.ndarray:
    """一支球队进球 λ 的特征行：自己的进攻变化、轮换，对手的防守轮换、整体轮换。"""
    return np.array([f_self["d_att"], f_self["rot"], f_opp["rot_def"], f_opp["rot"]])


def adjust_lambdas(lam_h: float, lam_a: float, f_h: dict, f_a: dict,
                   coef: dict | None = None) -> tuple[float, float]:
    b = np.array([(coef or COEF)[k] for k in FEATURES])
    return (float(lam_h * np.exp(design(f_h, f_a) @ b)),
            float(lam_a * np.exp(design(f_a, f_h) @ b)))


def fit_coef(X: np.ndarray, log_lam: np.ndarray, goals: np.ndarray,
             ridge: float = RIDGE) -> dict:
    """带偏移量的泊松回归（每行一支球队一场）：log E[进球] = log_lam + X·b，b 向 0 收缩。"""
    def nll(b):
        mu = np.exp(log_lam + X @ b)
        return (mu - goals * (log_lam + X @ b)).sum() + ridge * b @ b, \
            X.T @ (mu - goals) + 2 * ridge * b
    r = minimize(nll, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B")
    return dict(zip(FEATURES, map(float, r.x)))
