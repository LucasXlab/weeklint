# 功能清单（v0.1.0）

Weeklint 只做一件事：把「这周到底装不装得下」算清楚，并把装得下的部分排成一个可解释、可锁定的周计划。下面是已实现的功能，不含路线图。

## 1. 输入

### Markdown 任务

一行一个任务，必须是复选框：

```markdown
- [ ] 写课程论文 @due(2026-11-05T17:00) @estimate(240m) @priority(high) @tag(course)
- [x] 已完成的任务也会被读取，但不计入需求
```

| 元数据 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `@due(...)` | 否 | `YYYY-MM-DD`、`YYYY-MM-DDTHH:MM[:SS]`，可带 `Z` / `±HH:MM` | 只有日期时按当天 23:59；不带偏移按配置时区 |
| `@estimate(...)` | 否 | `30m`、`1h`、`1h30m`、`1.5h`，5–2400 分钟 | 省略时用 `default_estimate_minutes` |
| `@priority(...)` | 否 | `high` / `normal` / `low` | 默认 `normal` |
| `@tag(...)` | 否 | 1–24 个 `[A-Za-z0-9_-]`，最多 8 个 | 只用于展示 |
| `@id(...)` | 否 | 1–64 个 `[A-Za-z0-9_-]` | 省略时按标题哈希生成 `t-xxxxxxxx` |

- 元数据必须写在行尾，顺序任意。
- 标题可以包含 `@`、括号、逗号；只有行尾 `@key(value)` 会被当作元数据。
- 重复 id、未知元数据、非法日期/估算/优先级都会给出带行号的错误，不会静默跳过。
- 任务文件上限 1 MiB、500 个未完成任务。

### ICS 日历

- 支持 `VEVENT` 的 `UID`、`SUMMARY`、`DTSTART`、`DTEND`、`DURATION`、`RRULE`、`EXDATE`、`RDATE`、`STATUS`、`TRANSP`。
- 支持全天事件、`TZID` 时间、UTC 时间、浮动时间。
- `STATUS:CANCELLED` 和 `TRANSP:TRANSPARENT` 不计入忙时。
- 重复事件按 `dateutil.rrule` 展开，只保留与本周相交的实例。
- `RECURRENCE-ID` 单次修改不合并，跳过并 warning（见 `deviations.md` #9）。
- 文件上限 5 MiB/个、20 MiB/总、20 个文件；单文件 5000 个 VEVENT，本周展开 20000 个实例。

### 配置

`weeklint.yaml` 是唯一配置入口。完整字段、默认值和校验错误见 `SPEC.md` 第 2 节。最小配置：

```yaml
version: 1
timezone: Asia/Shanghai
```

其余字段都有默认值。路径相对配置文件所在目录解析。

## 2. 计算

`check` 输出四个可复算的数字：

| 字段 | 公式 |
|---|---|
| `workMinutes` | 周一到周日配置的工作时间总和 |
| `busyMinutes` | 日历事件与工作时间求交后的分钟，加 `buffer_after_event_minutes`，buffer 不超出当天工作结束 |
| `freeMinutes` | `workMinutes - busyMinutes` |
| `usableMinutes` | 自由区间中长度 ≥ `min_block_minutes` 的部分 |

`demand.estimatedMinutes` 只统计本周范围内的未完成任务（截止晚于本周日 23:59 的任务不计入，给一条 `task_after_horizon` info）；`gapMinutes = max(0, demand - usable)`，`overcommitted = gap > 0`。

## 3. 排程

- 任务排序：过期 → 截止升序（无截止最后）→ 优先级 high/normal/low → 估算降序 → id。
- 切块：总时长 ≤ `max_block_minutes` 时一块；否则 `ceil(total/max_block)` 块，向下调整到每块 ≥ `min_block`；块长用 `floor` 分配，总和严格等于总时长。
- 高优先级优先上午（开始 < 12:00），没有上午空档再用下午。
- 一个任务每天最多一个块；每个新块后加 `gap_between_tasks_minutes`。
- 每天不同任务数不超过 `max_tasks_per_day`；高优先级分钟不超过 `max_deep_work_minutes_per_day`（0 表示不限）。
- 任何一块放不下，回滚该任务本次新放的所有块，整任务进入 `unscheduled`；不会留下半截任务。
- 旧计划中满足条件的块保留为 `locked=true`，永不回滚；任务剩余分钟 = 估算 − 已锁定分钟。

## 4. 输出

| 文件 | 内容 |
|---|---|
| `plan.json` | 周范围、按天容量、块、未排程、summary、findings、文件路径 |
| `plan.ics` | 每个块一个 VEVENT；UTC 时间；可导入日历 |
| `plan.md` | 按天分组的 Markdown 表格，末尾未排程 |
| `report.html` | 单文件报告；无脚本、无外部资源；浅色/深色 token；375px；打印样式 |

写文件用同目录临时文件 + `os.replace`，临时文件 0600，最终文件 0644；旧 `plan.json` 先复制为 `plan.prev.json`。`plan` 用 `output_dir/.lock` 串行化，超过 10 分钟的锁视为陈旧并清理。

## 5. 命令

| 命令 | 作用 | 退出码 |
|---|---|---|
| `init [--dir]` | 创建配置、任务、空日历 | 0 / 2 |
| `check [--week]` | 只计算，不写文件 | 0 无 error / 1 有 error / 2 输入错误 |
| `plan [--week] [--no-report]` | 计算并写四个文件 | 0 无 error / 1 有 error / 2 输入错误 |
| `today` | 今天的块、下一块、到期未排 | 0 / 2 |
| `explain <id或标题>` | 某任务的块与原因 | 0 / 2 |
| `doctor` | 解析检查与计数 | 0 / 2（输入错误） |
| `version` | 版本 | 0 |

全局参数：`--config`、`--json`、`--now`、`--week`、`--no-color`；可写在命令前或后。

## 6. 错误与 finding

- 非 finding 错误在 `--json` 时是 stderr 上的一行 `{error, code, detail}`；人类模式是「消息 + 错误码 + detail JSON」。
- 退出码：0 正常；1 至少一个 `severity=error` 的 finding；2 用户/输入/配置/写文件错误；3 未预期内部错误。
- finding 级别：`error`（overcommitted、deadline_at_risk、task_unscheduled）、`warning`（过期、未估算、碎片日、无日历、DST 调整等）、`info`（截止晚于本周）。
- 完整错误码与 finding 码见 `SPEC.md` 第 4.3、5.3 节。

## 7. 隐私

- 没有网络调用、没有账号、没有 OAuth、没有 LLM、没有遥测。
- 只读配置指定的任务/日历文件；只写 `output_dir`。
- HTML 报告转义所有用户字符串；ICS 由 `icalendar` 做 RFC 5545 转义。
- 不需要 API key；`.env.example` 只有本地路径和调试开关。

## 8. 不包含

- 不做日历双向同步；不写回 Google/Outlook/Apple 日历。
- 不做多人协作、账号、云端存储。
- 不做自然语言解析、AI 建议、自动优先级。
- 不解析 `VTODO`、`VALARM`、`VFREEBUSY`。
