"""model_nn：特征按场时点构造（不需要 torch）；网络、损失与预测契约（需要 torch，.venv 里跳过）。"""
import sys
from datetime import date

import numpy as np
import pytest

from football_prediction.model_market.implied import dc_matrix
from football_prediction.model_nn.dataset import (FEATURES_VER, MARKET_COLS, build_table,
                                                  feature_columns, state_at)
from tests.conftest import _fill

ALL = sorted(set(feature_columns("full", "B")))
STATE_COLS = [c for c in ALL if c not in MARKET_COLS]


@pytest.fixture(autouse=True)
def _one_thread():
    """torch 测试用单线程：同一进程先跑过 Milvus Lite 的知识库测试时，torch 的多线程 OpenMP
    在 macOS 上会段错误（两边各带一份运行时）。选参 / 留出脚本不加载 Milvus，不受影响。"""
    if "torch" in sys.modules or _has_torch():
        import torch
        torch.set_num_threads(1)
    yield


def _has_torch() -> bool:
    import importlib.util
    return importlib.util.find_spec("torch") is not None


def _odds(conn, every: int = 1):
    """给合成比赛按真实 λ 写赛前平均赔率（5% 水），供变体 B 和市场列用。"""
    rows = conn.execute("SELECT m.match_id, x.home_xg, x.away_xg FROM matches m "
                        "JOIN match_xg x USING(match_id) ORDER BY m.match_date").fetchall()
    for k, (mid, lh, la) in enumerate(rows):
        if k % every:
            continue
        m = dc_matrix(lh, la)
        p = [np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()]
        tot = np.add.outer(np.arange(9), np.arange(9))
        po = m[tot > 2.5].sum()
        o = [1 / (x * 1.05) for x in p] + [1 / (po * 1.05), 1 / ((1 - po) * 1.05)]
        conn.execute("INSERT INTO match_odds (match_id, avg_h, avg_d, avg_a, avg_over25, avg_under25,"
                     " fetched_at, layer_ver) VALUES (?,?,?,?,?,?,?,?)", (mid, *o, "now", "t"))
    conn.commit()


def test_feature_columns():
    full_a, nox_a, full_b = (feature_columns("full", "A"), feature_columns("no_xg", "A"),
                             feature_columns("full", "B"))
    assert "h_xf" in full_a and "h_xf" not in nox_a and "mk_ph" not in full_a
    assert set(full_b) - set(full_a) == set(MARKET_COLS)
    with pytest.raises(ValueError):
        feature_columns("xg", "A")


def test_features_point_in_time(conn):
    """删掉某场之后的全部比赛、改掉这场自己的比分，这场的特征完全不变。"""
    _fill(conn, rounds=4)
    _odds(conn)
    full = build_table(conn, "E0", cache=False)
    target = full.iloc[70]
    d = target["match_date"]
    conn.execute("DELETE FROM matches WHERE match_date > ?", (d,))
    conn.execute("UPDATE matches SET home_goals = 9, away_goals = 9 WHERE match_id = ?",
                 (target["match_id"],))
    # 同一天再加一场：同日比赛互不可见
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("E0-same", "E0", "2425", d, target["home_team"], "Z", 7, 0, "t", "now", "t"))
    conn.commit()
    cut = build_table(conn, "E0", cache=False).set_index("match_id").loc[target["match_id"]]
    for c in ALL:
        assert cut[c] == target[c] or (np.isnan(cut[c]) and np.isnan(target[c])), c
    assert target["cutoff_date"] == d[:10] and target["features_ver"] == FEATURES_VER


def test_future_result_changes_later_features(conn):
    """反过来：前一天的比分变了，后一场的特征要跟着变（特征确实在用历史）。"""
    _fill(conn, rounds=2)
    a = build_table(conn, "E0", cache=False)
    first = a.iloc[0]
    conn.execute("UPDATE matches SET home_goals = 8 WHERE match_id = ?", (first["match_id"],))
    conn.commit()
    b = build_table(conn, "E0", cache=False)
    assert b.iloc[0]["h_gf5"] == a.iloc[0]["h_gf5"]
    assert not np.allclose(b[STATE_COLS].to_numpy(float), a[STATE_COLS].to_numpy(float))


