"""
agent/config.py  Agent 的配置：库路径、快照路径、FotMob 库路径、知识库目录、向量模型目录、用量库、
对话状态库、价格表、单轮上限与额度（Limits）和时钟。
从仓库根目录的 .env 读（只读 KEYS / LIMIT_KEYS 里的键，环境变量优先），没写或为空时用默认值。
相对路径按仓库根目录解析，所以 MCP 客户端从别的目录启动也能找到库。
测试用 override() 换路径、上限、时钟和向量函数（embedder，测试注入假的），不读 .env。
密钥不在这里读，也不打印（模型提供方与密钥在 agent/llm.py）。
"""
import contextlib
import os
import pathlib
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from football_prediction import services

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEYS = {"db_path": "AGENT_DB_PATH", "snapshot_path": "AGENT_SNAPSHOT_PATH",
        "fotmob_path": "AGENT_FOTMOB_PATH", "kb_path": "AGENT_KB_PATH", "embed_model": "AGENT_EMBED_MODEL",
        "usage_path": "AGENT_USAGE_PATH", "state_path": "AGENT_STATE_PATH", "prices_path": "AGENT_PRICES_PATH"}
KB_PATH = "agent_data/kb"              # Milvus Lite 数据目录（gitignore）
EMBED_MODEL = "checkpoints/bge-m3"     # BAAI/bge-m3 本地目录（gitignore），见 docs/stack.md
USAGE_PATH = "agent_data/usage.db"     # 用量与额度预留（agent/budget.py）
STATE_PATH = "agent_data/state.db"     # 对话状态（LangGraph SqliteSaver）
PRICES_PATH = "agent/prices.toml"      # 单价表，用户手工维护


@dataclass(frozen=True)
class Limits:
    """单轮上限（docs/agent-plan.md 第 8.1 节）与个人额度（第 10.3 节，命令行 / MCP 一档）。
    budget_personal_daily：美元，北京时间按日切；2026-10-27 用户定为 2。"""
    model_calls: int = 6
    tool_rounds: int = 4
    answers: int = 2
    http: int = 12
    max_tokens: int = 6000          # 单次请求的输出上限（含思考 token），也是预留的输出 token 数；
                                    # 2000 时思考就占掉约 1600，P3 评测里 4 次回复被截断成空
    request_timeout: float = 60.0   # 单个 HTTP 请求，秒
    turn_timeout: float = 300.0     # 单轮总时长，秒；预留在这之后再过 RESERVE_GRACE 秒过期
    tool_tokens: int = 12000        # 一轮工具返回的总量（估计 token），超出的调用不交给模型，让它缩小范围
    budget_personal_daily: float = 2.0


LIMIT_KEYS = {"model_calls": "AGENT_MAX_MODEL_CALLS", "tool_rounds": "AGENT_MAX_TOOL_ROUNDS",
              "answers": "AGENT_MAX_ANSWERS", "http": "AGENT_MAX_HTTP", "max_tokens": "AGENT_MAX_TOKENS",
              "request_timeout": "AGENT_REQUEST_TIMEOUT", "turn_timeout": "AGENT_TURN_TIMEOUT",
              "tool_tokens": "AGENT_MAX_TOOL_TOKENS", "budget_personal_daily": "AGENT_BUDGET_PERSONAL_DAILY"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentConfig:
    db_path: str
    snapshot_path: str
    fotmob_path: str | None
    kb_path: str = field(default_factory=lambda: _abs(KB_PATH))
    embed_model: str = field(default_factory=lambda: _abs(EMBED_MODEL))
    usage_path: str = field(default_factory=lambda: _abs(USAGE_PATH))
    state_path: str = field(default_factory=lambda: _abs(STATE_PATH))
    prices_path: str = field(default_factory=lambda: _abs(PRICES_PATH))
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], datetime] = field(default=_utcnow, compare=False)
    embedder: Any = field(default=None, compare=False)    # None：按 embed_model 加载 bge-m3（agent/kb/embed.py）


def _abs(p: str) -> str:
    return str(p if pathlib.Path(p).is_absolute() else ROOT / p)


def _defaults() -> AgentConfig:
    return AgentConfig(_abs(services.DB_PATH), _abs(services.SNAPSHOT_PATH), _abs(services.FOTMOB_DB))


def _limits(get: Callable[[str], str | None]) -> Limits:
    """上限与额度：写了但不是正数时报错，不悄悄用默认值。"""
    vals: dict[str, Any] = {}
    for attr, key in LIMIT_KEYS.items():
        v = get(key)
        if not v:
            continue
        kind = type(getattr(Limits, attr))
        try:
            x = kind(v)
        except ValueError:
            raise ValueError(f"{key}={v!r} 不是{'整数' if kind is int else '数字'}") from None
        if x <= 0:
            raise ValueError(f"{key} 要大于 0")
        vals[attr] = x
    return Limits(**vals)


def load_config(env_file: pathlib.Path = ENV_FILE) -> AgentConfig:
    """环境变量 > .env > 默认值；空字符串视为没写。只取 KEYS / LIMIT_KEYS 里的键。"""
    file_vals: dict[str, str | None] = {}
    if env_file.exists():
        from dotenv import dotenv_values      # 只在 .venv-ml 里有；没有 .env 时不需要
        file_vals = dotenv_values(env_file)

    def get(key: str) -> str | None:
        return os.environ.get(key) or file_vals.get(key)

    base, vals = _defaults(), {}
    for attr, key in KEYS.items():
        if v := get(key):
            vals[attr] = _abs(v)
    return replace(base, **vals, limits=_limits(get))


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
    """临时换配置（测试用）：override(db_path=..., snapshot_path=..., fotmob_path=None, kb_path=..., clock=...,
    embedder=..., usage_path=..., state_path=..., prices_path=..., limits=Limits(...))。"""
    cfg = replace(_defaults(), **kw)
    _stack.append(cfg)
    try:
        yield cfg
    finally:
        _stack.pop()
