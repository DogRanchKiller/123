"""agent/access.py：邀请码与会话（docs/agent-plan.md 第 10.2 节做法 A、第 10.4 节 A 组）。
只用临时目录里的 access.db，不联网、不碰 football.db。只用标准库，.venv 里也能跑。"""
import sqlite3
from datetime import timedelta

import pytest

from agent import access, config
from tests.test_agent_budget import MON_NIGHT, Clock


@pytest.fixture
def env(tmp_path):
    clock = Clock(MON_NIGHT)
    cfg = config.AgentConfig(db_path="-", snapshot_path="-", fotmob_path=None,
                             access_path=str(tmp_path / "access.db"), clock=clock)
    return cfg, clock


def test_only_hashes_are_stored(env):
    cfg, _ = env
    code = access.add_user("alice", cfg)
    sid, _ = access.login(code, cfg)
    dump = "\n".join(sqlite3.connect(cfg.access_path).iterdump())
    assert code not in dump and sid not in dump
    assert access._hash(code) in dump and access._hash(sid) in dump


def test_wrong_code_gives_no_session(env):
    cfg, _ = env
    code = access.add_user("alice", cfg)
    assert access.login("nope", cfg) is None and access.login("", cfg) is None
    assert access.login(code + "x", cfg) is None and access.login("x" * 200, cfg) is None
    sid, s = access.login(code, cfg)
    assert s.user == "alice" and access.session(sid, cfg).user == "alice"
    assert access.session(None, cfg) is None and access.session("bogus", cfg) is None


def test_logout_and_revoke_take_effect_at_once(env):
    cfg, _ = env
    code = access.add_user("alice", cfg)
    sid1, _ = access.login(code, cfg)
    sid2, _ = access.login(code, cfg)
    access.logout(sid1, cfg)
    assert access.session(sid1, cfg) is None and access.session(sid2, cfg) is not None
    assert access.revoke_user("alice", cfg) is True
    assert access.session(sid2, cfg) is None and access.login(code, cfg) is None
    assert access.revoke_user("alice", cfg) is False


def test_readd_after_revoke_gives_new_code(env):
    cfg, _ = env
    old = access.add_user("alice", cfg)
    with pytest.raises(ValueError, match="已存在"):
        access.add_user("alice", cfg)
    access.revoke_user("alice", cfg)
    new = access.add_user("alice", cfg)
    assert new != old and access.login(old, cfg) is None and access.login(new, cfg) is not None
    assert access.list_users(cfg) == [{"user": "alice", "active": True, "sessions": 1}]


def test_session_expires(env):
    cfg, clock = env
    sid, s = access.login(access.add_user("alice", cfg), cfg)
    assert s.expires == MON_NIGHT.timestamp() + access.SESSION_TTL
    clock.t = MON_NIGHT + timedelta(seconds=access.SESSION_TTL - 1)
    assert access.session(sid, cfg) is not None
    clock.t = MON_NIGHT + timedelta(seconds=access.SESSION_TTL)
    assert access.session(sid, cfg) is None
    assert access.list_users(cfg)[0]["sessions"] == 0


def test_csrf_bound_to_session_and_expiry(env):
    cfg, clock = env
    a = access.login(access.add_user("alice", cfg), cfg)[1]
    b = access.login(access.add_user("bob", cfg), cfg)[1]
    tok = access.csrf_token(a, cfg)
    assert access.csrf_ok(tok, a, cfg)
    assert not access.csrf_ok(tok, b, cfg)                              # 别的会话的令牌
    assert not access.csrf_ok(access.csrf_token(b, cfg), a, cfg)
    exp, mac = tok.split(".")
    assert not access.csrf_ok(f"{int(exp) + 999}.{mac}", a, cfg)        # 改过期时间
    assert not access.csrf_ok(f"{exp}.{'0' * 64}", a, cfg)
    for junk in (None, "", "abc", ".", "1.2.3"):
        assert not access.csrf_ok(junk, a, cfg)
    clock.t = MON_NIGHT + timedelta(seconds=access.CSRF_TTL + 1)
    assert not access.csrf_ok(tok, a, cfg)


def test_csrf_secret_survives_restart(env):
    """密钥存在 access.db：重开（新的 cfg 对象，同一个库）后旧令牌照样有效。"""
    cfg, clock = env
    s = access.login(access.add_user("alice", cfg), cfg)[1]
    tok = access.csrf_token(s, cfg)
    again = config.AgentConfig(db_path="-", snapshot_path="-", fotmob_path=None, access_path=cfg.access_path,
                               clock=clock)
    assert access.csrf_ok(tok, s, again)


def test_bad_user_id(env):
    cfg, _ = env
    for bad in ("", "a b", "a:b", "x" * 33, "张三"):
        with pytest.raises(ValueError):
            access.add_user(bad, cfg)


def test_cli(env, capsys):
    cfg, _ = env
    with config.override(access_path=cfg.access_path, clock=cfg.clock):
        assert access.main(["add", "alice"]) == 0
        code = capsys.readouterr().out.strip().rsplit("：", 1)[1]
        assert access.login(code, cfg) is not None
        assert access.main(["add", "alice"]) == 1
        assert access.main(["list"]) == 0 and "alice\t有效\t有效会话 1" in capsys.readouterr().out
        assert access.main(["revoke", "alice"]) == 0
        access.main(["list"])
        assert "alice\t已吊销\t有效会话 0" in capsys.readouterr().out
