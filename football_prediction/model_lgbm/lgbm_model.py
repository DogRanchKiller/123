"""
model_lgbm/lgbm_model.py  v1.1.0
LightGBM 修正层：在 Dixon-Coles 预测基础上学习残差修正。
架构：DC 概率 + 统计特征 → LightGBM 三分类 → 与 DC 按 alpha 混合 → 校正后 1X2 概率。

v1.1.0 变更：
  - 修复 v1.0.0 中两套重名方法导致 alpha CV 失效的 bug（旧版 fit/predict 无 alpha）
  - fit() 改用滚动 OOS：对 train_seasons[i] (i>=1) 逐赛季生成场外样本，
    训练量从 ~380 增至 ~(N-1)×380，alpha CV 在最后一折（最接近测试期）进行
修改此文件后请同步更新 version.py 中 "model_lgbm" 的版本号。
"""
import sqlite3
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import date, timedelta

from football_prediction.features.builder import build_features

LAYER_VERSION = "1.1.0"

FEATURE_COLS = [
    "dc_p_home", "dc_p_draw", "dc_p_away",
    "dc_lam_h", "dc_lam_a",
    "home_win_rate", "home_recent_gf", "home_recent_ga",
    "away_win_rate", "away_recent_gf", "away_recent_ga",
    "h2h_home_win_rate", "h2h_count",
]

ALPHA_CANDIDATES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

_LGBM_PARAMS = dict(
    n_estimators=100, learning_rate=0.05, num_leaves=15,
    min_child_samples=20, reg_lambda=1.0,
    objective="multiclass", num_class=3,
    random_state=42, n_jobs=1, verbose=-1,
)


def _log_loss_arr(p_matrix: np.ndarray, labels: np.ndarray) -> float:
    """p_matrix: (N,3), labels: (N,) int 0/1/2"""
    p_true = p_matrix[np.arange(len(labels)), labels]
    return float(-np.log(np.clip(p_true, 1e-7, 1.0)).mean())


def _season_end_cutoff(conn, league, seasons):
    """返回给定赛季集合最后一场比赛日期 +1 天（ISO 字符串）。"""
    raw = pd.read_sql_query(
        f"""SELECT MAX(match_date) AS dt FROM matches
            WHERE league = ? AND season IN ({','.join('?'*len(seasons))})
              AND home_goals IS NOT NULL""",
        conn, params=[league] + list(seasons),
    ).iloc[0]["dt"]
    return (date.fromisoformat(raw) + timedelta(days=1)).isoformat()


