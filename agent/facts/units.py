"""
agent/facts/units.py  字段 → 单位对照表、按单位比对数值、按单位格式化（docs/agent-plan.md 第 8.2、8.4 节）。
FIELDS 按 scope 列出可以引用的字段：块内路径（去掉开头的 /blocks/<i>）用 fnmatch 匹配，[0-9]* 是数组下标。
对照表里没有的字段一律不能引用（第 8.3 节第 6 条），所以嵌在说明文字里的数（recommendation_note、
movement、hints、odds_source）只能换成可引用的字段，不能整句照抄。
"""
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase

BJ = timezone(timedelta(hours=8))
EXACT = {"line", "goals", "count", "score", "datetime"}
UNITS = ("prob", "odds", "line", "goals", "score", "xg", "lambda", "count", "ll", "ll_diff", "se", "brier",
         "pp", "datetime", "kb_number")
_I = "[0-9]*"

# (块内路径模式, 单位, 中文名)。同一路径只匹配第一条
_MATCH = [
    ("/at", "datetime", "数据时间"), ("/generated_at", "datetime", "生成时间"),
    ("/kickoff_utc", "datetime", "开球时间"), ("/scored_at", "datetime", "评分时间"),
    ("/odds_fetched_at", "datetime", "赔率获取时间"), ("/fetched_at", "datetime", "阵容抓取时间"),
    ("/probabilities/0", "prob", "主胜概率"), ("/probabilities/1", "prob", "平局概率"),
    ("/probabilities/2", "prob", "客胜概率"),
    ("/self_models/*/0", "prob", "自研模型主胜概率"), ("/self_models/*/1", "prob", "自研模型平局概率"),
    ("/self_models/*/2", "prob", "自研模型客胜概率"),
    ("/asian/line", "line", "亚盘市场线"), ("/asian/safe_line", "line", "亚盘稳妥线"),
    ("/asian/p_cover", "prob", "选择方赢盘概率"), ("/asian/safe_cover", "prob", "稳妥线赢盘概率"),
    ("/asian/historical_hit", "prob", "该档历史命中率"),
    ("/asian/self_home_cover", "prob", "dc_market 主队赢盘概率"),
    ("/asian/market_home_cover", "prob", "市场主队赢盘概率"),
    ("/asian/outcome/win", "prob", "主队全赢概率"), ("/asian/outcome/half_win", "prob", "主队赢半概率"),
    ("/asian/outcome/push", "prob", "走盘概率"), ("/asian/outcome/half_lose", "prob", "主队输半概率"),
    ("/asian/outcome/lose", "prob", "主队全输概率"),
    ("/historical_first_hit", "prob", "该档首选历史命中率"), ("/historical_double_hit", "prob", "该档双选历史命中率"),
    ("/estimated_first_hit", "prob", "首选估计命中率"), ("/estimated_double_hit", "prob", "双选估计命中率"),
    ("/over25", "prob", "大 2.5 概率"), ("/btts", "prob", "双方进球概率"),
    (f"/likely_scores/{_I}/score", "score", "可能比分"), (f"/likely_scores/{_I}/prob", "prob", "该比分概率"),
    ("/expected_goals/0", "lambda", "主队进球率 λ"), ("/expected_goals/1", "lambda", "客队进球率 λ"),
    ("/odds/avg_h", "odds", "主胜赔率"), ("/odds/avg_d", "odds", "平局赔率"), ("/odds/avg_a", "odds", "客胜赔率"),
    ("/odds/avg_over25", "odds", "大 2.5 赔率"), ("/odds/avg_under25", "odds", "小 2.5 赔率"),
    ("/odds/ah_line", "line", "赔率里的亚盘线"), ("/odds/avg_ahh", "odds", "亚盘主队水位"),
    ("/odds/avg_aha", "odds", "亚盘客队水位"), ("/n_books", "count", "公司家数"),
    ("/score", "score", "比分"), ("/score/home", "goals", "主队进球"), ("/score/away", "goals", "客队进球"),
    ("/xg/home", "xg", "主队预期进球"), ("/xg/away", "xg", "客队预期进球"),
    ("/log_loss", "ll", "胜平负 log loss"), ("/brier", "brier", "Brier"),
    ("/ou25_log_loss", "ll", "大小 2.5 log loss"), ("/score_log_loss", "ll", "比分 log loss"),
    ("/ah_line", "line", "评分用的亚盘线"), ("/ah_log_loss", "ll", "亚盘 log loss"),
]
_SCORECARD = [
    ("/at", "datetime", "成绩单时间"), ("/generated_at", "datetime", "成绩单时间"),
    ("/matches", "count", "已评分场数"), ("/log_loss", "ll", "胜平负 log loss"), ("/brier", "brier", "Brier"),
    ("/hit_rate", "prob", "首选命中率"), ("/ou25_ll", "ll", "大小 2.5 log loss"), ("/score_ll", "ll", "比分 log loss"),
    ("/ah_n", "count", "亚盘已评分场数"), ("/ah_ll", "ll", "亚盘 log loss"), ("/ah_hit", "prob", "亚盘命中率"),
    ("/paired_n", "count", "同场对比场数"), ("/diff_vs_base", "ll_diff", "与市场基准的同场差值"),
    ("/se", "se", "标准误"),
]
FIELDS = {"match": _MATCH, "scorecard": _SCORECARD, "kb": [("/text", "kb_number", "知识库原文")]}


