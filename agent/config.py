"""
agent/config.py  Agent 的配置：库路径、快照路径、FotMob 库路径与时钟。
从仓库根目录的 .env 读（只读下面三个键，环境变量优先），没写或为空时用 services 的默认值。
相对路径按仓库根目录解析，所以 MCP 客户端从别的目录启动也能找到库。
测试用 override() 换路径和时钟，不读 .env。密钥不在这里读，也不打印。
"""
import contextlib
import os
import pathlib
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from football_prediction import services

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEYS = {"db_path": "AGENT_DB_PATH", "snapshot_path": "AGENT_SNAPSHOT_PATH",
        "fotmob_path": "AGENT_FOTMOB_PATH"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentConfig:
    db_path: str
    snapshot_path: str
    fotmob_path: str | None
    clock: Callable[[], datetime] = field(default=_utcnow, compare=False)


def _abs(p: str) -> str:
    return str(p if pathlib.Path(p).is_absolute() else ROOT / p)


def _defaults() -> AgentConfig:
    return AgentConfig(_abs(services.DB_PATH), _abs(services.SNAPSHOT_PATH), _abs(services.FOTMOB_DB))


def load_config(env_file: pathlib.Path = ENV_FILE) -> AgentConfig:
    """环境变量 > .env > 默认值；空字符串视为没写。只取 KEYS 里的三个键。"""
    file_vals: dict[str, str | None] = {}
    if env_file.exists():
        from dotenv import dotenv_values      # 只在 .venv-ml 里有；没有 .env 时不需要
        file_vals = dotenv_values(env_file)
    base, vals = _defaults(), {}
    for attr, key in KEYS.items():
        v = os.environ.get(key) or file_vals.get(key)
        if v:
            vals[attr] = _abs(v)
    return replace(base, **vals)


_stack: list[AgentConfig] = []
_loaded: list[AgentConfig] = []


def current() -> AgentConfig:
    """当前配置：override 里的优先，否则第一次调用时读 .env 并缓存。"""
    if _stack:
        return _stack[-1]
    if not _loaded:
        _loaded.append(load_config())
    return _loaded[0]


@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """按当前配置只读打开库（services.open_readonly，有 fotmob.db 时只读挂上），用完关闭。"""
    cfg = current()
    conn = services.open_readonly(cfg.db_path, fotmob_path=cfg.fotmob_path)
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def override(**kw) -> Iterator[AgentConfig]:
    """临时换配置（测试用）：override(db_path=..., snapshot_path=..., fotmob_path=None, clock=...)。"""
    cfg = replace(_defaults(), **kw)
    _stack.append(cfg)
    try:
        yield cfg
    finally:
        _stack.pop()
