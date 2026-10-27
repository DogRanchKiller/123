"""
agent/llm.py  模型连接与一次模型调用（docs/agent-plan.md 第 8.1、10.3 节）。
- 按 AGENT_PROVIDER 建 LangChain 聊天模型：openai_compat（OpenAI 兼容接口：中转站、本地 Ollama）或 anthropic；
  AGENT_MODEL 模型名，AGENT_BASE_URL 接口地址，密钥 OPENAI_API_KEY / ANTHROPIC_API_KEY。
  密钥只在内存里交给 SDK，不打印、不写日志；describe() 只说有没有填。
- SDK 自带重试关掉（max_retries=0），一次 invoke 就是一个 HTTP 请求。Caller.call 是一次模型调用：
  首发 + 最多 1 次重试，只对超时、429、5xx 重试；每个请求发出前单独向 budget 预留，返回后结算：
    有用量 → 按实际；连接被拒 / 429 / 其他 4xx → 记 0（failed）；超时、5xx、断流、有响应但没用量字段 → 预留全额（usage_unknown）。
  预留被拒（budget.Refused）直接往外抛，不重试。
- openai_compat 的 httpx 客户端挂了请求计数钩子（Model.http），只给测试核对实际发出的请求数。
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from agent import budget, config

KEYS = ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
ATTEMPTS = 2                    # 每次模型调用最多 2 个 HTTP 请求：首发 + 1 次重试


class ModelError(Exception):
    """一次模型调用失败。retryable：失败原因本身可重试（超时、429、5xx），只是这次调用的 2 次都用完了。"""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class HttpCounter:
    n: int = 0

    def hook(self, request: httpx.Request) -> None:
        self.n += 1


@dataclass
class Model:
    chat: BaseChatModel
    provider: str = "fake"
    name: str = "fake"
    http: HttpCounter = field(default_factory=HttpCounter)


def settings() -> dict[str, str]:
    """环境变量 > .env；只取 KEYS 里的键。"""
    vals: dict[str, str] = {}
    if config.ENV_FILE.exists():
        from dotenv import dotenv_values
        vals = {k: v for k, v in dotenv_values(config.ENV_FILE).items() if k in KEYS and v}
    return {k: os.environ.get(k) or vals.get(k, "") for k in KEYS}


def describe(s: dict[str, str]) -> dict[str, str | bool]:
    """可以打印的配置摘要：不含密钥，只说有没有填。"""
    key = "ANTHROPIC_API_KEY" if s["AGENT_PROVIDER"] == "anthropic" else "OPENAI_API_KEY"
    return {"provider": s["AGENT_PROVIDER"], "model": s["AGENT_MODEL"], "base_url": s["AGENT_BASE_URL"],
            "key_set": bool(s[key])}


def build(s: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None,
          limits: config.Limits | None = None) -> Model:
    """按配置建模型。transport 只给测试用（httpx.MockTransport，不联网）。"""
    s, lim = s or settings(), limits or config.current().limits
    provider, name = s["AGENT_PROVIDER"], s["AGENT_MODEL"]
    if not name:
        raise ValueError("没有设置 AGENT_MODEL（写在仓库根目录 .env）")
    counter = HttpCounter()
    if provider == "openai_compat":
        from langchain_openai import ChatOpenAI
        if not (s["AGENT_BASE_URL"] and s["OPENAI_API_KEY"]):
            raise ValueError("openai_compat 需要 AGENT_BASE_URL 和 OPENAI_API_KEY（写在 .env）")
        client = httpx.Client(timeout=lim.request_timeout, transport=transport,
                              event_hooks={"request": [counter.hook]})
        chat = ChatOpenAI(model=name, base_url=s["AGENT_BASE_URL"], api_key=s["OPENAI_API_KEY"], max_retries=0,
                          http_client=client, temperature=0, max_tokens=lim.max_tokens, stream_usage=False,
                          http_socket_options=())     # 不让 langchain 换传输层，保留 httpx 读 HTTP(S)_PROXY
    elif provider == "anthropic":
        # 本机没有 Claude 密钥，这条路只按接口写法接上，未实测（P1.5 交接记录）
        from langchain_anthropic import ChatAnthropic
        if not s["ANTHROPIC_API_KEY"]:
            raise ValueError("anthropic 需要 ANTHROPIC_API_KEY（写在 .env）")
        chat = ChatAnthropic(model=name, api_key=s["ANTHROPIC_API_KEY"], max_retries=0, temperature=0,
                             max_tokens=lim.max_tokens, default_request_timeout=lim.request_timeout)
    else:
        raise ValueError(f"未知 AGENT_PROVIDER {provider!r}；可用：openai_compat、anthropic")
    return Model(chat, provider, name, counter)


def _errors(name: str) -> tuple[type, ...]:
    """openai 和 anthropic 两个 SDK 里同名的异常类。anthropic 只在装了时才算。"""
    out = [getattr(openai, name)]
    try:
        import anthropic
        out.append(getattr(anthropic, name))
    except ImportError:
        pass
    return tuple(out)


def classify(e: Exception) -> tuple[str, bool, str]:
    """(结算状态, 能否重试, 原因)。"""
    if isinstance(e, _errors("APITimeoutError")):
        return "usage_unknown", True, "timeout"
    if isinstance(e, _errors("RateLimitError")):
        return "failed", True, "429"
    if isinstance(e, _errors("InternalServerError")):
        return "usage_unknown", True, f"{getattr(e, 'status_code', 500)}"
    if isinstance(e, _errors("APIStatusError")):
        return "failed", False, f"{getattr(e, 'status_code', '4xx')}"
    if isinstance(e, _errors("APIConnectionError")):
        if isinstance(e.__cause__, httpx.ConnectError):      # 连不上，请求没发出去
            return "failed", False, "connect"
        return "usage_unknown", False, "connection"          # 发出后断开：可能已计费
    return "usage_unknown", False, type(e).__name__


def usage_of(msg: AIMessage) -> tuple[int, int, int] | None:
    """(输入，输出，缓存命中) token；响应里没有用量字段时 None。"""
    meta = msg.usage_metadata
    if not meta:
        return None
    cache = (meta.get("input_token_details") or {}).get("cache_read") or 0
    return int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0), int(cache)


def estimate(messages: list[BaseMessage], tools: list[dict[str, Any]]) -> int:
    """输入 token 估计：消息正文 + 工具调用参数 + 工具说明，按 budget.tokens 粗估（偏高）。"""
    parts = [json.dumps(tools, ensure_ascii=False)]
    for m in messages:
        parts.append(m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False))
        parts += [json.dumps(c["args"], ensure_ascii=False) for c in getattr(m, "tool_calls", None) or ()]
    return sum(budget.tokens(p) for p in parts) + 4 * len(messages)


class Caller:
    """绑好工具的模型 + 记账器。call() 是一次模型调用（call_index 由图给，同一调用的重试共用）。"""

    def __init__(self, model: Model, tools: list, ledger: budget.Budget):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        self.model, self.ledger = model, ledger
        self.bound = model.chat.bind_tools(tools)
        self.schemas = [convert_to_openai_tool(t) for t in tools]
        self.requests = 0                       # 本 Caller 发出的 HTTP 请求（含失败），图按它累计

    def call(self, messages: list[BaseMessage], *, turn_id: str, call_index: int,
             thread_id: str | None = None, attempts: int = ATTEMPTS) -> AIMessage:
        """attempts：这次最多发几个请求（图按本轮剩下的 HTTP 次数给，不超过 ATTEMPTS）。"""
        est = estimate(messages, self.schemas)
        reason = ""
        for attempt in range(1, min(attempts, ATTEMPTS) + 1):
            r = self.ledger.reserve(turn_id=turn_id, call_index=call_index, attempt=attempt, est_input=est,
                                    thread_id=thread_id)
            self.requests += 1
            try:
                msg = self.bound.invoke(messages)
            except Exception as e:      # noqa: BLE001  提供方的各种错误都要先结算这笔预留
                status, retry, reason = classify(e)
                self.ledger.settle(r, status, reason=reason)
                if not retry:
                    raise ModelError(f"模型调用失败（{reason}）", retryable=False) from e
                continue
            if (u := usage_of(msg)) is None:
                self.ledger.settle(r, "usage_unknown", reason="no usage")
            else:
                self.ledger.settle(r, "settled", input_tokens=u[0], output_tokens=u[1], cache_read=u[2])
            return msg
        raise ModelError(f"模型调用失败，重试已用完（{reason}）", retryable=True)
