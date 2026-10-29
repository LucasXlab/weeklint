"""Plan artifacts: JSON, Markdown, ICS and a standalone HTML report.

Every user-controlled string is escaped before it reaches HTML. The report uses
only the CSS custom properties documented in DESIGN.md, has no scripts, no
external assets and no network URLs.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import tempfile
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .budget import day_capacity_dicts
from .errors import WeeklintError
from .ics import blocks_to_ics
from .model import Block, PlanData, iso
from .errors import WeeklintError


def fmt_minutes(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{sign}{h}h{m:02d}m"
    if h:
        return f"{sign}{h}h"
    return f"{sign}{m}m"


def _block_markdown(block: Block) -> str:
    lock = "（已锁定）" if block.locked else ""
    return f"- {block.start.strftime('%m-%d %H:%M')}–{block.end.strftime('%H:%M')} · {block.title}{lock}"


def render_plan_markdown(plan: PlanData, config) -> str:
    check = plan.check
    lines = [
        f"# {config.planning.report_title}",
        "",
        f"- 周：{check.week.iso}（{check.week.start.isoformat()} 至 {(check.week.end - timedelta(days=1)).isoformat()}）",
        f"- 可支配：{fmt_minutes(check.capacity['usableMinutes'])}",
        f"- 任务需要：{fmt_minutes(check.demand['estimatedMinutes'])}",
        f"- 缺口：{fmt_minutes(check.gap_minutes)}",
        f"- 已排：{fmt_minutes(plan.summary['scheduledMinutes'])}",
        "",
        "## 周一至周日",
        "",
    ]
    by_day: dict[str, list[Block]] = {}
    for block in plan.blocks_sorted():
        by_day.setdefault(block.start.date().isoformat(), []).append(block)
    for offset in range(7):
        day = check.week.start + timedelta(days=offset)
        lines.append(f"### {day.isoformat()}")
        lines.append("")
        day_blocks = by_day.get(day.isoformat(), [])
        if not day_blocks:
            lines.append("无安排。")
        else:
            lines.extend(_block_markdown(b) for b in day_blocks)
        lines.append("")
    lines += ["## 未排程", ""]
    if not plan.unscheduled:
        lines.append("无。" if check.tasks else "无任务。请在 tasks.md 里添加任务。")
    else:
        for task, remaining, reason in plan.unscheduled:
            lines.append(f"- {task.title} · 还剩 {fmt_minutes(remaining)} · {reason}")
    lines += ["", "## 发现", ""]
    if not plan.findings:
        lines.append("没有问题。")
    else:
        for finding in plan.findings:
            lines.append(f"- [{finding.severity}] {finding.message}")
    lines.append("")
    return "\n".join(lines)


def _plan_json(plan: PlanData, include_report: bool) -> dict:
    check = plan.check
    files = dict(plan.files)
    if not include_report:
        files["reportHtml"] = None
    return {
        "version": __version__,
        "week": check.week.to_dict(),
        "days": day_capacity_dicts(check),
        "generatedAt": iso(check.generated_at),
        "now": iso(check.now),
        "blocks": [b.to_dict() for b in plan.blocks_sorted()],
        "unscheduled": [
            {"taskId": task.id, "title": task.title, "remainingMinutes": remaining, "reason": reason}
            for task, remaining, reason in plan.unscheduled
        ],
        "summary": dict(plan.summary),
        "findings": [f.to_dict() for f in plan.findings],
        "files": files,
    }


def acquire_lock(output_dir: Path) -> tuple[Path, bool]:
    """Create output_dir/.lock with O_EXCL; return (path, removed_stale)."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WeeklintError("output_dir_not_writable", f"无法创建输出目录：{output_dir}（{exc.strerror}）。", {"path": str(output_dir)}) from None
    lock = output_dir / ".lock"
    for attempt in range(2):
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, f"pid={os.getpid()} started={_time.time():.0f}\n".encode("utf-8"))
            os.close(fd)
            return lock, attempt == 1
        except FileExistsError:
            try:
                age = _time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age > 600 and attempt == 0:
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            raise WeeklintError("plan_locked", f"另一个 plan 正在写这个输出目录：{lock}。如果确认没有在运行，删除这个锁文件再试。", {"path": str(lock)}) from None
        except OSError as exc:
            raise WeeklintError("output_dir_not_writable", f"无法创建锁文件：{lock}（{exc.strerror}）。", {"path": str(lock)}) from None
    raise WeeklintError("plan_locked", f"无法获得输出目录锁：{lock}。", {"path": str(lock)})


