"""
agent/budget.py  额度：按金额预留再结算（docs/agent-plan.md 第 10.3 节），P3 先做命令行 / MCP 的个人一档。
- 记账单位是每一次 HTTP 请求：发请求前 reserve() 按「输入 token 估计 + max_tokens」和这次请求可能落到的
  最高倍率预留一笔，个人当日额度够、本轮 HTTP 请求数和模型调用数都没到上限才写入；调用后 settle()：
  有用量按实际结算（倍率取请求起止之间的最高值），明确没生成的失败记 0，超时 / 断流按预留全额记 usage_unknown。
- 原子：检查和写入在同一个 BEGIN IMMEDIATE 事务里，不在内存里计数。
- 当日已用 = 北京时间当天的 settled + usage_unknown + 未过期的 reserved。预留过期时间 = 单轮总超时 + RESERVE_GRACE；
  过期后不再计入，若之后又结算回来照样记账。
- 只读写 cfg.usage_path（agent_data/usage.db），这是 agent/ 里唯一写 SQL 的地方（tests/test_agent_boundary.py 放行）；
  不碰实盘库和 FotMob 库。
- 单价表 cfg.prices_path（agent/prices.toml）：同模型取生效日期 ≤ 当天里最新的一条；表里没有的模型拒绝。
P6 再加每人 / 全站的日、月额度和并发计数。
"""
import contextlib
import pathlib
import sqlite3
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from agent import config

BJ = timezone(timedelta(hours=8))
RESERVE_GRACE = 120.0          # 秒：预留在单轮总超时之后再保留这么久
PERSONAL = "personal"

_SCHEMA = """CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    tier TEXT NOT NULL, user TEXT NOT NULL, thread_id TEXT, turn_id TEXT NOT NULL,
    call_index INTEGER NOT NULL, attempt INTEGER NOT NULL,
    provider TEXT NOT NULL, model TEXT NOT NULL, price_effective TEXT NOT NULL,
    status TEXT NOT NULL,            -- reserved / settled / failed / usage_unknown
    reason TEXT,
    est_input INTEGER NOT NULL, max_output INTEGER NOT NULL, multiplier REAL NOT NULL,
    reserved_usd REAL NOT NULL, cost_usd REAL,
    input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
    bj_day TEXT NOT NULL,
    created REAL NOT NULL, expires REAL NOT NULL, settled REAL)"""
_INDEX = "CREATE INDEX IF NOT EXISTS requests_day ON requests (tier, user, bj_day)"
_USED = """SELECT COALESCE(SUM(CASE WHEN status IN ('settled', 'usage_unknown') THEN cost_usd
                                    WHEN status = 'reserved' AND expires > ? THEN reserved_usd
                                    ELSE 0 END), 0), COUNT(*)
           FROM requests WHERE tier = ? AND user = ? AND bj_day = ?"""
_TURN = "SELECT COUNT(*), COUNT(DISTINCT call_index) FROM requests WHERE turn_id = ?"
_HAS_CALL = "SELECT 1 FROM requests WHERE turn_id = ? AND call_index = ? LIMIT 1"
_INSERT = """INSERT INTO requests (tier, user, thread_id, turn_id, call_index, attempt, provider, model,
                                   price_effective, status, est_input, max_output, multiplier, reserved_usd,
                                   bj_day, created, expires)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?, ?, ?)"""
_ROW = "SELECT status, created, provider, model, price_effective, reserved_usd FROM requests WHERE id = ?"
_SETTLE = """UPDATE requests SET status = ?, reason = ?, cost_usd = ?, input_tokens = ?, output_tokens = ?,
                                 cache_read_tokens = ?, settled = ? WHERE id = ? AND status = 'reserved'"""
_ROWS = """SELECT id, call_index, attempt, status, reason, reserved_usd, cost_usd, input_tokens, output_tokens,
                  cache_read_tokens FROM requests WHERE turn_id = ? ORDER BY id"""


class Refused(Exception):
    """预留被拒：余额不够、本轮请求数或模型调用数到上限、单价表没有这个模型。不发请求。"""


