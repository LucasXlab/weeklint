# Show HN draft

**Title:** Show HN: Weeklint – check whether your week fits before you say yes

**First comment:**

I'm a student who kept saying yes to things and then discovering, on Thursday night, that the week never had room for them. Weeklint is a local CLI that reads an exported ICS calendar and a Markdown task list, subtracts meetings and buffer from work hours, and tells me whether the week actually fits before I commit.

What it does today:

- `check`: computes work / busy / buffer / free / usable minutes, compares them with task estimates, and names tasks whose deadlines are at risk. It writes nothing.
- `plan`: schedules whole tasks into 30–120 minute blocks, high priority in the morning, with per-day task and deep-work caps. If a task cannot be placed completely, it rolls the whole task back instead of leaving half of it on the calendar.
- `plan` also reuses blocks from the previous `plan.json` when they are still valid, so re-running the scheduler does not shuffle a plan I already confirmed.
- `today` shows today's blocks and the next one.
- `explain` answers "why is this here?" or "why didn't this fit?".
- Outputs: JSON, ICS, Markdown and a standalone HTML report with light/dark and a 375 px layout.

It is deliberately boring: Python 3.11+, four small dependencies, no account, no OAuth, no LLM, no telemetry, and no network calls. Tests monkeypatch `socket.socket` to fail if anything tries to connect.

Limitations I know about:

- It reads an exported `.ics`; it is not a CalDAV client and does not write back.
- ICS `RECURRENCE-ID` overrides are skipped with a warning instead of merged.
- One task file, up to 20 calendars.
- No Windows machine was used during development; CI covers Windows but I cannot claim real-device testing.
- The scheduler is deterministic and rule-based, not an optimizer. If two tasks both need the same morning, it picks by deadline, priority, estimate and id, and says so.

I would especially like feedback on the capacity model: is "work hours minus events minus buffer" the right denominator for a personal week, or do you use a different rule? And does the whole-task rollback match how you actually plan?

Repo: <local only for now; not posted>