def release_lock(lock: Path) -> None:
    try:
        lock.unlink()
    except OSError:
        pass


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as exc:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise WeeklintError(
            "write_failed",
            f"写文件失败：{path}（{exc.strerror or exc}）。已写成的文件会保留。",
            {"path": str(path)},
        ) from None


def write_plan_files(plan: PlanData, config, include_report: bool = True) -> dict[str, str | None]:
    output = config.planning.output_dir
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WeeklintError(
            "output_dir_not_writable",
            f"无法创建输出目录：{output}（{exc.strerror}）。",
            {"path": str(output)},
        ) from None
    if not os.access(output, os.W_OK):
        raise WeeklintError("output_dir_not_writable", f"输出目录不可写：{output}。", {"path": str(output)})
    plan_json = output / "plan.json"
    if plan_json.exists():
        prev = output / "plan.prev.json"
        try:
            shutil.copy2(plan_json, prev)
        except OSError as exc:
            raise WeeklintError(
                "write_failed",
                f"备份上一次的 plan.json 失败：{exc.strerror or exc}。",
                {"path": str(prev)},
            ) from None
    payload = _plan_json(plan, include_report)
    _atomic_write(plan_json, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    _atomic_write(output / "plan.ics", blocks_to_ics(plan.blocks, config.tz, plan.check.generated_at, __version__).encode("utf-8"))
    _atomic_write(output / "plan.md", render_plan_markdown(plan, config).encode("utf-8"))
    if include_report:
        _atomic_write(output / "report.html", render_report_html(plan, config).encode("utf-8"))
    return payload["files"]


def _status_text(plan: PlanData) -> str:
    if plan.summary["tasksUnscheduled"]:
        return "有任务未排完，见下方。"
    if any(f.severity == "error" for f in plan.findings):
        return "有截止风险，见下方。"
    return "这周装得下。"


def _finding_class(severity: str) -> str:
    return {"error": "finding-error", "warning": "finding-warning", "info": "finding-info"}.get(severity, "finding-info")


def render_report_html(plan: PlanData, config) -> str:
    check = plan.check
    title = html.escape(config.planning.report_title)
    days = day_capacity_dicts(check)
    by_day: dict[str, list[Block]] = {}
    for block in plan.blocks_sorted():
        by_day.setdefault(block.start.date().isoformat(), []).append(block)
    capacity = check.capacity["usableMinutes"]
    demand = check.demand["estimatedMinutes"]
    ratio = (min(100.0, (plan.summary["scheduledMinutes"] / capacity) * 100) if capacity else 0.0)
    errors = [f for f in plan.findings if f.severity == "error"]
    warnings = [f for f in plan.findings if f.severity == "warning"]
    infos = [f for f in plan.findings if f.severity == "info"]
    if errors or warnings:
        finding_title = "需要处理"
    elif infos:
        finding_title = f"提醒（{len(infos)}）"
    else:
        finding_title = "没有问题"

    def finding_items(items) -> str:
        if not items:
            return ""
        return "".join(
            f'<li class="{_finding_class(f.severity)}"><span class="finding-code">{html.escape(f.code)}</span>{html.escape(f.message)}</li>'
            for f in items
        )

    day_html = []
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for index, day in enumerate(days):
        day_blocks = by_day.get(day["date"], [])
        work = int(day["workMinutes"])
        if work == 0:
            empty = "不排周末" if index >= 5 and not config.planning.include_weekends else "无工作时间"
        elif not day_blocks:
            empty = "无安排。"
        else:
            empty = ""
        blocks_html = "".join(
            f'<div class="block{" block-locked" if b.locked else ""}"><span class="block-time">{html.escape(b.start.strftime("%H:%M"))}–{html.escape(b.end.strftime("%H:%M"))}</span><span class="block-title">{html.escape(b.title)}</span>{"<span class=\"badge\">已锁定</span>" if b.locked else ""}</div>'
            for b in day_blocks
        )
        day_html.append(
            f'<div class="day"><div class="day-head"><span class="day-name">{weekdays[index]}</span><span class="day-date">{html.escape(day["date"][5:])}</span></div>'
            f'<div class="day-cap">可用 {fmt_minutes(int(day["usableMinutes"]))}</div>'
            f'{blocks_html or f"<div class=\"empty\">{empty}</div>"}</div>'
        )
    unscheduled_html = ""
    if plan.unscheduled:
        rows = "".join(
            f"<tr><td>{html.escape(task.title)}</td><td>{fmt_minutes(remaining)}</td><td>{html.escape(reason)}</td></tr>"
            for task, remaining, reason in plan.unscheduled
        )
        unscheduled_html = f'<table><thead><tr><th>任务</th><th>剩余</th><th>原因</th></tr></thead><tbody>{rows}</tbody></table>'
    elif check.tasks:
        unscheduled_html = '<p class="empty-line">无。所有任务都排进了本周。</p>'
    else:
        unscheduled_html = '<p class="empty-line">无任务。请在 tasks.md 里添加任务。</p>'
    findings_html = (
        f'<ul class="findings">{finding_items(errors + warnings + infos)}</ul>'
        if (errors or warnings or infos)
        else '<p class="empty-line">没有问题。</p>'
    )
    css = """
:root {
  --bg: #fbfbfa;
  --surface: #ffffff;
  --surface-subtle: #f2f3ee;
  --border: #e4e5df;
  --border-strong: #c9cbc2;
  --text: #1c1c1a;
  --text-muted: #5f5f5a;
  --accent: #2f6f4e;
  --accent-weak: #e7f0ea;
  --danger: #a33a2b;
  --danger-weak: #f7e8e5;
  --warning: #8a5a12;
  --warning-weak: #f8f0df;
  --ok: #2f6f4e;
  --ok-weak: #e7f0ea;
  --text-xs: 12px;
  --text-sm: 13px;
  --text-base: 16px;
  --text-md: 18px;
  --text-lg: 24px;
  --text-metric: 32px;
  --text-metric-sm: 28px;
  --text-print: 11pt;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111311;
    --surface: #191b18;
    --surface-subtle: #21241f;
    --border: #33372f;
    --border-strong: #4a4f44;
    --text: #eceee9;
    --text-muted: #a7aba3;
    --accent: #9cc3a8;
    --accent-weak: #22352a;
    --danger: #e28f80;
    --danger-weak: #3a211d;
    --warning: #d9b36a;
    --warning-weak: #3a2f1b;
    --ok: #9cc3a8;
    --ok-weak: #22352a;
  }
}
* { box-sizing: border-box; }
html { color-scheme: light dark; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--font); font-size: var(--text-base); line-height: 1.5; }
.page { max-width: 1120px; margin: 0 auto; padding: var(--space-5) var(--space-4); }
header { display: flex; justify-content: space-between; gap: var(--space-3); align-items: baseline; padding-bottom: var(--space-4); border-bottom: 1px solid var(--border); }
h1 { margin: 0; font-size: var(--text-lg); font-weight: 650; }
h2 { margin: 0 0 var(--space-3); font-size: var(--text-md); font-weight: 600; }
.meta { color: var(--text-muted); font-size: var(--text-sm); }
section { margin-top: var(--space-5); }
.metrics { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.metric { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-3); }
.metric:last-child { grid-column: 1 / -1; }
.metric-label { color: var(--text-muted); font-size: var(--text-xs); }
.metric-value { font-size: var(--text-metric); font-weight: 600; font-variant-numeric: tabular-nums; }
.metric-unit { font-size: var(--text-sm); color: var(--text-muted); margin-left: var(--space-1); }
.bar { height: 8px; background: var(--surface-subtle); border-radius: var(--radius-sm); overflow: hidden; margin-top: var(--space-2); }
.bar > span { display: block; height: 100%; background: var(--accent); }
.bar.over > span { background: var(--danger); }
.bar-caption { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--text-muted); font-size: var(--text-xs); margin-top: var(--space-1); }
.status { margin-top: var(--space-3); color: var(--text-muted); font-size: var(--text-sm); }
.week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: var(--space-2); }
.day { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-2); min-width: 0; }
.day-head { display: flex; justify-content: space-between; gap: var(--space-1); align-items: baseline; }
.day-name { font-weight: 600; font-size: var(--text-sm); }
.day-date { color: var(--text-muted); font-size: var(--text-xs); }
.day-cap { color: var(--text-muted); font-size: var(--text-xs); margin: var(--space-1) 0 var(--space-2); }
.block { background: var(--accent-weak); border-left: 3px solid var(--accent); border-radius: var(--radius-sm); padding: var(--space-2); margin-bottom: var(--space-2); font-size: var(--text-sm); overflow-wrap: anywhere; }
.block-locked { background: var(--surface-subtle); border-left-color: var(--border-strong); }
.block-time { display: block; color: var(--text-muted); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.block-title { display: block; }
.badge { display: inline-block; margin-top: var(--space-1); color: var(--text-muted); font-size: var(--text-xs); }
.empty { color: var(--text-muted); font-size: var(--text-sm); padding: var(--space-2) 0; }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
th, td { text-align: left; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); font-size: var(--text-sm); vertical-align: top; overflow-wrap: anywhere; }
th { color: var(--text-muted); font-weight: 600; background: var(--surface-subtle); }
tr:last-child td { border-bottom: 0; }
.findings { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--space-2); }
.findings li { background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--border-strong); border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3); font-size: var(--text-sm); }
.finding-error { border-left-color: var(--danger) !important; }
.finding-warning { border-left-color: var(--warning) !important; }
.finding-info { border-left-color: var(--accent) !important; }
.finding-code { display: inline-block; color: var(--text-muted); font-size: var(--text-xs); margin-right: var(--space-2); }
.empty-line { color: var(--text-muted); font-size: var(--text-sm); margin: 0; }
footer { margin-top: var(--space-6); padding-top: var(--space-3); border-top: 1px solid var(--border); color: var(--text-muted); font-size: var(--text-xs); }
@media (max-width: 900px) {
  .week { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 639px) {
  .page { padding: var(--space-4) var(--space-3); }
  header { display: block; }
  .week { grid-template-columns: 1fr; }
  .metric-value { font-size: var(--text-metric-sm); }
  th, td { padding: var(--space-2); }
}
@media print {
  body { background: var(--bg); color: var(--text); font-size: var(--text-print); }
  .page { max-width: none; padding: 0; }
  section { break-inside: avoid; }
  .block { break-inside: avoid; }
}
"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {check.week.iso}</title>
<style>{css}</style>
</head>
<body>
<div class="page">
<header><h1>{title}</h1><div class="meta">{check.week.iso} · {check.week.start.isoformat()} 至 {(check.week.end - timedelta(days=1)).isoformat()}<br>生成于 {html.escape(iso(check.generated_at))}</div></header>
<section aria-labelledby="summary-h">
<h2 id="summary-h">本周容量</h2>
<div class="metrics">
  <div class="metric"><div class="metric-label">可支配</div><div class="metric-value">{fmt_minutes(capacity)}</div></div>
  <div class="metric"><div class="metric-label">任务需要</div><div class="metric-value">{fmt_minutes(demand)}</div></div>
  <div class="metric"><div class="metric-label">缺口</div><div class="metric-value" style="color: var(--{'danger' if check.gap_minutes else 'ok'})">{fmt_minutes(check.gap_minutes)}</div></div>
</div>
<div class="bar{' over' if check.overcommitted else ''}"><span style="width: {ratio:.1f}%"></span></div>
<div class="bar-caption"><span>已排 {fmt_minutes(plan.summary['scheduledMinutes'])} / 可排 {fmt_minutes(capacity)}</span><span>{'本周没有可用时间' if capacity == 0 else ''}</span></div>
<div class="status">{_status_text(plan)}</div>
</section>
<section aria-labelledby="week-h">
<h2 id="week-h">周一至周日</h2>
<div class="week">{''.join(day_html)}</div>
</section>
<section aria-labelledby="unscheduled-h">
<h2 id="unscheduled-h">未排程</h2>
{unscheduled_html}
</section>
<section aria-labelledby="findings-h">
<h2 id="findings-h">{finding_title}</h2>
{findings_html}
</section>
<footer>Weeklint {__version__} · 本地生成，无网络请求 · 只读输入，不改日历和任务文件</footer>
</div>
</body>
</html>
"""
