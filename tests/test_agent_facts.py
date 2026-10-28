"""agent/facts：第 8.3 节第 1–8 条的校验、第 8.4 节的渲染与降级（docs/agent-plan.md）。
用手写的工具结果（块的结构与 agent/tools 一致），不读库、不需要 ML 包，.venv 里也跑。"""
from datetime import datetime, timezone

import pytest

from agent import facts
from agent.facts import numbers, units
from agent.facts.verify import check_fact

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
SNAP, ARCH, SCORED = "2026-10-26T14:43:07+00:00", "2026-10-25T10:07:12+00:00", "2026-10-27T01:00:00+00:00"


def mblock(mid, kind, at, home, away, **body):
    return {"scope": "match", "match_id": mid, "kind": kind, "at": at, "league": "D1", "league_name": "德甲",
            "home": home, "away": away, "kickoff_utc": "2026-10-26T16:00:00+00:00", **body}


VIEW = {"probabilities": [0.534, 0.25, 0.216], "asian": {"line": -0.75, "p_cover": 0.534},
        "expected_goals": [1.62, 1.05], "likely_scores": [{"score": "1-0", "prob": 0.11}]}
LOG = {
    "c1": {"as_of": NOW.isoformat(), "blocks": [
        mblock("m1", "current", SNAP, "Mainz 05", "Hoffenheim", **VIEW),
        mblock("m1", "first_archive", ARCH, "Mainz 05", "Hoffenheim",
               probabilities=[0.51, 0.26, 0.23], asian={"line": -0.5}),
        mblock("m2", "current", SNAP, "Bayern Munich", "Dortmund", asian={"line": -1.5}),
    ]},
    "c2": {"as_of": NOW.isoformat(), "blocks": [
        mblock("m3", "score", "2026-10-26T18:00:00+00:00", "Augsburg", "Freiburg",
               score={"home": 2, "away": 1}, score_source="fotmob", xg={"home": 1.42, "away": 0.8}),
        mblock("m3", "grading", SCORED, "Augsburg", "Freiburg", model_name="market_implied", model_ver="1.0.0",
               result_src="fotmob", log_loss=0.8123, brier=0.4561),
    ]},
    "c3": {"as_of": NOW.isoformat(), "blocks": [
        {"scope": "scorecard", "model_name": "market_implied", "model_ver": "1.0.0", "kind": "scorecard",
         "at": SNAP, "matches": 51, "diff_vs_base": -0.0018, "se": 0.0041},
        {"scope": "scorecard", "model_name": "dc_market", "model_ver": "1.1.0", "kind": "scorecard",
         "at": SNAP, "matches": 40, "diff_vs_base": 0.012, "se": 0.006},
    ]},
    "c4": {"as_of": NOW.isoformat(), "blocks": [
        {"scope": "kb", "chunk_id": "doc:docs/progress.md:x.0", "kind": "kb", "at": "2026-10-26T15:08:06+00:00",
         "authority": "status", "family": "doc", "path": "docs/progress.md",
         "text": "替换主模型要求场数 ≥ 1000，且差值 + 2×SE < 0。"},
    ]},
}


def fact(fid, path, value, unit, kind="current", at=SNAP, subject="m1", scope="match", call="c1", **kw):
    return {"id": fid, "scope": scope, "subject": subject, "tool_call_id": call, "path": path, "value": value,
            "unit": unit, "kind": kind, "at": at, **kw}


F_LINE = fact("f1", "/blocks/0/asian/line", -0.75, "line")
F_PROB = fact("f2", "/blocks/0/asian/p_cover", 0.534, "prob")
F_ARCH = fact("f3", "/blocks/1/asian/line", -0.5, "line", "first_archive", ARCH)
F_N = fact("f4", "/blocks/0/matches", 51, "count", "scorecard", SNAP, "market_implied@1.0.0", "scorecard", "c3")
F_KB = fact("f5", "/blocks/0/text", 1000, "kb_number", "kb", "2026-10-26T15:08:06+00:00",
            "doc:docs/progress.md:x.0", "kb", "c4", quote="场数 ≥ 1000")
GOOD = {"text": "Mainz 05 对 Hoffenheim 的市场线是 {f1}，主队赢盘概率 {f2}；首次存档时是 {f3}。"
                "主模型已评分 {f4} 场，替换门槛是 {f5} 场。",
        "facts": [F_LINE, F_PROB, F_ARCH, F_N, F_KB]}


