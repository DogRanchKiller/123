""".claude/skills/ 必须是 .agents/skills/ 的真实副本（不是符号链接），内容一致。"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".agents" / "skills"
DST = ROOT / ".claude" / "skills"
NAMES = sorted(p.name for p in SRC.iterdir() if (p / "SKILL.md").is_file())


def _files(d: Path) -> dict[str, str]:
    # 行尾按 LF 比较：同一份文件在 Windows（autocrlf）和 Mac 上检出的行尾可能不同
    return {p.relative_to(d).as_posix(): p.read_text(encoding="utf-8").replace("\r\n", "\n")
            for p in sorted(d.rglob("*")) if p.is_file()}


def test_skills_found():
    assert NAMES


@pytest.mark.parametrize("name", NAMES)
def test_claude_skill_is_real_copy(name):
    d = DST / name
    assert not d.is_symlink() and d.is_dir(), \
        f"{d} 不是目录；运行 python .agents/sync_skills.py"
    assert _files(d) == _files(SRC / name), \
        f"{d} 与 .agents/skills/{name} 不一致；运行 python .agents/sync_skills.py"
