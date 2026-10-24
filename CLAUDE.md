# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

仓库规则、命令、架构和训练规范的检索都在 [AGENTS.md](AGENTS.md)（Codex 与 Claude Code 共用，规则只写在那里）。先读它，再按其中的指针打开 `docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`、`docs/progress.md`、`docs/issues.md` 或 `.agents/skills/`。

@AGENTS.md

## Claude Code 补充

- 技能在 `.claude/skills/`（`.agents/skills/` 的副本），Mac 和 Windows 都会自动加载。改技能只改 `.agents/skills/`，再运行 `python .agents/sync_skills.py`。
- Windows 上 bash heredoc 里写中文在本机会出错；改含中文的文件用编辑工具。
