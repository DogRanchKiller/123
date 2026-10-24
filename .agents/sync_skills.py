"""
把 .agents/skills/ 同步到 .claude/skills/（真实文件，不用符号链接）。
Windows 默认 core.symlinks=false，符号链接会检出成普通文本，Claude Code 读不到技能；
复制一份后 Mac / Windows 都能直接用。技能只在 .agents/skills/ 里改，改完运行：
    python .agents/sync_skills.py
tests/test_skills_sync.py 检查两边一致。
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".agents" / "skills"
DST = ROOT / ".claude" / "skills"


def sync() -> list[str]:
    """逐个技能整目录覆盖复制，返回同步的技能名。只动 SRC 里有的名字。"""
    DST.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in SRC.iterdir() if (p / "SKILL.md").is_file())
    for name in names:
        target = DST / name
        if target.is_symlink() or target.is_file():
            target.unlink()          # 旧的符号链接，或 Windows 上检出成的文本文件
        elif target.is_dir():
            shutil.rmtree(target)
        shutil.copytree(SRC / name, target)
    return names


if __name__ == "__main__":
    names = sync()
    print(f"已同步 {len(names)} 个技能到 {DST.relative_to(ROOT)}：{'、'.join(names)}")
    extra = sorted(p.name for p in DST.iterdir() if p.name not in names)
    if extra:
        print(f"注意：{DST.relative_to(ROOT)} 里有 .agents/skills/ 没有的条目（未删除）：{'、'.join(extra)}")
