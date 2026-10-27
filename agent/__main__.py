"""
agent/__main__.py  命令行问答（阶段 3）：python -m agent "问题" [--thread ID]
- 同一 --thread 可以追问（对话状态在 agent_data/state.db）；不写就新开一个，并打印它的 id。
- --check 只打印配置摘要（不含密钥）、上限、单价和一轮最坏花费，不调模型；--usage 打印今日已用金额。
- 记账走个人一档（agent/budget.py，额度 AGENT_BUDGET_PERSONAL_DAILY，北京时间按日切）。
"""
import argparse
import sys
import uuid

from agent import budget, config, graph, llm


def _check(s: dict, ledger: budget.Budget | None) -> None:
    lim = config.current().limits
    print("配置：", llm.describe(s))
    print(f"上限：模型调用 {lim.model_calls} 次、工具 {lim.tool_rounds} 轮、提交 {lim.answers} 次、HTTP {lim.http} 个；"
          f"单次输出 {lim.max_tokens} token，单次请求 {lim.request_timeout:g} 秒，单轮 {lim.turn_timeout:g} 秒")
    if ledger is None:
        return
    try:
        p = ledger.price()
    except budget.Refused as e:
        print(e)
        return
    est = graph.max_input(lim)
    worst = lim.http * ledger.worst_request(est)
    print(f"单价（{p.effective} 起，美元 / 百万 token）：输入 {p.input}、输出 {p.output}、缓存命中 {p.cache_read}；"
          f"倍率时段 {len(p.peak)} 组")
    print(f"单次请求输入上界约 {est} token（不含之前几轮的问答）；一轮最坏花费约 {worst:.4f} 美元；今日额度 {lim.budget_personal_daily} 美元"
          + ("" if worst <= lim.budget_personal_daily else "（不够一轮最坏情况，可能在中途被拒）"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent", description="足球预测系统问答（只读）")
    ap.add_argument("question", nargs="?", help="问题")
    ap.add_argument("--thread", help="对话 id；同一 id 可以追问，不写就新开一个")
    ap.add_argument("--check", action="store_true", help="只打印配置、上限、单价和一轮最坏花费，不调模型")
    ap.add_argument("--usage", action="store_true", help="打印今日已用金额")
    a = ap.parse_args(argv)
    cfg, s = config.current(), llm.settings()
    ledger = budget.Budget(s["AGENT_PROVIDER"], s["AGENT_MODEL"]) if s["AGENT_MODEL"] else None
    if a.check:
        _check(s, ledger)
    if a.usage and ledger:
        used, n = ledger.used_today()
        print(f"今日（北京时间）已用 {used:.4f} / {cfg.limits.budget_personal_daily} 美元，{n} 个请求")
    if a.check or a.usage:
        return 0
    if not a.question:
        ap.error("要给一个问题，或用 --check / --usage")
    model = llm.build(s)
    ledger = budget.Budget(model.provider, model.name)
    thread = a.thread or uuid.uuid4().hex[:8]
    with graph.saver(cfg.state_path) as ck:
        st = graph.ask(graph.build(model, ledger, ck), a.question, cfg.clock(), thread)
    cost = sum(r["cost_usd"] or 0 for r in ledger.turn_rows(st["turn_id"]))
    used, _ = ledger.used_today()
    print(st["output"])
    print(f"\n[对话 {thread}｜{st['outcome']}｜模型调用 {st['model_calls']} 次、工具 {st['tool_rounds']} 轮、"
          f"提交 {st['answers']} 次、HTTP {st['http']} 个｜本轮 {cost:.4f} 美元，"
          f"今日 {used:.4f} / {cfg.limits.budget_personal_daily} 美元]")
    if st.get("error"):
        print(f"[{st['error']}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
