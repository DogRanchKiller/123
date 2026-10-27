"""agent/budget.py：单价表、每次 HTTP 请求的预留与结算、北京时间按日切、过期、单轮上限、原子预留；
网站一档（P6）的三道上限、日 / 月恢复、并发占用、跨进程原子预留。
只用临时目录里的 usage.db 和价格表，不联网、不碰 football.db。"""
import multiprocessing
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from agent import budget, config

PRICES = """
[[model]]
provider = "fake"
name = "fake"
effective = "2020-01-01"
input = 1.0
output = 2.0
cache_read = 0.1
peak = [{ multiplier = 2.0, days = [1, 2, 3, 4, 5], hours = ["09:00-12:00", "14:00-18:00"] }]

[[model]]
provider = "fake"
name = "fake"
effective = "2026-11-01"
input = 10.0
output = 20.0

[[model]]
provider = "openai_compat"
name = "m-test"
effective = "2020-01-01"
input = 1.0
output = 2.0
"""
MON_NIGHT = datetime(2026, 10, 26, 13, 0, tzinfo=timezone.utc)      # 北京时间周一 21:00，不在倍率时段
MON_PEAK = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)        # 北京时间周一 10:00


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def ledger_paths(tmp_path) -> dict:
    """临时目录里的 usage.db 和测试价格表（fake / fake、openai_compat / m-test），给 config.override 用。"""
    prices = tmp_path / "prices.toml"
    prices.write_text(PRICES, encoding="utf-8")
    return {"usage_path": str(tmp_path / "usage.db"), "prices_path": str(prices)}


@pytest.fixture
def env(tmp_path):
    """(clock, make)：make(**limits) 返回在临时目录记账的 Budget。"""
    paths, clock = ledger_paths(tmp_path), Clock(MON_NIGHT)

    def make(user: str = "local", tier: str = budget.PERSONAL, **limits) -> budget.Budget:
        cfg = config.AgentConfig(db_path="-", snapshot_path="-", fotmob_path=None, **paths,
                                 limits=config.Limits(**limits), clock=clock)
        return budget.Budget("fake", "fake", user, cfg, tier=tier)
    return clock, make


def test_repo_price_table_loads():
    prices = budget.load_prices(str(config.ROOT / "agent" / "prices.toml"))
    p = budget.price_for(prices, "openai_compat", "DeepSeek-v4.1-flash-1017", date(2026, 10, 27))
    assert (p.input, p.output, p.cache_read) == (0.4, 1.6, 0.008)
    assert p.multiplier(MON_PEAK) == 2.0 and p.multiplier(MON_NIGHT) == 1.0
    sat_peak = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)
    assert p.multiplier(sat_peak) == 1.0
    with pytest.raises(budget.Refused):
        budget.price_for(prices, "openai_compat", "DeepSeek-v4.1-flash-1017", date(2026, 10, 26))


def test_price_by_effective_date_and_unknown_model(env):
    clock, make = env
    b = make()
    assert b.price().input == 1.0
    clock.t = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    assert b.price().input == 10.0 and b.price().cache_read == 10.0      # 不写 cache_read 按 input 算
    with pytest.raises(budget.Refused, match="单价表里没有"):
        budget.Budget("fake", "other", cfg=b.cfg).reserve(turn_id="t", call_index=1, attempt=1, est_input=10)


def test_cost_counts_cache_inside_input():
    p = budget.Price("fake", "fake", date(2026, 1, 1), 1.0, 2.0, 0.1)
    assert p.cost(1_000_000, 0) == pytest.approx(1.0)
    assert p.cost(1_000_000, 500_000, cache_read=400_000) == pytest.approx(0.6 + 0.04 + 1.0)
    assert p.cost(1000, 1000, multiplier=2.0) == pytest.approx(0.006)


def test_peak_window_is_checked_across_the_request(env):
    _, make = env
    p = make().price()
    bj = timezone(timedelta(hours=8))
    t0 = datetime(2026, 10, 26, 8, 59, 30, tzinfo=bj)
    assert p.multiplier(t0) == 1.0 and p.worst(t0, t0 + timedelta(seconds=60)) == 2.0
    t1 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=bj)          # 不含终点
    assert p.multiplier(t1) == 1.0 and p.worst(t1 - timedelta(seconds=1), t1) == 2.0


