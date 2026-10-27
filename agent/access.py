"""
agent/access.py  网站对话的鉴权（docs/agent-plan.md 第 10.2 节做法 A：邀请码 + 会话 Cookie），P6。
- 邀请码和会话 id 都是 secrets 生成的随机串（128 位以上），库里只存 SHA-256 哈希，明文只在发放时出现一次。
  随机串熵足够，不需要慢哈希；登录不做限速（猜中的概率可以忽略）。
- 会话：login() 用邀请码换一个会话 id（Next.js 放进 HttpOnly + SameSite=Strict 的 Cookie），SESSION_TTL 后过期；
  logout() 吊销这个会话，revoke_user() 吊销用户及其所有会话，都立即生效。
- CSRF 令牌：HMAC-SHA256(密钥, 会话哈希 + 过期时间)，绑定会话、带过期时间；密钥第一次用时随机生成，存在 access.db。
  别的会话的令牌、过期或改动过的令牌都不通过。
- 只读写 cfg.access_path（agent_data/access.db），不碰实盘库、FotMob 库和用量库（tests/test_agent_boundary.py 检查）。
命令行（只在本机，发码给群友的人用）：
  python -m agent.access add <用户 id>    新建用户（或重新启用已吊销的）并打印一次性邀请码
  python -m agent.access revoke <用户 id> 吊销用户及其所有会话
  python -m agent.access list            列出用户、状态和有效会话数
"""
import argparse
import contextlib
import hashlib
import hmac
import pathlib
import re
import secrets
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass

from agent import config

SESSION_TTL = 14 * 86400.0      # 秒：会话 Cookie 的有效期
CSRF_TTL = 86400.0              # 秒：页面里的 CSRF 令牌有效期，过期后刷新页面即可
USER_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")

