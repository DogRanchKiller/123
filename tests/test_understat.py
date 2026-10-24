"""understat 队名自动映射：按同日 ±1 天且同比分投票。"""
import pytest

from football_prediction.data.understat import _team_map


def _us(d, h, a, hg, ag):
    return {"datetime": f"{d} 15:00:00", "h": {"title": h}, "a": {"title": a},
            "goals": {"h": str(hg), "a": str(ag)}}


FD = [("1", "2025-08-16", "Man United", "Arsenal", 0, 1),
      ("2", "2025-08-17", "Wolves", "Man City", 0, 4),
      ("3", "2025-08-23", "Arsenal", "Wolves", 2, 0),
      ("4", "2025-08-24", "Man City", "Man United", 3, 0)]


def test_team_map_votes_with_date_offset():
    us = [_us("2025-08-15", "Manchester United", "Arsenal", 0, 1),   # 时区差一天
          _us("2025-08-17", "Wolverhampton Wanderers", "Manchester City", 0, 4),
          _us("2025-08-23", "Arsenal", "Wolverhampton Wanderers", 2, 0),
          _us("2025-08-24", "Manchester City", "Manchester United", 3, 0)]
    assert _team_map(us, FD) == {
        "Manchester United": "Man United", "Arsenal": "Arsenal",
        "Wolverhampton Wanderers": "Wolves", "Manchester City": "Man City"}


def test_team_map_duplicate_raises():
    # 两个 understat 队名都只在同一场里出现 → 都映射到同一队，必须报错而不是静默写错
    us = [_us("2025-08-16", "Man Utd A", "Arsenal", 0, 1),
          _us("2025-08-16", "Man Utd B", "Arsenal", 0, 1)]
    with pytest.raises(ValueError):
        _team_map(us, FD)