def rules(answer) -> set[int]:
    return {i.rule for i in facts.verify(answer, LOG)}


def test_good_answer_passes_and_renders_tool_values():
    assert facts.verify(GOOD, LOG) == []
    # 按工具结果的小数位比：少写一位（0.53）就不通过；渲染用工具结果里的值
    assert 4 in rules({"text": "赢盘 {f2}", "facts": [{**F_PROB, "value": 0.53}]})
    out = facts.render(GOOD, LOG, NOW)
    # 同一句里连着两个本轮看法的数，来源只标在后一个
    assert "主-0.75，主队赢盘概率 53%（本轮看法，10-26 22:43）" in out
    assert "主-0.50（首次存档，10-25 18:07）" in out and "51（实盘成绩单，10-26 22:43）" in out
    assert "1000（项目文档 docs/progress.md，2026-10-26）" in out and out.endswith("（时间均为北京时间）")


@pytest.mark.parametrize("name, answer, rule", [
    ("编造数字", {"text": "一共 3 场，市场线 {f1}", "facts": [F_LINE]}, 1),
    ("错比赛", {"text": "市场线 {f1}", "facts": [{**F_LINE, "subject": "m2"}]}, 5),
    ("错模型", {"text": "已评分 {f4} 场", "facts": [{**F_N, "subject": "dc_market@1.1.0"}]}, 5),
    ("错时点", {"text": "市场线 {f1}", "facts": [{**F_LINE, "at": ARCH}]}, 5),
    ("存档当当前", {"text": "现在的线 {f3}", "facts": [{**F_ARCH, "kind": "current", "at": SNAP}]}, 5),
    ("错单位 xg 报成 goals", {"text": "主队 {f1}", "facts": [
        fact("f1", "/blocks/0/xg/home", 1.42, "goals", "score", "2026-10-26T18:00:00+00:00", "m3", call="c2")]}, 6),
    ("λ 报成 xg", {"text": "主队 {f1}", "facts": [fact("f1", "/blocks/0/expected_goals/0", 1.62, "xg")]}, 6),
    ("错单位 prob 报成 line", {"text": "{f2}", "facts": [{**F_PROB, "unit": "line"}]}, 6),
    ("对照表外的字段", {"text": "{f1}", "facts": [fact("f1", "/blocks/0/league", "D1", "count")]}, 6),
    ("值不对", {"text": "市场线 {f1}", "facts": [{**F_LINE, "value": -1.0}]}, 4),
    ("取不到值", {"text": "{f1}", "facts": [fact("f1", "/blocks/0/asian/safe_line", -1.0, "line")]}, 4),
    ("不存在的调用", {"text": "{f1}", "facts": [{**F_LINE, "tool_call_id": "c9"}]}, 3),
    ("路径不在块里", {"text": "{f1}", "facts": [{**F_LINE, "path": "/as_of"}]}, 5),
    ("块序号越界", {"text": "{f1}", "facts": [{**F_LINE, "path": "/blocks/9/asian/line"}]}, 5),
    ("kb 引文不在原文里", {"text": "{f5}", "facts": [{**F_KB, "quote": "场数 ≥ 1200"}]}, 7),
    ("kb 数不在引文里", {"text": "{f5}", "facts": [{**F_KB, "value": 500}]}, 7),
    ("kb 没有引文", {"text": "{f5}", "facts": [{k: v for k, v in F_KB.items() if k != "quote"}]}, 7),
    ("队名与比赛不符", {"text": "Bayern Munich 的市场线 {f1}", "facts": [F_LINE]}, 8),
    ("没有比赛事实却写队名", {"text": "Dortmund 状态不错", "facts": []}, 8),
    ("占位没有事实", {"text": "{f1} {f2}", "facts": [F_LINE]}, 2),
    ("事实没被引用", {"text": "{f1}", "facts": [F_LINE, F_PROB]}, 2),
    ("id 重复", {"text": "{f1}", "facts": [F_LINE, F_LINE]}, 2),
    ("缺字段", {"text": "{f1}", "facts": [{k: v for k, v in F_LINE.items() if k != "path"}]}, 2),
    ("坏占位", {"text": "{f1}，{fu}", "facts": [F_LINE]}, 2),
    ("全角占位", {"text": "｛f1｝", "facts": []}, 2),
    ("占位后写 %", {"text": "{f2}%", "facts": [F_PROB]}, 2),
    ("不是对象", {"text": "x", "facts": ["f1"]}, 2),
    ("没有 text", {"facts": []}, 2),
])
def test_rejections(name, answer, rule):
    assert rule in rules(answer), name


