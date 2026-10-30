# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-30

First usable release. Local-only, no network, no account, no LLM.

### Added

- `weeklint init` creates `weeklint.yaml`, `tasks.md` and an empty `calendar.ics`
  without overwriting existing files.
- `weeklint check` parses one Markdown task file and up to 20 ICS calendars,
  then reports work minutes, busy minutes, buffer, free minutes, usable minutes,
  demand, gap and findings.
- `weeklint plan` produces a deterministic week schedule with 30–120 minute
  blocks, high-priority morning preference, per-day task and deep-work caps,
  and whole-task rollback when a task cannot be placed completely.
- Locked blocks from the previous `plan.json` are reused when they are still
  inside work hours, outside calendar events (including buffer), and within the
  task estimate.
- `weeklint today` shows today's blocks and the next block from the current
  plan, generating it in memory when no current plan exists.
- `weeklint explain` resolves a task by exact id or title substring and shows
  every block, its reason, or the unscheduled reason.
- `weeklint doctor` reports task/calendar counts, file sizes and this week's
  usable minutes without writing files.
- Outputs: `plan.json`, `plan.ics` (valid VCALENDAR with UTC times), `plan.md`
  and a standalone `report.html` with light/dark CSS tokens, 375 px layout and
  print styles.
- Stable error envelope `{error, code, detail}` in `--json` mode, with exit codes 0/1/2/3. Long user values are truncated in messages.
- `--now`, `--week`, `--config`, `--json`, `--no-color` and the matching
  `WEEKLINT_*` environment variables.
- Tests cover config validation, task metadata, ICS recurrence and DST, budget
  arithmetic, planner locking/rollback, report escaping and CLI error paths.
- Verification pass fixed long-running RRULEs that were truncated before the
  requested week, sub-min-block fragment placement, DST capacity arithmetic,
  unclosed metadata silently becoming title text, Rich/ANSI output injection,
  oversized error values, deep YAML recursion, input/output path collisions,
  and stale-lock ownership.

### Security / privacy

- No outbound network calls; tests monkeypatch `socket.socket` to fail if one is
  attempted.
- Reads only the configured task/calendar files, writes only to `output_dir`.
- HTML report escapes every user string; ICS uses the library's RFC 5545
  escaping.
- No secrets are read or printed. There is no API key to configure.

### Known limitations

- ICS `RECURRENCE-ID` overrides are skipped with a warning instead of merged.
- RRULE expansion is capped at 1000 instances per event within the week.
- Only one task file and at most 20 calendars per run.
- `plan` covers the whole current ISO week; running it midweek can include
  already-passed slots. Use it at the start of the week; on Sunday pass
  `--week` for the next week. `today` marks past/running blocks.
- Not tested against every calendar vendor export.
