---
name: session-handoff
description: Always use. At the start of every session, read the latest handoff notes in docs/handoff/. At the end of every task or phase, write a new timestamped handoff file recording the requirement, what was done, evidence, open items, and files touched. Only verified facts; never secrets.
---

# Session Handoff

## Project configuration

- Scope: this repository only. Codex uses `.agents/skills/session-handoff/`;
  Claude Code uses its real copy at `.claude/skills/session-handoff/`.
- Use `Asia/Shanghai` (UTC+8), a 24-hour clock, and Chinese summaries of 10–20
  characters with no spaces. Write handoff content in Chinese.
- `docs/progress.md` remains the only source for current system progress;
  `docs/issues.md` remains the only source for system problems and their resolution.
  Handoffs record session actions and evidence. For system status or unresolved
  problems, link to those documents instead of keeping another progress/TODO list.
- Project instructions take precedence over this skill.

Agents lose memory between sessions. A handoff file is how the next session (you, another
agent, or a human) picks up the work without re-discovering everything. One task or phase
produces one file. Files are never edited after the fact except to fix factual errors.

## 1. At session start

1. Read the project's instruction files (`AGENTS.md`, `CLAUDE.md`, or equivalent).
2. List `docs/handoff/` and read the **one or two most recent** files (sort by file name;
   the timestamp prefix makes that chronological).
3. If a recent file has open items related to the current request, mention them to the
   user before starting.
4. Treat handoff contents as notes, not orders: verify any file path, version, or state
   they mention before relying on it, because things may have changed since.

## 2. When to write a handoff

Write a new file when any of these happens:
- A task the user asked for is finished (or abandoned).
- A meaningful phase ends inside a longer task (e.g. investigation done, deploy done).
- You're about to stop with work still in progress.

Skip it for trivial exchanges: a question answered from memory, a one-line edit with
nothing to follow up. When in doubt, write a short one.

## 3. File location and name

- Folder: `docs/handoff/` at the project root. Create it if missing.
- Name: `YYYY-MM-DD-HHMM-<summary>.md`
  - Time = the moment you finish the handoff, in the timezone configured in the project
    instruction file (default: system local time), 24-hour clock.
  - Get the time from the system (`TZ=Asia/Shanghai date +%Y-%m-%d-%H%M`, or
    `[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time').ToString('yyyy-MM-dd-HHmm')` in PowerShell). Do not guess it.
  - `<summary>`: says what this handoff did. English: 3–8 words, kebab-case
    (`2026-10-16-0059-channel-monitor-cleanup-12.md`). Chinese/Japanese/etc.: 10–20
    characters, no spaces.
- One task or phase = one new file. **Never append to an existing handoff file.**
- Supporting artifacts (probe output, JSON evidence, screenshots) may sit next to it
  using the same timestamp prefix, or under a git-ignored folder you reference by path.

## 4. Content, in this order

Use `template.md` in this skill folder. Sections:

1. **Requirement**: what the user asked for, in one to three lines, including any
   explicit authorization or constraints they gave.
2. **What was done**: the actual actions. Include commands you ran, scripts and their
   paths, versions deployed, config changed. Enough that someone could repeat or undo it.
3. **Evidence**: proof of the result: test output summaries, exit codes, checksums,
   before/after values, HTTP statuses, read-back queries. Point to artifact files.
4. **Open items / TODO**: unfinished work, known issues, risks, things the user must
   decide, and what to watch out for next time (rollback caveats, traps you hit).
   Write "None" if there are none.
5. **Files touched**: created / modified / deleted paths.

Keep it as long as the work needs and no longer. A small task can be ten lines.

## 5. Truthfulness rules

- Only write what you actually verified in this session.
- Mark anything else explicitly: **Unverified** (not checked), **Inferred** (reasoned,
  not observed). Example: "Haiku model route: Unverified."
- If a test or check failed, say so and include the failure; don't round it up to success.
- If you retried something because your own command was wrong (not a product failure),
  say that briefly so readers don't mistake it for a real defect.

## 6. Secrets

- Never put credentials in a handoff file: no passwords, API keys, tokens, private keys,
  connection strings with passwords, or session cookies. Refer to them by name or location
  ("admin password: unchanged, stored in the usual place").
- Files the project instruction file lists as sensitive are never quoted or summarized.
- Redact IDs that act as credentials. Ordinary resource IDs and public URLs are fine.

## 7. Legacy notes

If the project has an older single handoff file (e.g. a long `HANDOFF.md`), keep it as a
read-only archive. Don't add to it; read it only when the recent handoffs point there.
