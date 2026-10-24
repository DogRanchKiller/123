# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

仓库规则、命令、架构和训练规范的检索都在 [AGENTS.md](AGENTS.md)（Codex 与 Claude Code 共用，规则只写在那里）。先读它，再按其中的指针打开 `docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`、`docs/progress.md`、`docs/issues.md` 或 `.agents/skills/`。

@AGENTS.md

## Claude Code 补充

- 本机是 Windows：`.claude/skills/` 的符号链接会检出成普通文本，技能不会自动加载。需要技能时按 AGENTS.md「检索」的表直接读 `.agents/skills/*/SKILL.md`。
- bash heredoc 里写中文在本机会出错；改含中文的文件用编辑工具。
