"""agent/eval/agent.py：评测集格式和指标的算法（不调模型）。只在 .venv-ml 里跑。"""
import pytest

pytest.importorskip("langgraph")

from agent.eval import agent as ev  # noqa: E402


def row(rid: str, outcome: str, vlog: list, answer: dict | None = None, cost: float = 0.01) -> dict:
    return {"id": rid, "outcome": outcome, "verify_log": vlog, "answer": answer, "cost_usd": cost,
            "http": 2, "model_calls": 2}


R1 = {"rule": 1, "fact": None, "message": "text 里出现了数字或数字写法：两场、半球。所有数（含中文数字）都写成占位"}
R5 = {"rule": 5, "fact": "f1", "message": "kind 不符"}


def test_eval_set_loads():
    items = ev.load()
    assert len(items) >= 20 and all(it["expect"] for it in items)
    threads = [it for it in items if it.get("thread")]
    assert len(threads) >= 2 and len({it["thread"] for it in threads}) < len(threads)


def test_wording_mismatch():
    a = {"text": "现在的赢盘概率是 {f1}，首次存档 {f2}。",
         "facts": [{"id": "f1", "kind": "last_pre_kickoff"}, {"id": "f2", "kind": "first_archive"}]}
    assert ev.wording_mismatch(a) == ["f1"]
    assert ev.wording_mismatch({"text": "现在 {f1}", "facts": [{"id": "f1", "kind": "current"}]}) == []
    # 首次存档与开球前最后一轮写反（P3 第二轮 follow_up_2）；离占位最近的词算数
    swap = {"text": "首次存档是 {f1}，开球前最后一轮是 {f2}，首次存档的评分 {f3}，比分 {f4}",
            "facts": [{"id": "f1", "kind": "last_pre_kickoff"}, {"id": "f2", "kind": "first_archive"},
                      {"id": "f3", "kind": "grading"}, {"id": "f4", "kind": "score"}]}
    assert ev.wording_mismatch(swap) == ["f1", "f2"]
    ok = {"text": "首次存档 {f1}，临场存档 {f2}，最后一轮 {f3}",
          "facts": [{"id": "f1", "kind": "first_archive"}, {"id": "f2", "kind": "near_archive"},
                    {"id": "f3", "kind": "last_pre_kickoff"}]}
    assert ev.wording_mismatch(ok) == []


def test_metrics():
    past = {"text": "目前 {f1}", "facts": [{"id": "f1", "kind": "first_archive"}]}
    rows = [row("a", "passed", [[]]), row("b", "passed_retry", [[R1], []], past),
            row("c", "degraded", [[R1, R5], [R5]]), row("d", "error", [])]
    m = ev.metrics(rows)
    assert m["first_pass"] == round(1 / 3, 3) and m["passed"] == 0.5 and m["degraded"] == 0.5
    assert m["wording_mismatch"] == 0.5 and m["wording_mismatch_ids"] == ["b"]
    assert m["submissions"] == 5 and m["allow_reject"] == 0.4
    assert m["allow_reject_hits"] == {"两场": 2, "半球": 2} and m["rules"] == {1: 2, 5: 2}
    assert m["cost_usd"] == 0.04