@pytest.mark.parametrize("text", [
    "５场", "三场", "两成", "百分之五十三", "二比一", "半球", "一球半", "平半", "平手", "第十三", "排名第三", "前四",
    "三连胜", "十几场", "fifty-three percent", "thirty", "Thirty-Third", "twice", "½", "①", "Ⅱ", "IV",
    "主让0.75", "first_archive 的线", "零", "壹", "廿", "a dozen", "the second match", "半个", "半数",
])
def test_number_spellings_rejected(text):
    assert numbers.find_numbers(text), text


@pytest.mark.parametrize("text", [
    "一定", "统一口径", "唯一", "上半场", "下半场", "半场", "I think", "一般来说", "一起看", "一直", "一致", "一些",
    "一下", "万一", "之一", "一样", "一旦", "一切", "进一步", "一律", "同一", "一贯", "不一", "没有数", "MCP 服务", "xG",
    # P3 真实评测里被误拦的
    "北京时间", "作为参照", "对照参考", "另一条线", "下一场", "上一场", "等下一轮快照", "上一轮", "开球前最后一轮看法",
    "最后一场", "最近一场是主场", "下一步", "下一阶段", "两者场数", "两队",
])
def test_allow_list(text):
    assert numbers.find_numbers(text) == [], text


@pytest.mark.parametrize("text,hit", [
    ("略高于一半", "一半"), ("两档", "两"), ("两倍标准误", "两"), ("五五开", "五五"), ("最近一周", "一"),
    ("下一场让半球", "半球"), ("北京 3 点", "3"),
])
def test_allow_list_does_not_hide_quantities(text, hit):
    """放行词旁边的真数量照拦。"""
    assert hit in numbers.find_numbers(text), text


def test_bad_path_hint():
    """path 写成 blocks[0].x 或序号越界：提示 JSON Pointer 写法和可用序号。"""
    msg = check_fact(dict(F_LINE, path="blocks[0].asian.line"), LOG)[0].message
    assert "/blocks/0/asian/line" in msg and "blocks[0].x" in msg and "0–" in msg
    assert check_fact(dict(F_LINE, path="/blocks/36/asian/line"), LOG)[0].rule == 5


def test_entity_names_from_tool_results():
    """工具结果里的 Mainz 05 放行；本轮工具结果里没有这场时，同样的写法不放行；改写数字也不放行。"""
    assert numbers.find_numbers("Mainz 05 主场", {"Mainz 05"}) == []
    assert numbers.find_numbers("Mainz 05 主场", set()) == ["05"]
    assert numbers.find_numbers("Mainz 050", {"Mainz 05"}) == ["050"]
    assert rules({"text": "Mainz 05 的线 {f1}", "facts": [F_LINE]}) == set()
    assert 1 in {i.rule for i in facts.verify({"text": "Mainz 05 不错", "facts": []}, {})}


def test_team_names_longest_first():
    assert facts.verify({"text": "Sp Lisbon", "facts": []}, {}) == []      # 工具里没出现的名字不认
    assert facts.verify.__module__ == "agent.facts.verify"
    from agent.facts.verify import teams_in
    assert teams_in("Sp Lisbon 主场", {"Sp Lisbon", "Lisbon"}) == {"Sp Lisbon"}
    assert teams_in("Paris FC", {"Paris SG"}) == set()


def test_unit_compare():
    assert units.same("prob", 0.534, 0.534) and units.same("odds", 1.9, 1.90)
    assert not units.same("prob", 0.534, 0.53) and not units.same("prob", 0.534, 0.5341)
    assert units.same("line", -0.75, -0.75) and not units.same("line", -0.75, -0.8)
    assert units.same("count", 51, 51.0) and not units.same("count", 51, True)
    assert units.same("score", {"home": 2, "away": 1}, "2-1") and not units.same("score", "2-1", "1-2")
    assert units.same("datetime", "2026-10-26T14:43:07+00:00", "2026-10-26T22:43:07+08:00")
    assert not units.same("datetime", "2026-10-26T14:43:07+00:00", "2026-10-26")
    assert units.kb_literal("差值 + 2×SE < 0，场数 ≥ 1000", 1000) == "1000"
    assert units.kb_literal("主-0.75 赢盘54%", 0.54) == "54%" and units.kb_literal("主-0.75", 0.75) == "-0.75"


