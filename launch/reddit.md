# Reddit draft (r/productivity)

**Title:** I built a local CLI that tells me whether my week actually fits before I say yes

**Body:**

I'm a student. My calendar was full of classes and meetings, my task list was full of 2–4 hour tasks, and I kept pretending those were compatible. The specific failure was saying yes to a lab meeting on Tuesday and then discovering it pushed a Thursday paper past its deadline.

Weeklint is the tool I wanted: it reads an exported `.ics` and a Markdown task file, subtracts meetings plus a buffer from my configured work hours, and compares the result with task estimates.

- `check` tells me the gap and which deadlines are at risk. It writes nothing.
- `plan` schedules only whole tasks, 30–120 minute blocks, high priority in the morning. If a task doesn't fully fit, it goes to an "unscheduled" list instead of becoming a half-done calendar block.
- It can lock the blocks from the previous plan, so a re-run doesn't move a plan I already accepted.
- `today` shows only today. `explain` tells me why a task landed where it did.
- The report is one HTML file, light/dark, works at 375 px.

No cloud, no account, no AI, no network. It runs locally and reads/writes files.

What I'm unsure about:

1. The capacity denominator. I use configured work hours minus calendar events minus buffer. Some people plan by "deep work hours" instead. Which is more honest for you?
2. Whole-task rollback. It is predictable, but it can leave a large free gap. Do you prefer splitting a task across days even if the last piece doesn't fit?
3. Morning preference for high priority. Is that helpful, or does it fight your actual energy pattern?

I'm not selling anything and there is no signup. Happy to answer how the scheduling works or share the JSON output.

Repo: <local only for now; not posted>