def field(scope: str, sub: str) -> tuple[str, str] | None:
    """块内路径 → (单位, 中文名)；对照表里没有时 None。"""
    for pat, unit, label in FIELDS.get(scope, ()):
        if fnmatchcase(sub, pat):
            if pat.startswith("/self_models/"):
                label = sub.split("/")[2] + label.removeprefix("自研模型")
            return unit, label
    return None


def _decimals(v: float) -> int:
    s = repr(float(v))
    return 0 if "e" in s else len(s.split(".")[1].rstrip("0"))


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def score_pair(v) -> tuple[int, int] | None:
    """比分的几种写法 → (主, 客)：{"home": 2, "away": 1}、"2-1"、[2, 1]。"""
    if isinstance(v, dict) and _num(v.get("home")) and _num(v.get("away")):
        return int(v["home"]), int(v["away"])
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(_num(x) for x in v):
        return int(v[0]), int(v[1])
    if isinstance(v, str) and (m := re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", v)):
        return int(m[1]), int(m[2])
    return None


def parse_dt(v) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def same(unit: str, tool_value, value) -> bool:
    """模型写的 value 与工具结果里的值是否一致（第 8.3 节第 4 条）。line / goals / count 完全相等；
    score 主客两个整数相等；datetime 是同一时刻；其余按工具结果的小数位比：位数不多于工具结果、
    按那个位数取整后相等（0.534 写成 0.53 或 0.5341 都不通过，要原样照抄）。"""
    if unit == "score":
        return score_pair(tool_value) is not None and score_pair(tool_value) == score_pair(value)
    if unit == "datetime":
        a, b = parse_dt(tool_value), parse_dt(value)
        return a is not None and a == b
    if not (_num(tool_value) and _num(value)):
        return False
    if unit in EXACT:
        return float(tool_value) == float(value)
    d = _decimals(tool_value)
    return _decimals(value) <= d and round(float(value), d) == round(float(tool_value), d)


_KB_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?%?")


def kb_literal(quote: str, value) -> str | None:
    """quote 里与 value 相等的那个数的原文写法（第 8.3 节第 7 条）；没有时 None。
    带 % 的按百分数比（53% 等于 53 或 0.53），负号可写可不写（「-0.75」里的 0.75 也算）。"""
    if not _num(value):
        return None
    for m in _KB_NUM.finditer(unicodedata.normalize("NFKC", quote)):
        lit = m.group()
        x = float(lit.rstrip("%"))
        cands = {x, abs(x)} | ({x / 100, abs(x) / 100} if lit.endswith("%") else set())
        if any(abs(c - float(value)) < 1e-9 for c in cands):
            return lit
    return None


def fmt_dt(v, now: datetime | None = None) -> str:
    t = parse_dt(v)
    if t is None:
        return str(v)
    t = t.astimezone(BJ)
    return t.strftime("%m-%d %H:%M") if now is None or t.year == now.astimezone(BJ).year \
        else t.strftime("%Y-%m-%d %H:%M")


def fmt(unit: str, v, now: datetime | None = None) -> str:
    """按单位格式化工具结果里的值（第 8.4 节，与报告的写法一致）：概率是整数百分数，亚盘线带主队方向，
    时间转北京时间。"""
    if unit == "datetime":
        return fmt_dt(v, now)
    if unit == "score":
        p = score_pair(v)
        return f"{p[0]}-{p[1]}" if p else str(v)
    if not _num(v):
        return str(v)
    if unit == "prob":
        return f"{v:.0%}"
    if unit == "line":
        return f"主{v + 0.0:+.2f}"
    if unit in ("goals", "count"):
        return str(int(v))
    if unit in ("odds", "xg", "lambda"):
        return f"{v:.2f}"
    if unit in ("ll_diff", "pp"):
        return f"{v:+.4f}" if unit == "ll_diff" else f"{v:+.1f}pp"
    if unit in ("ll", "se", "brier"):
        return f"{v:.4f}"
    return str(v)