def test_labels():
    blocks = LOG["c2"]["blocks"]
    assert facts.label(blocks[0], NOW) == "比分，FotMob，待 football-data 核对"
    assert facts.label({**blocks[0], "score_source": "football-data"}, NOW) == "比分，football-data"
    assert facts.label(blocks[1], NOW) == "赛后评分，FotMob，待 football-data 核对，10-27 09:00"
    lpk = {**LOG["c1"]["blocks"][0], "kind": "last_pre_kickoff"}
    assert facts.label(lpk, NOW) == "开球前最后一轮看法，10-26 22:43"
    live = mblock("m1", "live_calc", NOW.isoformat(), "A", "B", odds_fetched_at="2026-10-26T14:00:00+00:00")
    assert facts.label(live, NOW) == "按最新赔率现算，赔率 10-26 22:00 获取"
    rec = {**LOG["c4"]["blocks"][0], "authority": "record", "path": "docs/handoff/x.md"}
    assert facts.label(rec, NOW) == "交接记录 docs/handoff/x.md，未必是当前状态"
    res = {**LOG["c4"]["blocks"][0], "authority": "research", "path": "_diag/x.log"}
    assert facts.label(res, NOW) == "研究结论 _diag/x.log"
    old = {**LOG["c1"]["blocks"][0], "at": "2025-05-01T10:00:00+00:00"}
    assert facts.label(old, NOW) == "本轮看法，2025-05-01 18:00"
    closing = {**LOG["c3"]["blocks"][0], "kind": "closing"}
    assert facts.label(closing, NOW) == "对收盘参照，10-26 22:43"
    assert units.field("scorecard", "/diff_vs_close") == ("ll_diff", "与收盘赔率的同场差值")
    score = fact("f1", "/blocks/0/score", "2-1", "score", "score", "2026-10-26T18:00:00+00:00", "m3", call="c2")
    out = facts.render({"text": "Augsburg 对 Freiburg {f1}", "facts": [score]}, LOG, NOW)
    assert out.startswith("Augsburg 对 Freiburg 2-1（比分，FotMob，待 football-data 核对）")


def test_render_label_once_per_source_run():
    f_at = fact("f1", "/blocks/0/at", SNAP, "datetime")
    out = facts.render({"text": "看法生成于 {f1}。", "facts": [f_at]}, LOG, NOW)
    assert out.startswith("看法生成于 10-26 22:43（本轮看法）。")             # 不再写两遍同一时间
    # 句末标点隔开时各自标注；来源不同时各自标注
    two = {"text": "市场线 {f1}。赢盘 {f2}，首次存档 {f3}", "facts": [F_LINE, F_PROB, F_ARCH]}
    out = facts.render(two, LOG, NOW)
    assert "主-0.75（本轮看法，10-26 22:43）。" in out and "53%（本轮看法，10-26 22:43）" in out
    assert "主-0.50（首次存档，10-25 18:07）" in out


def test_degrade_has_no_unverified_numbers():
    bad = {"text": "一共 7 场，线 {f1}，概率 {f2}", "facts": [F_LINE, {**F_PROB, "value": 0.9}]}
    assert 1 in rules(bad) and 4 in rules(bad)
    out = facts.degrade(bad, LOG, NOW)
    assert out.startswith(facts.OMITTED) and "主-0.75" in out and "选择方赢盘概率" not in out
    assert "7 场" not in out and "90%" not in out and "一共" not in out
    assert facts.degrade(None, LOG) == facts.FAILED + "查到的场次：\n- Mainz 05 对 Hoffenheim\n" \
                                                     "- Bayern Munich 对 Dortmund\n- Augsburg 对 Freiburg"
    assert facts.degrade({"text": "3 场", "facts": []}, {}) == facts.FAILED


def test_field_table_covers_every_unit_and_real_tool_fields():
    used = {u for rows in facts.FIELDS.values() for _, u, _ in rows}
    assert used <= set(facts.UNITS) and set(facts.UNITS) - used == {"pp"}     # pp 留给以后的分歧字段
    assert facts.field("match", "/self_models/dc_xg/0") == ("prob", "dc_xg主胜概率")
    assert facts.field("match", "/likely_scores/3/score") == ("score", "可能比分")
    assert facts.field("match", "/recommendation_note") is None and facts.field("match", "/hints/0") is None
