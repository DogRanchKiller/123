"""
agent/eval/agent.py  Agent 问答评测（docs/agent-dev.md 第 8 节 P3 出口证据）。评测集 agent/eval/agent.jsonl，一行一题：
  {"id", "question", "expect", "thread"?, "note"?}；同一 thread 的题按顺序在同一对话里问（追问）。
  .venv-ml/bin/python -m agent.eval.agent --estimate            # 离线估算花费，不调模型（工具在本机库上真跑一遍量返回大小）
  .venv-ml/bin/python -m agent.eval.agent --run [--limit N]     # 真实调用模型，会花钱：先看 --estimate，经用户同意再跑
结果逐题写到 agent_data/eval/agent_<时间>.jsonl（不进版本库），最后打印指标：
- first_pass：有提交的题里，第 1 次提交就通过校验的比例；passed：最终通过（含重答）的比例；
- degraded：降级、出错、被拒、超时的比例；
- wording_mismatch：通过的答案里，数前最近的时点词与 kind 对不上的比例（存档 / 开球前 / 赛后的数写成「现在」，
  或首次存档、临场存档、开球前最后一轮互相写反；启发式，观察项）；
- allow_reject：所有提交里被第 1 条（数字写法）打回的比例，以及打回的写法，供增补放行表；
- cost：用量库里这几轮的实际金额。
"""
import argparse
import json
import pathlib
import re
import time
from collections import Counter
from datetime import datetime, timezone

from agent import budget, config, graph, llm, prompts
from agent.facts.verify import PLACEHOLDER

EVAL_FILE = pathlib.Path(__file__).with_name("agent.jsonl")
OUT = config.ROOT / "agent_data" / "eval"
NOW_WORDS = ("现在", "当前", "目前", "最新", "本轮", "此刻")
# 文字里说的是哪一种看法：占位前最近的一个词算数。四种看法之间写反就算错位
CLAIM_WORDS = {"current": NOW_WORDS, "first_archive": ("首次存档",), "near_archive": ("临场",),
               "last_pre_kickoff": ("最后一轮",)}
AFTER_KINDS = {"grading", "score"}  # 赛后的数只查「写成现在」，评分常和存档写在一起，不查存档词
_CLAIM = re.compile("|".join(sorted((re.escape(w) for ws in CLAIM_WORDS.values() for w in ws),
                                    key=len, reverse=True)))
_CLAIM_KIND = {w: k for k, ws in CLAIM_WORDS.items() for w in ws}
WINDOW = 12                       # 占位前多少个字算「旁边」
_HITS = re.compile(r"数字写法：(.+?)。所有数")


def load(path: pathlib.Path = EVAL_FILE) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)) or not all(it.get("question") for it in items):
        raise ValueError("评测集 id 重复或缺 question")
    return items


def wording_mismatch(answer: dict) -> list[str]:
    """通过的答案里，占位前最近的时点词（「现在」类、首次存档、临场、最后一轮）与该事实的 kind
    对不上的占位 id：过去的看法写成现在、首次存档与开球前最后一轮写反都算；评分和比分只查写成现在。
    现算、成绩单、知识库、阵容，以及旁边没有时点词的占位不判断。"""
    text, out = answer.get("text", ""), []
    kinds = {f.get("id"): f.get("kind") for f in answer.get("facts") or [] if isinstance(f, dict)}
    for m in PLACEHOLDER.finditer(text):
        kind = kinds.get(m.group(1))
        words = list(_CLAIM.finditer(text, max(0, m.start() - WINDOW), m.start()))
        if not words:
            continue
        claimed = _CLAIM_KIND[words[-1].group()]
        if kind in CLAIM_WORDS and claimed != kind or kind in AFTER_KINDS and claimed == "current":
            out.append(m.group(1))
    return out


def rule1_hits(verify_log: list[list[dict]]) -> list[str]:
    """每次提交里被第 1 条打回的写法。"""
    out = []
    for issues in verify_log:
        for i in issues:
            if i["rule"] == 1 and (m := _HITS.search(i["message"])):
                out += m.group(1).split("、")
    return out


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    submitted = [r for r in rows if r["verify_log"]]
    passed = [r for r in rows if r["outcome"] in ("passed", "passed_retry")]
    subs = [v for r in rows for v in r["verify_log"]]
    rule1 = [v for v in subs if any(i["rule"] == 1 for i in v)]
    mism = [r for r in passed if r.get("answer") and wording_mismatch(r["answer"])]
    rate = (lambda a, b: round(a / b, 3) if b else None)
    return {"n": n, "outcomes": dict(Counter(r["outcome"] for r in rows)),
            "first_pass": rate(sum(1 for r in submitted if not r["verify_log"][0]), len(submitted)),
            "passed": rate(len(passed), n),
            "degraded": rate(sum(1 for r in rows if r["outcome"] not in ("passed", "passed_retry")), n),
            "wording_mismatch": rate(len(mism), len(passed)), "wording_mismatch_ids": [r["id"] for r in mism],
            "submissions": len(subs), "allow_reject": rate(len(rule1), len(subs)),
            "allow_reject_hits": dict(Counter(h for r in rows for h in rule1_hits(r["verify_log"])).most_common()),
            "rules": dict(Counter(i["rule"] for v in subs for i in v)),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
            "http": sum(r["http"] for r in rows), "model_calls": sum(r["model_calls"] for r in rows)}