class LGBMCorrectionModel:
    """
    用法：
        lgbm = LGBMCorrectionModel()
        lgbm.fit(conn, league, dc_model_fitted, train_seasons)
        probs = lgbm.predict_match(conn, league, dc_model_fitted,
                                   "Arsenal", "Chelsea", cutoff_date)
    """

    def __init__(self):
        self.model = None
        self.alpha = 0.0   # LightGBM 混合权重，由 CV 确定

    # ------------------------------------------------------------------
    # 特征构建（内部辅助）
    # ------------------------------------------------------------------

    def _build_row(self, conn, league, dc_model, home, away, cutoff_date):
        """为单场比赛生成特征向量（dict）"""
        probs = dc_model.predict_1x2(home, away)
        lam_h, lam_a = dc_model._lambda(home, away)
        feats = build_features(conn, league, cutoff_date, home, away)
        return {
            "dc_p_home":          probs["home_win"],
            "dc_p_draw":          probs["draw"],
            "dc_p_away":          probs["away_win"],
            "dc_lam_h":           float(lam_h),
            "dc_lam_a":           float(lam_a),
            "home_win_rate":      feats["home_win_rate"],
            "home_recent_gf":     feats["home_recent_gf"],
            "home_recent_ga":     feats["home_recent_ga"],
            "away_win_rate":      feats["away_win_rate"],
            "away_recent_gf":     feats["away_recent_gf"],
            "away_recent_ga":     feats["away_recent_ga"],
            "h2h_home_win_rate":  feats["h2h_home_win_rate"],
            "h2h_count":          feats["h2h_count"],
        }

    def _season_rows(self, conn, league, dc_model, season):
        """
        对 season 中每场已有结果的比赛，用 dc_model 生成特征行。
        返回 (X, Pdc, y)，跳过异常场次。
        """
        df = pd.read_sql_query(
            """SELECT match_date, home_team, away_team, home_goals, away_goals
               FROM matches WHERE league = ? AND season = ?
                 AND home_goals IS NOT NULL ORDER BY match_date""",
            conn, params=[league, season],
        )
        rows, dc_probs_list, labels = [], [], []
        for _, row in df.iterrows():
            try:
                feat = self._build_row(
                    conn, league, dc_model,
                    row["home_team"], row["away_team"], row["match_date"],
                )
            except Exception:
                continue
            hg, ag = int(row["home_goals"]), int(row["away_goals"])
            label = 0 if hg > ag else (1 if hg == ag else 2)
            rows.append([feat[c] for c in FEATURE_COLS])
            dc_probs_list.append([feat["dc_p_home"], feat["dc_p_draw"], feat["dc_p_away"]])
            labels.append(label)
        if not rows:
            return np.empty((0, len(FEATURE_COLS))), np.empty((0, 3)), np.empty(0, int)
        return (
            np.array(rows,          dtype=float),
            np.array(dc_probs_list, dtype=float),
            np.array(labels,        dtype=int),
        )

    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------

    def fit(self, conn: sqlite3.Connection, league: str,
            dc_model, train_seasons: list) -> None:
        """
        滚动 OOS 训练（v1.1.0）：
          对每个 i in [1, N-1]，用前 i 赛季拟合 helper DC，
          在第 i+1 赛季生成场外样本，累积为完整训练集。
          总样本量 ~(N-1)×380，相较 v1.0.0 的 ~380 大幅提升。

          alpha 选取：在最后一折（最接近测试期）的 OOS 数据上进行 CV，
          避免用早期赛季数据的 CV 结果掩盖近期分布。
        """
        if len(train_seasons) < 2:
            raise ValueError("需要至少 2 个训练赛季")

        all_X, all_Pdc, all_y = [], [], []
        last_fold_start = 0  # 最后一折在 all_X 中的起始索引

        for i in range(1, len(train_seasons)):
            helper_seasons = train_seasons[:i]
            oos_season     = train_seasons[i]
            cutoff         = _season_end_cutoff(conn, league, helper_seasons)
            print(f"  [滚动OOS fold {i}] helper={helper_seasons} → oos={oos_season}"
                  f"  cutoff={cutoff}", flush=True)

            helper_dc = dc_model.__class__(xi=dc_model.xi)
            helper_dc.fit(conn, league, cutoff)

            X_fold, Pdc_fold, y_fold = self._season_rows(
                conn, league, helper_dc, oos_season
            )
            if len(X_fold) == 0:
                continue

            if i == len(train_seasons) - 1:
                last_fold_start = sum(len(x) for x in all_X)

            all_X.append(X_fold)
            all_Pdc.append(Pdc_fold)
            all_y.append(y_fold)

        if not all_X:
            raise RuntimeError("未能生成任何 OOS 训练样本")

        X   = np.vstack(all_X)
        Pdc = np.vstack(all_Pdc)
        y   = np.concatenate(all_y)
        print(f"  LightGBM 总训练样本: {len(X)} 场（{len(train_seasons)-1} 折滚动OOS）",
              flush=True)

        # 在最后一折数据上做 alpha CV（最接近真实测试条件）
        X_cv   = X[last_fold_start:]
        Pdc_cv = Pdc[last_fold_start:]
        y_cv   = y[last_fold_start:]
        X_tr   = X[:last_fold_start] if last_fold_start > 0 else X
        y_tr   = y[:last_fold_start] if last_fold_start > 0 else y

        best_alpha, best_ll = 0.0, float("inf")
        for alpha in ALPHA_CANDIDATES:
            if len(X_tr) < 20 or len(X_cv) < 20:
                break
            m = lgb.LGBMClassifier(**_LGBM_PARAMS)
            m.fit(X_tr, y_tr)
            Plgbm_cv = m.predict_proba(X_cv)
            blend = alpha * Plgbm_cv + (1 - alpha) * Pdc_cv
            blend /= blend.sum(axis=1, keepdims=True)
            ll = _log_loss_arr(blend, y_cv)
            if ll < best_ll:
                best_ll, best_alpha = ll, alpha

        self.alpha = best_alpha
        print(f"  最优混合权重 alpha={best_alpha:.1f}（CV Log Loss={best_ll:.4f}）",
              flush=True)

        # 用全量数据训练最终模型
        self.model = lgb.LGBMClassifier(**_LGBM_PARAMS)
        self.model.fit(X, y)

    # ------------------------------------------------------------------
    # 预测
    # ------------------------------------------------------------------

    def predict_match(self, conn: sqlite3.Connection, league: str,
                      dc_model, home: str, away: str,
                      cutoff_date: str) -> dict:
        if self.model is None:
            raise RuntimeError("请先调用 fit()")
        feat = self._build_row(conn, league, dc_model, home, away, cutoff_date)
        X = np.array([[feat[c] for c in FEATURE_COLS]], dtype=float)
        Plgbm = self.model.predict_proba(X)[0]
        Pdc   = np.array([feat["dc_p_home"], feat["dc_p_draw"], feat["dc_p_away"]])
        blend = self.alpha * Plgbm + (1 - self.alpha) * Pdc
        blend = blend / blend.sum()
        return {
            "home_win":  round(float(blend[0]), 4),
            "draw":      round(float(blend[1]), 4),
            "away_win":  round(float(blend[2]), 4),
            "alpha":     self.alpha,
            "model_ver": LAYER_VERSION,
        }
