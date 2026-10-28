"""中文队名表：football_prediction/data/team_zh.json（Agent 的 resolve_team 用）与网站副本
web/src/features/match/team-zh.json 必须一致；队名解析按中文名找到库里的队。"""
import json
import sqlite3
from pathlib import Path

from football_prediction.services.team_read import TEAM_ZH_PATH, resolve_team_name, team_zh

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src" / "features" / "match" / "team-zh.json"


def test_web_copy_matches():
    assert json.loads(WEB.read_text(encoding="utf-8")) == json.loads(TEAM_ZH_PATH.read_text(encoding="utf-8")), \
        f"{WEB} 与 {TEAM_ZH_PATH} 不一致；补队名时两份一起改"


def test_table_shape():
    zh = team_zh()
    assert len(zh) > 200
    assert all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in zh.items())
    assert zh["Man City"] == "曼城" and zh["Manchester Utd"] == zh["Man United"] == "曼联"


def _conn() -> sqlite3.Connection:
    """只有 resolve_team_name 要的两张表的最小库。"""
    c = sqlite3.connect(":memory:")
    for t in ("matches", "fixtures"):
        c.execute(f"CREATE TABLE {t} (league TEXT, home_team TEXT, away_team TEXT)")
    c.executemany("INSERT INTO matches VALUES (?,?,?)", [
        ("SP1", "Real Madrid", "Ath Madrid"), ("I1", "Milan", "Inter"), ("E0", "Arsenal", "Chelsea")])
    return c


def _hits(text, league=None):
    return [(h["team"], h["match"]) for h in resolve_team_name(_conn(), text, league)]


def test_resolve_chinese_names():
    assert _hits("阿森纳") == [("Arsenal", "zh")]
    assert _hits(" 皇家马德里 ") == [("Real Madrid", "zh")]
    assert _hits("马德里") == [("Ath Madrid", "zh_partial"), ("Real Madrid", "zh_partial")]   # 多个候选，不替用户挑
    assert _hits("米兰") == [("Inter", "zh_partial"), ("Milan", "zh_partial")]               # 国际米兰、AC米兰
    assert _hits("阿森纳", "SP1") == []                                   # 联赛过滤照常
    assert _hits("马") == [] and _hits("皇马") == []                       # 一个字不做子串；俗称不在表里
    assert _hits("Arsenal") == [("Arsenal", "exact")]                    # 英文层先于中文层