def _sample_returns() -> list[int]:
    """本机库上几种典型工具调用的返回大小（估计 token）。"""
    from agent.tools import get_match, kb_search, list_upcoming, recent_results, scorecard
    calls = [lambda: list_upcoming("法甲", 72), lambda: recent_results("英超", 3), scorecard,
             lambda: kb_search("替换主模型的条件")]
    rr = recent_results("法甲", 3)["blocks"]
    if rr:
        calls.append(lambda: get_match(rr[0]["match_id"]))
    out = []
    for c in calls:
        try:
            out.append(budget.tokens(json.dumps(c(), ensure_ascii=False, separators=(",", ":"))))
        except Exception as e:          # noqa: BLE001  估算时某个工具不可用（如知识库没建）就跳过
            print(f"跳过一次样本调用：{e}")
    return out


def estimate(items: list[dict]) -> dict:
    """典型：每题 3 次调用（查 → 交 → 偶尔重答），每次带上已有工具返回；上界：每题 12 个请求、每个按输入上界预留。"""
    s, lim = llm.settings(), config.current().limits
    ledger = budget.Budget(s["AGENT_PROVIDER"], s["AGENT_MODEL"])
    p, now = ledger.price(), config.current().clock()
    from langchain_core.utils.function_calling import convert_to_openai_tool
    schemas = json.dumps([convert_to_openai_tool(t) for t in graph._tools().values()], ensure_ascii=False)
    base = budget.tokens(prompts.system(now)) + budget.tokens(schemas)
    rets = _sample_returns()
    tool = sum(rets) // max(len(rets), 1)
    answer = 600
    typical_in = sum((base + 40, base + 40 + tool + 80, base + 40 + tool + 80 + answer))
    typical_out = 80 + answer + answer // 2
    mult = max([x.multiplier for x in p.peak], default=1.0)
    n = len(items)
    per_typ = p.cost(typical_in, typical_out)
    worst = lim.http * ledger.worst_request(graph.max_input(lim))
    return {"questions": n, "price": {"model": s["AGENT_MODEL"], "effective": p.effective.isoformat(),
                                      "input": p.input, "output": p.output, "peak_multiplier": mult},
            "base_prompt_tokens": base, "sample_tool_returns": rets,
            "typical_per_question": {"input": typical_in, "output": typical_out, "usd": round(per_typ, 4)},
            "typical_total_usd": {"off_peak": round(per_typ * n, 4), "peak": round(per_typ * n * mult, 4)},
            "worst_per_question_usd": round(worst, 4), "worst_total_usd": round(worst * n, 4),
            "daily_limit_usd": lim.budget_personal_daily}


def run(items: list[dict]) -> tuple[pathlib.Path, list[dict]]:
    cfg = config.current()
    model = llm.build()
    ledger = budget.Budget(model.provider, model.name)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    path, rows = OUT / f"agent_{stamp}.jsonl", []
    with graph.saver(str(OUT / f"state_{stamp}.db")) as ck, path.open("w", encoding="utf-8") as f:
        app = graph.build(model, ledger, ck)
        for it in items:
            t0 = time.monotonic()
            thread = f"{stamp}-{it.get('thread') or it['id']}"
            s = graph.ask(app, it["question"], cfg.clock(), thread)
            turn = ledger.turn_rows(s["turn_id"])
            r = {"id": it["id"], "question": it["question"], "expect": it.get("expect"), "outcome": s["outcome"],
                 "output": s["output"], "answer": s.get("answer"), "verify_log": s["verify_log"],
                 "trace": s["trace"], "model_calls": s["model_calls"], "tool_rounds": s["tool_rounds"],
                 "answers": s["answers"], "http": s["http"], "usage": s["usage"], "error": s.get("error"),
                 "cost_usd": sum(x["cost_usd"] or 0 for x in turn), "seconds": round(time.monotonic() - t0, 1)}
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{r['id']}\t{r['outcome']}\t调用 {r['model_calls']}\tHTTP {r['http']}\t{r['cost_usd']:.4f} 美元",
                  flush=True)
            if r["outcome"] == "refused":
                print("预留被拒，停止：", r["error"])
                break
    return path, rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent.eval.agent")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--estimate", action="store_true", help="离线估算花费，不调模型")
    mode.add_argument("--run", action="store_true", help="真实调用模型（会花钱）")
    ap.add_argument("--limit", type=int, help="只跑前 N 题")
    a = ap.parse_args(argv)
    items = load()[:a.limit] if a.limit else load()
    if a.estimate:
        print(json.dumps(estimate(items), ensure_ascii=False, indent=1))
        return
    path, rows = run(items)
    print(json.dumps({"file": str(path), **metrics(rows)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
