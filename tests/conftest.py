"""测试公共夹具：内存 SQLite + 合成联赛数据（不联网、不碰 football.db）。"""
from datetime import date, timedelta

import numpy as np
import pytest

from football_prediction.data.loader import init_db

TEAMS = ["A", "B", "C", "D", "E", "F"]
STRENGTH = {"A": 0.5, "B": 0.3, "C": 0.1, "D": -0.1, "E": -0.3, "F": -0.5}


def _fill(conn, league="E0", start=date(2024, 8, 1), rounds=4, seed=0):
    """双循环 × rounds 轮，泊松进球；同时写入射正与 xG。返回最后一场日期。"""
    rng = np.random.default_rng(seed)
    d, n = start, 0
    for r in range(rounds):
        for h in TEAMS:
            for a in TEAMS:
                if h == a:
                    continue
                lam_h = np.exp(0.25 + STRENGTH[h] - STRENGTH[a])
                lam_a = np.exp(STRENGTH[a] - STRENGTH[h])
                hg, ag = int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
                mid = f"{league}-{n}"
                conn.execute(
                    "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, league, "2425", d.isoformat(), h, a, hg, ag, "test", "now", "t"))
                conn.execute(
                    "INSERT INTO match_stats VALUES (?,?,?,?,?,?,?)",
                    (mid, 10, 10, int(rng.poisson(lam_h * 3)), int(rng.poisson(lam_a * 3)),
                     "now", "t"))
                conn.execute(
                    "INSERT INTO match_xg VALUES (?,?,?,?,?,?)",
                    (mid, float(lam_h), float(lam_a), str(n), "now", "t"))
                n += 1
                d += timedelta(days=1)
    conn.commit()
    return d


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def league(conn):
    """(conn, cutoff)：含 120 场已完赛合成比赛，cutoff 为最后一场之后一天。"""
    return conn, _fill(conn).isoformat()
