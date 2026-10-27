"""agent/facts/  结构化事实：数字识别（numbers）、单位对照与格式化（units）、校验第 1–8 条（verify）、
渲染与降级（render）。规则见 docs/agent-plan.md 第 8.2–8.4 节。"""
from agent.facts.numbers import find_numbers
from agent.facts.render import FAILED, OMITTED, checked_facts, degrade, label, render
from agent.facts.units import FIELDS, UNITS, field
from agent.facts.verify import FACT_KEYS, Issue, verify

__all__ = ["FACT_KEYS", "FAILED", "FIELDS", "Issue", "OMITTED", "UNITS", "checked_facts", "degrade", "field",
           "find_numbers", "label", "render", "verify"]