_DDL = ("""CREATE TABLE IF NOT EXISTS users (
             id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, created REAL NOT NULL, revoked REAL)""",
        """CREATE TABLE IF NOT EXISTS sessions (
             id_hash TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users (id),
             created REAL NOT NULL, expires REAL NOT NULL, revoked REAL)""",
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
_USER = "SELECT revoked FROM users WHERE id = ?"
_USER_ADD = "INSERT INTO users (id, code_hash, created) VALUES (?, ?, ?)"
_USER_RENEW = "UPDATE users SET code_hash = ?, revoked = NULL WHERE id = ?"
_USER_BY_CODE = "SELECT id FROM users WHERE code_hash = ? AND revoked IS NULL"
_USER_REVOKE = "UPDATE users SET revoked = ? WHERE id = ? AND revoked IS NULL"
_USERS = """SELECT u.id, u.revoked, COUNT(s.id_hash) FROM users u
            LEFT JOIN sessions s ON s.user = u.id AND s.revoked IS NULL AND s.expires > ?
            GROUP BY u.id ORDER BY u.id"""
_SESSION_ADD = "INSERT INTO sessions (id_hash, user, created, expires) VALUES (?, ?, ?, ?)"
_SESSION = """SELECT s.user, s.expires FROM sessions s JOIN users u ON u.id = s.user
              WHERE s.id_hash = ? AND s.revoked IS NULL AND u.revoked IS NULL AND s.expires > ?"""
_SESSION_REVOKE = "UPDATE sessions SET revoked = ? WHERE id_hash = ? AND revoked IS NULL"
_SESSIONS_REVOKE = "UPDATE sessions SET revoked = ? WHERE user = ? AND revoked IS NULL"
_SECRET = "SELECT value FROM meta WHERE key = 'csrf_secret'"
_SECRET_ADD = "INSERT INTO meta (key, value) VALUES ('csrf_secret', ?)"


@dataclass(frozen=True)
class Session:
    user: str
    expires: float          # UTC 时间戳
    id_hash: str


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@contextlib.contextmanager
def _db(cfg: config.AgentConfig) -> Iterator[sqlite3.Connection]:
    """一个 BEGIN IMMEDIATE 事务，只开 cfg.access_path。"""
    pathlib.Path(cfg.access_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.access_path, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for ddl in _DDL:
                conn.execute(ddl)
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _now(cfg: config.AgentConfig) -> float:
    return cfg.clock().timestamp()


def add_user(user: str, cfg: config.AgentConfig | None = None) -> str:
    """新建用户并返回邀请码（只这一次能看到明文）。已吊销的用户重新启用并换新码；有效用户报错。"""
    cfg = cfg or config.current()
    if not USER_ID.fullmatch(user):
        raise ValueError("用户 id 只能用字母、数字、_ 和 -，1–32 个字符")
    code = secrets.token_urlsafe(18)
    with _db(cfg) as conn:
        row = conn.execute(_USER, (user,)).fetchone()
        if row is None:
            conn.execute(_USER_ADD, (user, _hash(code), _now(cfg)))
        elif row[0] is not None:
            conn.execute(_USER_RENEW, (_hash(code), user))
        else:
            raise ValueError(f"用户 {user} 已存在且有效；要换码先 revoke")
    return code


def revoke_user(user: str, cfg: config.AgentConfig | None = None) -> bool:
    """吊销用户及其所有会话；返回是否有变化。"""
    cfg = cfg or config.current()
    with _db(cfg) as conn:
        t = _now(cfg)
        changed = conn.execute(_USER_REVOKE, (t, user)).rowcount
        conn.execute(_SESSIONS_REVOKE, (t, user))
    return bool(changed)


def list_users(cfg: config.AgentConfig | None = None) -> list[dict]:
    cfg = cfg or config.current()
    with _db(cfg) as conn:
        rows = conn.execute(_USERS, (_now(cfg),)).fetchall()
    return [{"user": u, "active": r is None, "sessions": n} for u, r, n in rows]


def login(code: str, cfg: config.AgentConfig | None = None) -> tuple[str, Session] | None:
    """邀请码对就新建会话，返回 (会话 id 明文, 会话)；不对或用户已吊销返回 None。"""
    cfg = cfg or config.current()
    if not code or len(code) > 128:
        return None
    sid = secrets.token_urlsafe(32)
    with _db(cfg) as conn:
        row = conn.execute(_USER_BY_CODE, (_hash(code),)).fetchone()
        if row is None:
            return None
        t = _now(cfg)
        conn.execute(_SESSION_ADD, (_hash(sid), row[0], t, t + SESSION_TTL))
    return sid, Session(row[0], t + SESSION_TTL, _hash(sid))


def session(sid: str | None, cfg: config.AgentConfig | None = None) -> Session | None:
    """有效会话（未过期、未吊销、用户未吊销）或 None。"""
    cfg = cfg or config.current()
    if not sid or len(sid) > 128:
        return None
    with _db(cfg) as conn:
        row = conn.execute(_SESSION, (_hash(sid), _now(cfg))).fetchone()
    return Session(row[0], row[1], _hash(sid)) if row else None


def logout(sid: str | None, cfg: config.AgentConfig | None = None) -> None:
    cfg = cfg or config.current()
    if sid:
        with _db(cfg) as conn:
            conn.execute(_SESSION_REVOKE, (_now(cfg), _hash(sid)))


def _secret(cfg: config.AgentConfig) -> bytes:
    with _db(cfg) as conn:
        row = conn.execute(_SECRET).fetchone()
        if row is None:
            row = (secrets.token_hex(32),)
            conn.execute(_SECRET_ADD, row)
    return bytes.fromhex(row[0])


def _mac(key: bytes, s: Session, exp: int) -> str:
    return hmac.new(key, f"{s.id_hash}.{exp}".encode(), hashlib.sha256).hexdigest()


def csrf_token(s: Session, cfg: config.AgentConfig | None = None) -> str:
    """绑定这个会话、CSRF_TTL 后过期的令牌：「过期时间.签名」。"""
    cfg = cfg or config.current()
    exp = int(_now(cfg) + CSRF_TTL)
    return f"{exp}.{_mac(_secret(cfg), s, exp)}"


def csrf_ok(token: str | None, s: Session, cfg: config.AgentConfig | None = None) -> bool:
    cfg = cfg or config.current()
    exp, _, mac = (token or "").partition(".")
    if not exp.isdigit() or int(exp) <= _now(cfg):
        return False
    return hmac.compare_digest(mac, _mac(_secret(cfg), s, int(exp)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.access", description="网站对话的邀请码（只在本机用）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("add", "新建用户（或重新启用已吊销的）并打印一次性邀请码"), ("revoke", "吊销用户及其所有会话")):
        sub.add_parser(name, help=text).add_argument("user", help="用户 id：字母、数字、_、-")
    sub.add_parser("list", help="列出用户、状态和有效会话数")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "add":
            print(f"用户 {a.user} 的邀请码（只显示这一次，私下发给对方）：{add_user(a.user)}")
        elif a.cmd == "revoke":
            print(f"已吊销 {a.user}" if revoke_user(a.user) else f"{a.user} 不存在或已吊销（其会话已一并吊销）")
        else:
            for u in list_users():
                print(f"{u['user']}\t{'有效' if u['active'] else '已吊销'}\t有效会话 {u['sessions']}")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