@dataclass(frozen=True)
class Peak:
    multiplier: float
    days: frozenset[int]                       # 1 = 周一 … 7 = 周日
    hours: tuple[tuple[time, time], ...]       # 北京时间，含起点、不含终点

    def covers(self, t: datetime) -> bool:
        bj = t.astimezone(BJ)
        clock = bj.time().replace(tzinfo=None)
        return bj.isoweekday() in self.days and any(a <= clock < b for a, b in self.hours)


@dataclass(frozen=True)
class Price:
    provider: str
    name: str
    effective: date
    input: float                 # 美元 / 百万 token
    output: float
    cache_read: float
    peak: tuple[Peak, ...] = ()

    def multiplier(self, t: datetime) -> float:
        return max([p.multiplier for p in self.peak if p.covers(t)], default=1.0)

    def worst(self, start: datetime, end: datetime) -> float:
        """[start, end] 内的最高倍率：查两端和其间每个整分钟（倍率时段的边界都是整分钟）。"""
        points, t = [start, end], start.replace(second=0, microsecond=0) + timedelta(minutes=1)
        while t < end:
            points.append(t)
            t += timedelta(minutes=1)
        return max(self.multiplier(p) for p in points)

    def cost(self, input_tokens: int, output_tokens: int, cache_read: int = 0, multiplier: float = 1.0) -> float:
        """input_tokens 含缓存命中的部分（langchain usage_metadata 的口径），命中部分按 cache_read 单价。"""
        fresh = max(input_tokens - cache_read, 0)
        return (fresh * self.input + cache_read * self.cache_read + output_tokens * self.output) * multiplier / 1e6


def _clock(s: str) -> time:
    return time.max if s == "24:00" else time.fromisoformat(s)


def _peak(d: dict) -> Peak:
    hours = []
    for h in d["hours"]:
        a, b = h.split("-")
        hours.append((_clock(a), _clock(b)))
    return Peak(float(d["multiplier"]), frozenset(int(x) for x in d["days"]), tuple(hours))


def load_prices(path: str) -> list[Price]:
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    return [Price(m["provider"], m["name"], date.fromisoformat(m["effective"]), float(m["input"]),
                  float(m["output"]), float(m.get("cache_read", m["input"])),
                  tuple(_peak(p) for p in m.get("peak", ()))) for m in doc.get("model", ())]


def price_for(prices: list[Price], provider: str, name: str, day: date) -> Price:
    hits = [p for p in prices if p.provider == provider and p.name == name and p.effective <= day]
    if not hits:
        raise Refused(f"单价表里没有 {provider} / {name}（{day} 起生效的），不调用")
    return max(hits, key=lambda p: p.effective)


def tokens(text: str) -> int:
    """输入 token 的粗估（偏高）：中日韩字符各算 1，其余每 4 个字符算 1，另加 1。"""
    cjk = sum(1 for ch in text if "\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef")
    return cjk + (len(text) - cjk) // 4 + 1


@dataclass(frozen=True)
class Reservation:
    id: int
    usd: float
    multiplier: float


@contextlib.contextmanager
def _tx(path: str) -> Iterator[sqlite3.Connection]:
    """一个 BEGIN IMMEDIATE 事务：一开始就拿写锁，提交或回滚后关闭。"""
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_SCHEMA)
            conn.execute(_INDEX)
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _ts(t: datetime) -> float:
    return t.timestamp()


