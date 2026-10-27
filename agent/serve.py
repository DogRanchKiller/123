"""
agent/serve.py  网站对话服务（docs/agent-plan.md 第 10 节，P6）：python -m agent.serve [--port 8100]
- 只听 127.0.0.1（不能改），浏览器不直接访问；Next.js 的 /api/chat 路由和登录动作在服务端转发过来。
- 每个请求都要带服务令牌（请求头 X-Service-Token，等于 .env 的 AGENT_SERVICE_TOKEN，至少 32 个字符），
  不对一律 401，带 reason=service_token（网站据此区分"服务配置错"和"没登录"）。
  用户只从会话（请求头 X-Session，agent/access.py）得出，请求体里的用户 id 一概不读。
- POST /chat：JSON {question, thread_id?}，还要 X-CSRF（绑定会话的令牌）；只收 application/json，其余方法 405。
  校验顺序：令牌 → 会话 → CSRF → 请求体 → 并发占用（每人 1、全站 limits.concurrency，满了 429）→ 跑一轮。
  通过后返回 NDJSON 流：{"type":"step",...} 若干行，最后一行 {"type":"done",...}（或 {"type":"error"}）；
  久无进度时插 {"type":"ping"}。
  一轮在单独的线程里跑完，浏览器断开也不中断，结束后释放并发占用。
- 记账走网站一档（budget.SITE：每人当日、全站当日、全站当月三道上限，北京时间）。
- 对话状态与命令行共用 state.db，键是「site:用户:thread_id」，所以只能续自己的对话。
- POST /login {code} → 会话 id、CSRF 令牌、过期时间；GET /session（X-Session）→ 用户、CSRF 令牌、额度；
  POST /logout（X-Session）→ 吊销这个会话。
"""
import argparse
import contextlib
import hmac
import json
import os
import queue
import re
import sys
import threading
import traceback
import uuid
from collections.abc import Callable, Iterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent import access, budget, config, graph, llm

HOST = "127.0.0.1"
PORT = 8100
MAX_QUESTION = 500                  # 问题最多多少字
HEARTBEAT = 15.0                    # 秒；这么久没有进度就发一行 ping
THREAD_ID = re.compile(r"[0-9a-f]{8,32}")
STEPS = {"agent": "思考中", "tools": "查数据", "verify": "核对数字", "render": "整理答案", "degrade": "整理答案"}


def service_token() -> str:
    """环境变量 > .env 的 AGENT_SERVICE_TOKEN；不打印。"""
    if v := os.environ.get("AGENT_SERVICE_TOKEN"):
        return v
    if config.ENV_FILE.exists():
        from dotenv import dotenv_values
        return dotenv_values(config.ENV_FILE).get("AGENT_SERVICE_TOKEN") or ""
    return ""