def test_reserve_then_settle(env):
    clock, make = env
    b = make(max_tokens=1000)
    r = b.reserve(turn_id="t1", call_index=1, attempt=1, est_input=1000)
    assert r.usd == pytest.approx((1000 * 1.0 + 1000 * 2.0) / 1e6) and r.multiplier == 1.0
    assert b.used_today() == (pytest.approx(r.usd), 1)
    cost = b.settle(r, "settled", input_tokens=500, output_tokens=100, cache_read=200)
    assert cost == pytest.approx((300 * 1.0 + 200 * 0.1 + 100 * 2.0) / 1e6)
    assert b.used_today()[0] == pytest.approx(cost)
    with pytest.raises(ValueError, match="已结算"):
        b.settle(r, "failed")


def test_failed_is_zero_and_unknown_is_full(env):
    _, make = env
    b = make()
    r1 = b.reserve(turn_id="t1", call_index=1, attempt=1, est_input=100)
    r2 = b.reserve(turn_id="t1", call_index=1, attempt=2, est_input=100)
    assert b.settle(r1, "failed", reason="429") == 0
    assert b.settle(r2, "usage_unknown", reason="timeout") == pytest.approx(r2.usd)
    rows = b.turn_rows("t1")
    assert [(x["status"], x["reason"], x["attempt"]) for x in rows] == [("failed", "429", 1),
                                                                        ("usage_unknown", "timeout", 2)]
    assert b.used_today()[0] == pytest.approx(r2.usd)
    with pytest.raises(ValueError):
        b.settle(b.reserve(turn_id="t1", call_index=2, attempt=1, est_input=1), "settled")


def test_reservation_uses_peak_multiplier(env):
    clock, make = env
    clock.t = MON_PEAK
    b = make()
    r = b.reserve(turn_id="t", call_index=1, attempt=1, est_input=1000)
    assert r.multiplier == 2.0
    assert b.settle(r, "settled", input_tokens=1000, output_tokens=0) == pytest.approx(0.002)


def test_daily_limit_refuses_before_writing(env):
    _, make = env
    b = make(max_tokens=1000, budget_personal_daily=0.005)       # 每笔预留 0.003
    b.reserve(turn_id="t", call_index=1, attempt=1, est_input=1000)
    with pytest.raises(budget.Refused, match="今日额度不够"):
        b.reserve(turn_id="t", call_index=2, attempt=1, est_input=1000)
    assert len(b.turn_rows("t")) == 1
    other = make(user="someone", max_tokens=1000, budget_personal_daily=0.005)
    other.reserve(turn_id="u", call_index=1, attempt=1, est_input=1000)       # 按人分开算


def test_day_cuts_at_beijing_midnight(env):
    clock, make = env
    b = make(max_tokens=1000, budget_personal_daily=0.004)
    clock.t = datetime(2026, 10, 27, 15, 59, tzinfo=timezone.utc)            # 北京时间 10-27 23:59
    b.settle(b.reserve(turn_id="a", call_index=1, attempt=1, est_input=1000), "usage_unknown")
    with pytest.raises(budget.Refused):
        b.reserve(turn_id="b", call_index=1, attempt=1, est_input=1000)
    clock.t = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)             # 北京时间 10-28 00:00
    assert b.used_today() == (0, 0)
    b.reserve(turn_id="b", call_index=1, attempt=1, est_input=1000)


def test_expired_reservation_released_but_late_settle_recorded(env):
    clock, make = env
    b = make(max_tokens=1000, turn_timeout=300)
    r = b.reserve(turn_id="t", call_index=1, attempt=1, est_input=1000)
    clock.t += timedelta(seconds=300 + budget.RESERVE_GRACE - 1)
    assert b.used_today()[0] == pytest.approx(r.usd)
    clock.t += timedelta(seconds=2)
    assert b.used_today()[0] == 0
    cost = b.settle(r, "settled", input_tokens=10, output_tokens=10)
    assert cost > 0 and b.used_today()[0] == pytest.approx(cost)