class Budget:
    """一个提供方 / 模型的记账器。cfg 默认取 config.current()；user 是个人一档的使用者名（命令行写 local）。"""

    def __init__(self, provider: str, model: str, user: str = "local", cfg: config.AgentConfig | None = None):
        self.cfg = cfg or config.current()
        self.provider, self.model, self.user = provider, model, user
        self.prices = load_prices(self.cfg.prices_path)

    def price(self, t: datetime | None = None) -> Price:
        t = t or self.cfg.clock()
        return price_for(self.prices, self.provider, self.model, t.astimezone(BJ).date())

    def worst_request(self, est_input: int) -> float:
        """输入 est_input token 时单次请求的最高预留（倍率按表里最高）：一轮最坏 = HTTP 上限 × 这个数。"""
        p = self.price()
        top = max([x.multiplier for x in p.peak], default=1.0)
        return p.cost(est_input, self.cfg.limits.max_tokens, 0, max(top, 1.0))

    def reserve(self, *, turn_id: str, call_index: int, attempt: int, est_input: int,
                thread_id: str | None = None) -> Reservation:
        lim, now = self.cfg.limits, self.cfg.clock()
        price = self.price(now)
        mult = price.worst(now, now + timedelta(seconds=lim.request_timeout))
        usd = price.cost(est_input, lim.max_tokens, 0, mult)
        day = now.astimezone(BJ).date().isoformat()
        expires = _ts(now) + lim.turn_timeout + RESERVE_GRACE
        with _tx(self.cfg.usage_path) as conn:
            http, calls = conn.execute(_TURN, (turn_id,)).fetchone()
            if http >= lim.http:
                raise Refused(f"本轮 HTTP 请求已到上限 {lim.http}")
            new_call = conn.execute(_HAS_CALL, (turn_id, call_index)).fetchone() is None
            if new_call and calls >= lim.model_calls:
                raise Refused(f"本轮模型调用已到上限 {lim.model_calls}")
            used, _ = conn.execute(_USED, (_ts(now), PERSONAL, self.user, day)).fetchone()
            if used + usd > lim.budget_personal_daily:
                raise Refused(f"今日额度不够：已用 {used:.4f}，这次预留 {usd:.4f}，上限 {lim.budget_personal_daily} 美元")
            cur = conn.execute(_INSERT, (PERSONAL, self.user, thread_id, turn_id, call_index, attempt, self.provider,
                                         self.model, price.effective.isoformat(), est_input, lim.max_tokens, mult,
                                         usd, day, _ts(now), expires))
            return Reservation(cur.lastrowid, usd, mult)

    def settle(self, r: Reservation, status: str, *, input_tokens: int | None = None,
               output_tokens: int | None = None, cache_read: int | None = None, reason: str | None = None) -> float:
        """status：settled（要给用量）/ failed（记 0）/ usage_unknown（记预留全额）。返回记下的金额。"""
        if status not in ("settled", "failed", "usage_unknown"):
            raise ValueError(status)
        if status == "settled" and (input_tokens is None or output_tokens is None):
            raise ValueError("settled 要给 input_tokens 和 output_tokens")
        now = self.cfg.clock()
        with _tx(self.cfg.usage_path) as conn:
            row = conn.execute(_ROW, (r.id,)).fetchone()
            if row is None or row[0] != "reserved":
                raise ValueError(f"预留 {r.id} 不存在或已结算")
            created, provider, model, effective, reserved = row[1:]
            if status == "settled":
                price = next(p for p in self.prices if (p.provider, p.name, p.effective.isoformat())
                             == (provider, model, effective))
                start = datetime.fromtimestamp(created, timezone.utc)
                cost = price.cost(input_tokens, output_tokens, cache_read or 0, price.worst(start, max(now, start)))
            else:
                cost = 0.0 if status == "failed" else reserved
            conn.execute(_SETTLE, (status, reason, cost, input_tokens, output_tokens, cache_read, _ts(now), r.id))
            return cost

    def used_today(self) -> tuple[float, int]:
        """(当日已用金额，当日请求笔数)；北京时间按日切。"""
        now = self.cfg.clock()
        with _tx(self.cfg.usage_path) as conn:
            used, n = conn.execute(_USED, (_ts(now), PERSONAL, self.user,
                                           now.astimezone(BJ).date().isoformat())).fetchone()
        return float(used), int(n)

    def turn_rows(self, turn_id: str) -> list[dict]:
        """本轮每笔请求（评测和测试用）。"""
        keys = ("id", "call_index", "attempt", "status", "reason", "reserved_usd", "cost_usd",
                "input_tokens", "output_tokens", "cache_read_tokens")
        with _tx(self.cfg.usage_path) as conn:
            return [dict(zip(keys, r)) for r in conn.execute(_ROWS, (turn_id,)).fetchall()]