def _err(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


async def _json(request: Request) -> dict | None:
    """只认 application/json 的 JSON 对象；别的格式（含表单）返回 None。"""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return None
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _session_info(s: access.Session, cfg: config.AgentConfig, ledger: budget.Budget | None) -> dict:
    out = {"user": s.user, "expires": s.expires, "csrf": access.csrf_token(s, cfg)}
    if ledger is not None:
        out["quota"] = ledger.quota()
    return out


def create_app(model: llm.Model, token: str, cfg: config.AgentConfig | None = None,
               log: Callable[[str], None] | None = None) -> FastAPI:
    """model 由调用方建好（测试注入假模型）；cfg 默认 config.current()。"""
    if len(token) < 32:
        raise ValueError("AGENT_SERVICE_TOKEN 至少 32 个字符（写在仓库根目录 .env）")
    cfg = cfg or config.current()
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    want = token.encode()
    stack = contextlib.ExitStack()
    checkpointer = stack.enter_context(graph.saver(cfg.state_path))

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            stack.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    budget.clear_expired_slots(cfg)

    def ledger_for(user: str) -> budget.Budget:
        return budget.Budget(model.provider, model.name, user, cfg, tier=budget.SITE)

    @app.middleware("http")
    async def need_token(request: Request, call_next):
        got = request.headers.get("x-service-token", "").encode()
        if not hmac.compare_digest(got, want):
            return _err(401, "服务令牌不对", reason="service_token")
        return await call_next(request)

    @app.post("/login")
    async def login(request: Request):
        body = await _json(request)
        if body is None:
            return _err(415, "只接受 JSON")
        got = access.login(str(body.get("code") or ""), cfg)
        if got is None:
            return _err(401, "邀请码不对或已停用")
        sid, s = got
        return {"session": sid, **_session_info(s, cfg, None)}

    @app.get("/session")
    def session(request: Request):
        s = access.session(request.headers.get("x-session"), cfg)
        if s is None:
            return _err(401, "没有登录或登录已过期")
        return _session_info(s, cfg, ledger_for(s.user))

    @app.post("/logout")
    def logout(request: Request):
        access.logout(request.headers.get("x-session"), cfg)
        return Response(status_code=204)

    @app.post("/chat")
    async def chat(request: Request):
        s = access.session(request.headers.get("x-session"), cfg)
        if s is None:
            return _err(401, "没有登录或登录已过期")
        if not access.csrf_ok(request.headers.get("x-csrf"), s, cfg):
            return _err(403, "页面已过期，请刷新后再问")
        body = await _json(request)
        if body is None:
            return _err(415, "只接受 JSON")
        question = str(body.get("question") or "").strip()
        if not question or len(question) > MAX_QUESTION:
            return _err(400, f"问题要在 1–{MAX_QUESTION} 字之间")
        tid = body.get("thread_id")
        if tid is not None and not (isinstance(tid, str) and THREAD_ID.fullmatch(tid)):
            return _err(400, "thread_id 格式不对")
        tid = tid or uuid.uuid4().hex[:12]
        ledger, slot = ledger_for(s.user), uuid.uuid4().hex
        try:
            ledger.acquire(slot)
        except budget.Busy as e:
            return _err(429, str(e), scope=e.scope)
        events: queue.Queue = queue.Queue()
        threading.Thread(target=_run_turn, daemon=True,
                         args=(model, ledger, checkpointer, question, tid, slot, events, log)).start()
        return StreamingResponse(_drain(events), media_type="application/x-ndjson")

    return app


def _run_turn(model: llm.Model, ledger: budget.Budget, checkpointer, question: str, tid: str, slot: str,
              events: queue.Queue, log: Callable[[str], None]) -> None:
    """跑一轮（单独线程），进度和结果放进 events，最后放 None；无论如何都释放并发占用。"""
    seen = 0

    def step(node: str, update: dict) -> None:
        nonlocal seen
        ev = {"type": "step", "node": node, "label": STEPS.get(node, node)}
        if node == "tools":
            names = [t["name"] for t in update.get("trace", [])[seen:]]
            seen = len(update.get("trace", []))
            ev["tools"] = names
        if node in STEPS:
            events.put(ev)

    try:
        app = graph.build(model, ledger, checkpointer)
        st = graph.ask(app, question, ledger.cfg.clock(), tid, key=f"site:{ledger.user}:{tid}", on_step=step)
        cost = sum(r["cost_usd"] or 0 for r in ledger.turn_rows(st["turn_id"]))
        events.put({"type": "done", "thread_id": tid, "output": st["output"], "outcome": st["outcome"],
                    "cost": round(cost, 6), "quota": ledger.quota()})
        if st.get("error"):
            log(f"[对话 {ledger.user}/{tid}] {st['outcome']}: {st['error']}")
    except Exception:      # noqa: BLE001  任何错误都要给浏览器一个结尾，并释放占用
        log(f"[对话 {ledger.user}/{tid}] 出错\n{traceback.format_exc()}")
        events.put({"type": "error", "thread_id": tid, "error": "服务出错，这一轮没有完成"})
    finally:
        ledger.release(slot)
        events.put(None)


def _drain(events: queue.Queue) -> Iterator[bytes]:
    """逐行输出事件；HEARTBEAT 秒没有新事件时发一行 ping，免得中间的转发层按空闲超时断开。"""
    while True:
        try:
            ev = events.get(timeout=HEARTBEAT)
        except queue.Empty:
            ev = {"type": "ping"}
        if ev is None:
            return
        yield (json.dumps(ev, ensure_ascii=False) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.serve", description="网站对话服务（只听 127.0.0.1）")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    cfg, s = config.current(), llm.settings()
    try:
        model = llm.build(s)
        app = create_app(model, service_token(), cfg)
        worst = cfg.limits.http * budget.Budget(model.provider, model.name, cfg=cfg).worst_request(
            graph.max_input(cfg.limits))
    except (ValueError, budget.Refused) as e:
        print(e, file=sys.stderr)
        return 1
    lim = cfg.limits
    print(f"agent.serve {HOST}:{a.port}｜{llm.describe(s)['model']}｜每人每日 {lim.budget_user_daily:g}、"
          f"全站每日 {lim.budget_site_daily:g}、全站每月 {lim.budget_site_monthly:g} 美元，全站并发 {lim.concurrency}｜"
          f"一轮最坏约 {worst:.4f} 美元", flush=True)
    if worst > lim.budget_user_daily:
        print("提醒：每人每日额度不够一轮最坏情况，这一轮可能在中途被拒", flush=True)
    import uvicorn
    uvicorn.run(app, host=HOST, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