def test_turn_caps_http_and_model_calls(env):
    _, make = env
    b = make()
    for call in range(1, 7):
        for attempt in (1, 2):
            b.reserve(turn_id="t", call_index=call, attempt=attempt, est_input=10)
    with pytest.raises(budget.Refused, match="HTTP"):
        b.reserve(turn_id="t", call_index=6, attempt=3, est_input=10)
    assert len(b.turn_rows("t")) == 12

    c = make(http=20)
    for call in range(1, 7):
        c.reserve(turn_id="u", call_index=call, attempt=1, est_input=10)
    c.reserve(turn_id="u", call_index=6, attempt=2, est_input=10)             # 同一调用的重试不算新调用
    with pytest.raises(budget.Refused, match="模型调用"):
        c.reserve(turn_id="u", call_index=7, attempt=1, est_input=10)


def test_worst_round_bound(env):
    _, make = env
    b = make(max_tokens=2000)
    assert b.worst_request(10000) == pytest.approx((10000 * 1.0 + 2000 * 2.0) * 2.0 / 1e6)


def test_reservation_is_atomic(env):
    """上限刚好够一笔：多个线程同时预留，只有一个通过，库里只有一条。重复多次。"""
    _, make = env
    for round_ in range(5):
        b = make(user=f"u{round_}", max_tokens=1000, budget_personal_daily=0.0045)
        barrier, ok, refused = threading.Barrier(8), [], []

        def go(i: int) -> None:
            barrier.wait()
            try:
                ok.append(b.reserve(turn_id=f"r{round_}-{i}", call_index=1, attempt=1, est_input=1000))
            except budget.Refused:
                refused.append(i)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ok) == 1 and len(refused) == 7
        assert b.used_today()[1] == 1


def test_tokens_estimate_is_rough_upper():
    assert budget.tokens("") == 1
    assert budget.tokens("主队让球") == 5
    assert budget.tokens("abcdefgh") == 3


SITE_CAPS = {"max_tokens": 1000, "budget_user_daily": 0.0045, "budget_site_daily": 0.0075,
             "budget_site_monthly": 0.0105}         # 每笔 0.003：每人每日 1 笔、全站每日 2 笔、全站每月 3 笔


def bj(y: int, m: int, d: int, h: int = 21) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone(timedelta(hours=8)))


def test_site_three_caps_and_day_month_reset(env):
    """网站一档：每人当日、全站当日、全站当月三道上限各自拒绝；次日北京时间 0 点恢复，到了月上限整月拒绝。"""
    clock, make = env
    site = {u: make(u, budget.SITE, **SITE_CAPS) for u in ("alice", "bob", "carol", "dave")}

    def go(u: str):
        """预留后按全额结算（usage_unknown），不然 7 分钟后预留过期就不再计入。"""
        r = site[u].reserve(turn_id=f"{u}-{clock.t.isoformat()}", call_index=1, attempt=1, est_input=1000)
        site[u].settle(r, "usage_unknown")
        return r
    assert go("alice").usd == pytest.approx(0.003)
    with pytest.raises(budget.Refused, match="你今日的额度不够"):
        go("alice")
    go("bob")
    with pytest.raises(budget.Refused, match="全站今日额度不够"):
        go("carol")
    clock.t = bj(2026, 10, 26, 23) + timedelta(minutes=59, seconds=59)
    with pytest.raises(budget.Refused, match="全站今日额度不够"):
        go("carol")
    clock.t = bj(2026, 10, 27, 0)                           # 北京时间次日 0 点
    go("carol")
    with pytest.raises(budget.Refused, match="全站本月额度不够"):
        go("dave")
    for t in (bj(2026, 10, 28), bj(2026, 10, 31, 23)):
        clock.t = t
        with pytest.raises(budget.Refused, match="全站本月额度不够"):
            go("dave")
    clock.t = bj(2026, 11, 1, 0)                            # 次月：单价换成 10 / 20，用更小的请求
    nov = make("dave", budget.SITE, **{**SITE_CAPS, "max_tokens": 100})
    assert nov.reserve(turn_id="nov", call_index=1, attempt=1, est_input=100).usd == pytest.approx(0.003)
    assert [q["used"] for q in nov.quota()] == [pytest.approx(0.003)] * 3


