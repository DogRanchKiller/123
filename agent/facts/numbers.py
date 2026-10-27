"""
agent/facts/numbers.py  第 8.3 节第 1 条：text 里（去掉占位后）不允许出现数字。
判定是「默认拦、放行表放」：先 NFKC 归一（全角 ５ → 5、① → 1、½ → 1⁄2、Ⅱ → II），把工具结果里原样出现的
实体名（队名、联赛名、模型名、球员名，如 Mainz 05）遮掉，再按下面的顺序找：
- 中文盘口名（平手、平半、球半…）：项目规定亚盘只用数字线，这些词也要走事实；
- 放行表里的固定词（一定、统一、上半场…）遮掉；
- 剩下的任何带数值的字符（unicodedata.numeric 有值：阿拉伯数字、中文数字与大写数字、两、〇、廿…）和「半」；
- 英文数词（基数、整十、序数、分数和倍数，按 ASCII 字母边界、不区分大小写；连字符组合靠各段命中）；
- ASCII 罗马数字：两个及以上 [IVXLC] 的整词（单个 I / V / X 不拦）。
放行表外的一律不通过，宁可多打回一次；放行表增补的每个词都要有测试（tests/test_agent_facts.py）。
"""
import re
import unicodedata

MASK = "◇"        # 遮挡用的字符：不是字母、数字，不会和前后拼成英文词

# 放行表：含数字字符或「半」、但不表示数量的固定词。只能整词增补，并补测试
ALLOW = ("一定", "一般", "一起", "一直", "一致", "一些", "一下", "统一", "唯一", "万一", "之一", "一样",
         "上半场", "下半场", "半场", "一旦", "一切", "进一步", "一律", "同一", "一贯", "不一",
         # P3 真实评测里被误拦的：京、参是数值字符（unicodedata），其余指「那一场 / 那一轮」而不是数量
         "北京", "参照", "参考", "另一", "下一场", "上一场", "下一轮", "上一轮", "最后一轮", "最后一场",
         "最近一场", "下一步", "下一阶段", "两者", "两队")
# 中文盘口名：不含数字字符的（平手）也要拦
HANDICAP_WORDS = tuple(sorted(("平手", "平半", "半一", "一球", "球半", "半球", "一球半", "两球", "两球半"),
                              key=len, reverse=True))

_EN_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand "
    "million billion dozen first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth "
    "fortieth fiftieth sixtieth seventieth eightieth ninetieth hundredth thousandth half halves quarter "
    "quarters thirds once twice double triple").split()
EN_NUM = re.compile(r"(?<![A-Za-z])(?:" + "|".join(sorted(_EN_WORDS, key=len, reverse=True))
                    + r")s?(?![A-Za-z])", re.IGNORECASE)
ROMAN = re.compile(r"(?<![A-Za-z])[IVXLC]{2,}(?![A-Za-z])")


# unicodedata 不认、但表示数量的字：「两 / 兩」到 Unicode 15.1 才有数值，Python 3.12 的 15.0 里没有
_EXTRA_NUM = frozenset("半两兩")


def _is_num(ch: str) -> bool:
    return ch in _EXTRA_NUM or unicodedata.numeric(ch, None) is not None


def mask_entities(text: str, entities: set[str]) -> str:
    """把工具结果里原样出现的实体名遮掉（长的先遮）。英文名前后不能紧贴字母或数字，
    所以模型把 Mainz 05 写成 Mainz 050 时不会被放过。"""
    for e in sorted((e for e in entities if e), key=len, reverse=True):
        e = unicodedata.normalize("NFKC", e)
        pat = re.escape(e)
        if e[0].isascii() and e[0].isalnum():
            pat = r"(?<![A-Za-z0-9])" + pat
        if e[-1].isascii() and e[-1].isalnum():
            pat += r"(?![A-Za-z0-9])"
        text = re.sub(pat, MASK, text)
    return text


def find_numbers(text: str, entities: set[str] = frozenset()) -> list[str]:
    """返回 text 里所有算作「数字」的写法（按出现顺序，去重）；空列表 = 通过。
    text 里的占位 {fN} 要先由调用方去掉。"""
    s = mask_entities(unicodedata.normalize("NFKC", text), entities)
    hits: list[str] = []
    for w in HANDICAP_WORDS:
        if w in s:
            hits.append(w)
            s = s.replace(w, MASK)
    for w in sorted(ALLOW, key=len, reverse=True):
        s = s.replace(w, MASK)
    run = ""
    for ch in s + MASK:
        if _is_num(ch):
            run += ch
        elif run:
            hits.append(run)
            run = ""
    hits += [m.group() for m in EN_NUM.finditer(s)]
    hits += [m.group() for m in ROMAN.finditer(s)]
    return list(dict.fromkeys(hits))