def test_state_at_matches_table(conn):
    """实盘路径（state_at + features）与样本表同一场的特征逐项相等。"""
    _fill(conn, rounds=3)
    t = build_table(conn, "E0", cache=False)
    r = t.iloc[50]
    st = state_at(conn, "E0", r["match_date"])
    f = st.features(r["home_team"], r["away_team"], date.fromisoformat(r["match_date"]))
    for c in STATE_COLS:
        assert f[c] == r[c], c


def test_no_top_level_torch():
    """version.py / test_versions 在 .venv（没有 torch）里要能读 LAYER_VERSION。"""
    import subprocess
    code = ("import sys; import football_prediction.model_nn.model, football_prediction.model_nn.net, "
            "football_prediction.model_nn.train; print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# ---- 以下需要 torch ----

def _fit(conn, variant, seed=0, rounds=12):
    torch = pytest.importorskip("torch")
    from football_prediction.model_nn.model import NNModel
    from football_prediction.model_nn.train import TrainConfig
    end = _fill(conn, rounds=rounds)
    _odds(conn)
    cfg = TrainConfig(variant=variant, hidden=(16,), max_epochs=30, patience=5, val_days=60,
                      batch_size=64, seed=seed)
    m = NNModel(cfg, cache=False)
    m.fit(conn, "E0", end.isoformat())
    return torch, m


@pytest.mark.parametrize("variant", ["A", "B"])
def test_lambda_positive_and_matrix_sums_to_one(conn, variant):
    _, m = _fit(conn, variant)
    odds = {"h": 2.0, "d": 3.4, "a": 3.8, "over": 1.9, "under": 1.95}
    lh, la, rho = m.predict_rows(build_table(conn, "E0", cache=False).dropna(subset=["mk_lam_h"]))
    assert (lh > 0).all() and (la > 0).all() and abs(rho) < 0.25
    mat = m.score_matrix("A", "F", odds)
    assert mat.min() >= 0 and mat.sum() == pytest.approx(1.0, abs=1e-12)
    p = m.predict_1x2("A", "F", odds)
    assert p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1.0, abs=1e-12)
    assert p["home_win"] > p["away_win"]          # 合成数据里 A 最强、F 最弱
    assert m.fitted.info["n_train"] > 200 and m.fitted.epochs >= 1


def test_variant_b_needs_odds(conn):
    _, m = _fit(conn, "B")
    with pytest.raises(ValueError):
        m.predict_1x2("A", "F")


def test_variant_b_starts_at_market():
    """B 的输出层初始化为 0：未训练时 λ 就是市场 λ。"""
    torch = pytest.importorskip("torch")
    from football_prediction.model_nn.net import build_net, inv_softplus
    net = build_net(4, (8,), 0.0, "B")
    base = torch.tensor([[inv_softplus(1.7), inv_softplus(0.9)]])
    with torch.no_grad():
        lh, la, _ = net(torch.zeros(1, 4), base)
    assert float(lh) == pytest.approx(1.7 + 1e-4, rel=1e-5)
    assert float(la) == pytest.approx(0.9 + 1e-4, rel=1e-5)


def test_dc_nll_equals_matrix_log_prob():
    torch = pytest.importorskip("torch")
    from football_prediction.model_nn.net import dc_nll
    lh, la, rho = 1.6, 1.1, -0.07
    m = dc_matrix(lh, la, rho)
    hg, ag = torch.tensor([0, 1, 2, 3, 12]), torch.tensor([0, 1, 0, 4, 1])
    got = dc_nll(torch.full((5,), lh, dtype=torch.float64), torch.full((5,), la, dtype=torch.float64),
                 torch.tensor(rho, dtype=torch.float64), hg, ag).numpy()
    want = [-np.log(m[min(i, 8), min(j, 8)]) for i, j in zip(hg.tolist(), ag.tolist())]
    assert got == pytest.approx(want, abs=1e-9)


def test_same_seed_same_model():
    from football_prediction.data.loader import init_db
    preds = []
    for _ in range(2):
        c = init_db(":memory:")
        _, m = _fit(c, "A", seed=3, rounds=10)
        preds.append(m.predict_1x2("B", "E")["home_win"])
        c.close()
    assert preds[0] == preds[1]