def test_site_and_personal_do_not_mix(env):
    _, make = env
    site = make("local", budget.SITE, **SITE_CAPS)
    site.reserve(turn_id="s", call_index=1, attempt=1, est_input=1000)
    personal = make("local", max_tokens=1000, budget_personal_daily=0.0045)
    assert personal.used_today() == (0, 0)
    personal.reserve(turn_id="p", call_index=1, attempt=1, est_input=1000)
    assert site.used_today()[1] == 1 and personal.used_today()[1] == 1
    assert [q["name"] for q in site.quota()] == ["你今日的额度", "全站今日额度", "全站本月额度"]
    assert [q["name"] for q in personal.quota()] == ["今日额度"]
    with pytest.raises(ValueError):
        make("x", "other")


def test_slots_per_user_and_site(env):
    clock, make = env
    a, b, c, d = (make(u, budget.SITE, concurrency=3) for u in "abcd")
    a.acquire("a1")
    with pytest.raises(budget.Busy) as e:
        a.acquire("a2")
    assert e.value.scope == "user"
    b.acquire("b1")
    c.acquire("c1")
    with pytest.raises(budget.Busy) as e:
        d.acquire("d1")
    assert e.value.scope == "site"
    a.release("a1")
    d.acquire("d1")                       # a 释放后 d 能进；b、c、d 占满 3 个
    with pytest.raises(budget.Busy) as e:
        a.acquire("a3")
    assert e.value.scope == "site"
    clock.t += timedelta(seconds=config.Limits().turn_timeout + budget.RESERVE_GRACE)
    assert budget.clear_expired_slots(a.cfg) == 3
    make("e", budget.SITE, concurrency=3).acquire("e1")


def test_slot_expiry_frees_a_crashed_turn(env):
    """进程崩溃没释放：过期前一直占着，过期后下次 acquire 自己先清掉。"""
    clock, make = env
    a = make("a", budget.SITE)
    a.acquire("crashed")
    clock.t += timedelta(seconds=config.Limits().turn_timeout + budget.RESERVE_GRACE - 1)
    with pytest.raises(budget.Busy):
        a.acquire("again")
    clock.t += timedelta(seconds=1)
    a.acquire("again")


def _reserve_in_child(paths: dict, user: str, i: int, barrier, out) -> None:
    cfg = config.AgentConfig(db_path="-", snapshot_path="-", fotmob_path=None, **paths, clock=Clock(MON_NIGHT),
                             limits=config.Limits(**SITE_CAPS))
    b = budget.Budget("fake", "fake", user, cfg, tier=budget.SITE)
    barrier.wait()
    try:
        b.reserve(turn_id=f"{user}-{i}", call_index=1, attempt=1, est_input=1000)
        out.put("ok")
    except budget.Refused:
        out.put("refused")


def test_site_reservation_is_atomic_across_threads_and_processes(env, tmp_path):
    """网站一档的上限刚好够一笔：多个线程（同一人 → 每人当日上限；不同人 → 全站当日上限）、多个进程同时预留，
    只有一个通过，库里只有一条。各重复几次，每次换一天。"""
    clock, make = env
    for round_ in range(4):
        clock.t = MON_NIGHT + timedelta(days=round_)
        same = round_ % 2 == 0
        caps = {**SITE_CAPS, "budget_site_daily": 1.0 if same else 0.0045, "budget_site_monthly": 1.0}
        ledgers = [make("t" if same else f"t{i}", budget.SITE, **caps) for i in range(8)]
        barrier, ok = threading.Barrier(8), []

        def go(i: int) -> None:
            barrier.wait()
            try:
                ok.append(ledgers[i].reserve(turn_id=f"t{round_}-{i}", call_index=1, attempt=1, est_input=1000))
            except budget.Refused:
                pass
        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ok) == 1 and sum(b.used_today()[1] for b in (ledgers[:1] if same else ledgers)) == 1
    ctx = multiprocessing.get_context("spawn")
    for round_ in range(2):
        (tmp_path / f"p{round_}").mkdir()
        paths = ledger_paths(tmp_path / f"p{round_}")
        barrier, out = ctx.Barrier(4), ctx.Queue()
        procs = [ctx.Process(target=_reserve_in_child, args=(paths, "p", i, barrier, out)) for i in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        got = sorted(out.get(timeout=5) for _ in procs)
        assert got == ["ok", "refused", "refused", "refused"]
        cfg = config.AgentConfig(db_path="-", snapshot_path="-", fotmob_path=None, **paths, clock=Clock(MON_NIGHT))
        assert budget.Budget("fake", "fake", "p", cfg, tier=budget.SITE).used_today()[1] == 1
