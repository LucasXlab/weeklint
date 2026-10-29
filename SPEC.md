# 周检 Weeklint — 规格（v0.1.0）

> 这是唯一契约。实现、测试、README 和输出字段以本文件为准；开发中任何偏离都编号写入 [docs/deviations.md](docs/deviations.md)。字段名、枚举值、退出码、错误码一字不差。

## 0. 产品说明

**给谁**：用 `.ics` 日历（Google Calendar、Outlook、Apple 日历导出）记固定事件，用 Markdown 记任务，每周会做一次周计划的学生和独立开发者。

**做什么**：读入用户已有的日历和任务文件，先算清这一周还剩多少可支配时间，再回答三个问题：

1. 这周装得下吗？（`check`）
2. 如果装不下，具体哪几个任务做不完？（`check` / `plan`）
3. 装得下的部分，排在哪几天、为什么排在那里？（`plan` / `today` / `explain`）

**靠什么做到**：本地解析 ICS（RFC 5545）和 Markdown；用整数分钟做时间预算；用确定性的优先级 + 截止日期 + 时间块算法排程；输出带解释的 JSON、Markdown、ICS 和一份单文件 HTML 周报。不联网、不接 OAuth、不调用大模型、不读取任何密钥。

**第一版只做的核心流程**：

```text
weeklint init
  → 用户编辑 weeklint.yaml、tasks.md，导出 calendar.ics
  → weeklint check       # 这周够不够，哪些任务有风险
  → weeklint plan        # 生成 plan.json / plan.ics / plan.md / report.html
  → weeklint today       # 今天做什么
  → weeklint explain ID  # 为什么排在这里
```

**非目标（v0.1.0 明确不做）**：

- 不做账号、云同步、多人协作、团队日历；
- 不做手机 App、推送通知、后台常驻；
- 不写回 Google Calendar / Outlook / Apple 日历，不调用任何日历 API；
- 不做任务管理数据库，不改写 `tasks.md`，不提供看板/标签体系；
- 不做 Google Tasks、Todoist、Notion、Obsidian 的双向同步；
- 不做自然语言录入、AI 排优先级、AI 估算工时；
- 不做番茄钟、时间追踪、习惯打卡；
- 不做 Windows/macOS 安装包；只发布 Python 包和单文件 HTML 报告；
- 不承诺「排出来的计划一定合理」；只承诺约束满足、结果可解释、可复现。

## 1. 目录与技术栈

```text
weeklint/
  pyproject.toml
  SPEC.md
  DESIGN.md
  README.md
  README_EN.md
  LICENSE
  CHANGELOG.md
  .env.example
  .gitignore
  src/weeklint/
    __init__.py
    __main__.py
    cli.py            argparse 命令与输出
    config.py         配置加载与校验
    tasks.py          Markdown 任务解析
    ics.py            ICS 解析、重复事件展开、忙闲区间
    model.py          dataclass：Task / Event / FreeSlot / Block / Finding
    budget.py         周范围、时间预算、findings
    planner.py        确定性排程、锁定旧计划
    report.py         plan.json / plan.ics / plan.md / report.html
    errors.py         WeeklintError 与错误码
  tests/
    test_config.py
    test_tasks.py
    test_ics.py
    test_budget.py
    test_planner.py
    test_cli.py
    test_report.py
    fixtures/
  docs/
    features.md
    development.md
    deviations.md
    external-apis.md
```

- 语言：Python **3.11+**（使用 `zoneinfo`、`tomllib` 不需要；代码兼容 3.11、3.12、3.13）。
- 运行依赖（精确版本下限，允许同主版本升级）：
  - `icalendar>=6.1,<7`（实测 6.3.2）
  - `python-dateutil>=2.9,<3`（实测 2.9.0.post0）
  - `PyYAML>=6.0,<7`（实测 6.0.3）
  - `rich>=13.9,<14`（实测 13.9.4）
- 开发依赖：`pytest>=8.3,<9`（实测 8.4.2）。
- 安装：`pipx install weeklint`（发布后）或 `pip install .`；开发：`python -m venv .venv && .venv/bin/pip install -e '.[dev]'`。
- 入口：`weeklint` 命令，等价于 `python -m weeklint`。
- 最低运行环境：Python 3.11，任意支持 UTF-8 的终端；HTML 报告支持最近两个版本的 Chrome、Safari、Firefox、Edge。
- 不引入数据库、不启动服务、不监听端口。
- 代码风格：Python 标准库 + 上述依赖；不引入网络库；不执行子进程。

## 2. 配置

### 2.1 环境变量

只读取 `WEEKLINT_` 前缀；不读取 `NO_COLOR` 以外的通用变量。所有变量在每次命令启动时读取。

| 变量 | 默认 | 必填 | 非法时 |
|---|---|---|---|
| `WEEKLINT_CONFIG` | `weeklint.yaml` | 否 | 空字符串视为默认；路径不存在按 `config_not_found` 处理 |
| `WEEKLINT_NOW` | 空（用系统当前时间） | 否 | 不是 ISO 8601 → 退出 2，`invalid_env`，说明变量名和期望格式 |
| `WEEKLINT_NO_COLOR` | `0` | 否 | 不是 `0`/`1` → 退出 2，`invalid_env` |
| `WEEKLINT_DEBUG` | `0` | 否 | 不是 `0`/`1` → 退出 2，`invalid_env` |

- `WEEKLINT_NOW` 同时接受带偏移（`2026-11-02T09:00:00+08:00`）、`Z` 结尾、以及不带偏移的本地时间（按配置时区解释）。
- 命令行 `--now` 优先于 `WEEKLINT_NOW`；`--config` 优先于 `WEEKLINT_CONFIG`。
- 本项目没有任何密钥、token、API key；日志和错误信息中也不允许出现用户文件全文，只允许出现路径、行号、任务 id 和出错片段（最多 80 字符）。

### 2.2 `weeklint.yaml`

`init` 生成的完整示例：

```yaml
version: 1
timezone: Asia/Shanghai
planning:
  include_weekends: false
  work_hours:
    mon: ["09:00-12:00", "13:30-18:00"]
    tue: ["09:00-12:00", "13:30-18:00"]
    wed: ["09:00-12:00", "13:30-18:00"]
    thu: ["09:00-12:00", "13:30-18:00"]
    fri: ["09:00-12:00", "13:30-18:00"]
    sat: []
    sun: []
  buffer_after_event_minutes: 10
  gap_between_tasks_minutes: 10
  min_block_minutes: 30
  max_block_minutes: 120
  max_deep_work_minutes_per_day: 180
  max_tasks_per_day: 4
  default_estimate_minutes: 60
  lock_existing_plan: true
  block_all_day_events: true
  task_file: tasks.md
  calendar_files: ["calendar.ics"]
  output_dir: .weeklint
  report:
    title: 本周计划
```

字段规则：

| 字段 | 类型 | 默认 | 取值 / 校验 | 非法时错误码 |
|---|---|---|---|---|
| `version` | int | 无，必须显式写 | 必须等于 `1` | `config_version_unsupported` |
| `timezone` | str | `UTC` | 必须是 `zoneinfo.ZoneInfo` 能识别的 IANA 名称 | `config_invalid_timezone` |
| `planning` | map | 见下 | 未知键拒绝 | `config_unknown_key` |
| `planning.include_weekends` | bool | `false` | 必须是 YAML 布尔 | `config_invalid_type` |
| `planning.work_hours` | map | 周一至周五 `09:00-18:00`，周六日空 | 键只能是 `mon,tue,wed,thu,fri,sat,sun`；值为字符串数组；每天最多 4 段 | `config_unknown_key` / `config_invalid_type` |
| 每段工作时间 | str | — | `HH:MM-HH:MM`，24 小时制，分钟必须是 5 的倍数，结束晚于开始，同一天内不重叠 | `config_invalid_time_range` |
| `planning.buffer_after_event_minutes` | int | `10` | 0–120 | `config_value_out_of_range` |
| `planning.gap_between_tasks_minutes` | int | `10` | 0–120 | `config_value_out_of_range` |
| `planning.min_block_minutes` | int | `30` | 15–240 | `config_value_out_of_range` |
| `planning.max_block_minutes` | int | `120` | 30–480，且 ≥ `min_block_minutes` | `config_value_out_of_range` |
| `planning.max_deep_work_minutes_per_day` | int | `180` | 0–720；`0` 表示高优先级任务不受此限 | `config_value_out_of_range` |
| `planning.max_tasks_per_day` | int | `4` | 1–12 | `config_value_out_of_range` |
| `planning.default_estimate_minutes` | int | `60` | 5–480 | `config_value_out_of_range` |
| `planning.lock_existing_plan` | bool | `true` | YAML 布尔 | `config_invalid_type` |
| `planning.block_all_day_events` | bool | `true` | YAML 布尔 | `config_invalid_type` |
| `planning.task_file` | str | `tasks.md` | 非空；相对路径按配置文件所在目录解析；绝对路径允许 | `config_invalid_path` |
| `planning.calendar_files` | str[] | `["calendar.ics"]` | 0–20 个；每项非空；相对路径按配置文件目录解析 | `config_invalid_path` / `config_too_many_calendars` |
| `planning.output_dir` | str | `.weeklint` | 非空；相对路径按配置目录解析；不能是已存在的普通文件 | `config_invalid_path` |
| `planning.report.title` | str | `本周计划` | 1–80 字符，不允许换行 | `config_invalid_value` |

- YAML 必须能用 `yaml.safe_load` 解析成 map；否则 `config_invalid_yaml`（带行号）。
- 未知顶层键或 `planning`/`planning.report` 下未知键：`config_unknown_key`，`detail.key` 写出完整路径（如 `planning.foo`）。
- 整数不接受布尔值（YAML 的 `true` 不能当 1）；字符串不接受数字。
- 所有路径展开 `~`；不做网络路径。
- 配置文件不存在：`config_not_found`。文件不是 UTF-8：`config_invalid_encoding`。文件大于 256 KiB：`config_too_large`。
- 读取配置阶段不检查 `task_file` / `calendar_files` 是否存在；执行 `check/plan/today/explain/doctor` 时再检查：
  - `task_file` 不存在 → `task_file_not_found`，退出 2；
  - `calendar_files` 是空数组 → warning `no_calendar_files`，按全空闲计算，退出 0；
  - `calendar_files` 非空但某个文件不存在 → `calendar_file_not_found`，退出 2；
  - 文件存在但无法读取（权限/IO）→ `calendar_file_unreadable`，退出 2。
- `output_dir` 不存在时 `plan` 创建；`check/today/explain/doctor` 不创建。

## 3. 数据模型

### 3.1 Task

从 `tasks.md` 解析；每个字段都出现在 `--json` 输出的 `tasks[]` 里。

```json
{
  "id": "t-3f2a91c0",
  "title": "写分布式系统实验报告",
  "estimateMinutes": 120,
  "due": "2026-11-04T23:59:00+08:00",
  "priority": "high",
  "tags": ["course", "distributed"],
  "line": 12,
  "completed": false,
  "estimated": true
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | `t-` + 8 位十六进制；或用户显式 `@id(...)`；全局唯一 |
| `title` | str | 1–200 字符；去掉首尾空白；不允许换行 |
| `estimateMinutes` | int | 5–2400；未写时用 `default_estimate_minutes` |
| `due` | str\|null | 带时区偏移的 ISO 8601；日期形式按当天 `23:59` 配置时区解释 |
| `priority` | `"high"\|"normal"\|"low"` | 默认 `normal` |
| `tags` | str[] | 0–8 个；每个 1–24 字符 `[A-Za-z0-9_-]` |
| `line` | int | 1 起的行号 |
| `completed` | bool | `[x]`/`[X]` 为 true |
| `estimated` | bool | 是否写了 `@estimate` |

Markdown 语法：

```markdown
- [ ] 写分布式系统实验报告 @due(2026-11-04T17:00) @estimate(2h) @priority(high) @tag(course)
- [x] 读完第 5 章
- [ ] 给导师发周报 @due(2026-11-06) @estimate(30m) @id(advisor-weekly)
```

- 行首允许空白；列表符号 `-` 或 `*`；方括号内是空格、`x` 或 `X`。
- 元数据必须写在标题末尾，格式 `@key(value)`，键和值之间没有空格；多个元数据用空格分隔，顺序任意。
- 支持的键：`due`、`estimate`、`priority`、`tag`、`id`。不区分键的大小写，值按原样解析。
- 标题是去掉末尾元数据后的剩余文本；标题中允许出现 `@`，但如果末尾出现未知 `@key(...)`，按 `task_unknown_metadata` 报错（防拼写错误）。
- 未匹配任务行的文本（标题、说明、空行、`#` 注释）全部忽略；不解析子任务层级。
- 文件编码 UTF-8（允许 BOM）；换行 LF/CRLF 都接受。文件大于 1 MiB → `task_file_too_large`。
- 最多 500 个未完成任务；超过 → `too_many_tasks`。
- 重复 id → `task_duplicate_id`；标题相同且都没写 `@id` → 派生 id 冲突，同样按 `task_duplicate_id` 报错，错误信息提示加 `@id`。
- 解析错误一律退出 2，`detail.line` 给出 1 起行号，`detail.snippet` 给出该行最多 80 字符；不输出整份文件。

### 3.2 CalendarEvent（内部）

不直接输出完整对象；用于计算忙闲。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | str | ICS UID，缺失时用 `sha1(summary+start)[:12]` |
| `summary` | str | 事件标题；仅用于人类排障，不进入 HTML 的任务区 |
| `start` | datetime | 已转成配置时区，带 tzinfo |
| `end` | datetime | 已转成配置时区；必须 > start |
| `allDay` | bool | DTSTART 是 DATE |
| `sourceFile` | str | 来源文件名 |

### 3.3 FreeSlot

```json
{"date":"2026-11-02","start":"09:00","end":"12:00","minutes":180}
```

内部用 datetime；JSON 输出只用于 `doctor --json` 的 `freeSlots`（可选）。

### 3.4 Block

```json
{
  "taskId": "t-3f2a91c0",
  "title": "写分布式系统实验报告",
  "start": "2026-11-02T09:00:00+08:00",
  "end": "2026-11-02T10:30:00+08:00",
  "minutes": 90,
  "locked": false,
  "reason": "截止 11-04 17:00，高优先级；放在周一上午第一个足够长的空档。"
}
```

### 3.5 Finding

```json
{
  "code": "overcommitted",
  "severity": "error",
  "message": "本周可用 18 小时 30 分，任务需要 24 小时，缺口 5 小时 30 分。",
  "taskId": null,
  "day": null,
  "value": 330
}
```

`severity` 取值 `error|warning|info`。`value` 是分钟数或 null。

## 4. CLI

### 4.1 通用规则

```text
weeklint [--config PATH] [--json] [--now ISO] [--week YYYY-Www] [--no-color] <command> ...
```

- 全局参数可以写在命令前，也可以写在命令后（argparse 的父解析器实现）。
- `--json`：stdout 只输出一个 JSON 对象，末尾一个换行；不输出 ANSI、不输出进度条、不输出人类表格。错误仍写 stderr，格式见 4.3。
- `--no-color` 等价于 `WEEKLINT_NO_COLOR=1`；优先级最高。
- `--now` 只影响「现在」的判断（过期、today 的当前时间、周范围默认值）；`--week` 指定周范围时，`now` 不改变范围。
- 没有 `--week` 时，周范围由 `now` 所在 ISO 周决定（周一 00:00 到下一周一 00:00，配置时区）。
- `--week` 必须是 `YYYY-Www`，周一到周日；不存在的周（如 `2027-W53`）→ `invalid_week`；`2026-W53` 是合法周（2026-12-28 至 2027-01-03）。
- 命令帮助：`weeklint --help`、`weeklint <command> --help`，退出 0。
- `weeklint --version` 输出 `weeklint 0.1.0`，退出 0；`weeklint version` 是独立子命令，等价于 `--version`，`--json` 输出 `{"version":"0.1.0"}`。
- `--week` 只适用于 `check/plan/explain`；`init/today/doctor/version` 带 `--week` → `invalid_argument`，退出 2。argparse 自身的未知子命令、缺参数错误也统一转成 `invalid_argument` 的 JSON/单行错误，不直接打印 usage 后退出。

### 4.2 命令

#### `version`

```text
weeklint version
```

- 人类输出 `weeklint 0.1.0`；`--json` 输出 `{"version":"0.1.0"}`；退出 0。

#### `init`

```text
weeklint init [--dir PATH]
```

- 在 `--dir`（默认当前目录）创建 `weeklint.yaml`、`tasks.md`、`calendar.ics`。
- `weeklint.yaml` 使用 2.2 的完整示例；`timezone` 写系统 IANA 时区（取不到则 `UTC`）。
- `tasks.md` 只写 3 行注释（第 2 行是注释掉的示例任务），避免用户第一次 check 看到假任务：

```markdown
# Weeklint 任务
# 每行一个任务：- [ ] 标题 @due(2026-11-04T17:00) @estimate(90m) @priority(high) @tag(course)
# 元数据可省略；省略 estimate 时使用配置里的 default_estimate_minutes。
```

- `calendar.ics` 是合法的空 VCALENDAR：

```ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Weeklint//Weeklint 0.1.0//ZH
CALSCALE:GREGORIAN
END:VCALENDAR
```

- 任一目标文件已存在 → 退出 2，`already_initialized`，`detail.path` 列出第一个已存在的文件；不覆盖、不写任何文件。
- `--dir` 不存在 → 创建（含父目录）；创建失败 → `init_failed`。
- 三个文件用 `O_CREAT|O_EXCL` 逐个创建；任一失败时删除本次已创建的文件（不删除运行前已存在的文件），再返回 `init_failed` 或 `already_initialized`。并发 `init` 由 `O_EXCL` 保证最多一个成功。
- 成功输出（人类）：`已创建 weeklint.yaml、tasks.md、calendar.ics。下一步：导出日历到 calendar.ics，再运行 weeklint check。`
- `--json`：`{"version":"0.1.0","created":["weeklint.yaml","tasks.md","calendar.ics"],"dir":"/abs/path"}`。

#### `check`

```text
weeklint check [--week YYYY-Www]
```

- 解析配置、任务、日历，计算 5 节的预算和 findings；不写任何文件。
- 人类输出：周范围、容量摘要、findings（按 error → warning → info）、任务表（id、标题、估算、截止、优先级、状态）。
- `--json` 输出 5.1 的 `CheckResult`。
- 退出码：`0` 无 `severity=error` 的 finding；`1` 至少一个 `severity=error`；`2` 配置/输入错误。
- 空任务文件：输出 warning `no_tasks`，退出 0。
- `calendar_files` 为空数组：warning `no_calendar_files`，按「所有工作时间都可用」计算，退出 0；非空但文件不存在或不可读按 §2.2 的错误处理，退出 2。

#### `plan`

```text
weeklint plan [--week YYYY-Www] [--no-report]
```

- 先做与 `check` 相同的解析和预算；即使有 error 也继续排程，写出「装得下的部分」。
- 读取 `output_dir/plan.json`（`lock_existing_plan=true` 时），按 6.3 保留可复用的旧块。
- 写文件（全部在 `output_dir` 下）：
  - `plan.json`：6.4 的 PlanResult；写新文件前，如已有 `plan.json`，先原子复制为 `plan.prev.json`。
  - `plan.ics`：每个 block 一个 VEVENT。
  - `plan.md`：按天分组的 Markdown 表格，末尾是未排程任务和容量摘要。
  - `report.html`：单文件 HTML，按 DESIGN.md。
  - `--no-report` 时不写 `report.html`，其余照写。
- 写文件用「同目录临时文件 + `os.replace`」；临时文件权限 0o600，最终文件 0o644（受 umask 影响）。
- `plan` 在 `output_dir/.lock` 上用 `O_CREAT|O_EXCL` 建锁；已存在 → `plan_locked`，退出 2；正常结束/异常都删除锁。锁文件只含 PID 和开始时间，超过 10 分钟视为陈旧锁，下一次运行会删除并 warning `stale_lock_removed`。
- 成功输出（人类）：容量摘要、已排/未排数量、四个文件路径。
- `--json`：6.5 的 `PlanOutput`。
- 退出码：`0` 排出计划且没有 error finding；`1` 至少一个 `severity=error` 的 finding（`overcommitted` / `deadline_at_risk` / `task_unscheduled`）；`2` 配置/输入/写文件错误。
- 未排程任务不删除，只在 `unscheduled[]` 里列出；不修改 `tasks.md`。
- 同一输入、同一 `--week` 连续运行两次（第二次的 `now` 可以不同），`plan.json` 除 `generatedAt`、`now`、`blocks[].locked` 外必须完全一致；第二次所有块 `locked=true`。

#### `today`

```text
weeklint today
```

- 默认读 `output_dir/plan.json`；若不存在或周范围不是当前周，则在内存中生成当周计划（不写文件），`planFound=false`。
- 输出今天的块（按开始时间）、下一块、今天到期但未排程的任务。
- 人类输出：`今天 · 11月4日 周三`，时间轴；没有块时输出 `今天没有安排。`。
- `--json`：6.6 的 `TodayResult`。
- 退出码：0 正常（包括今天没有安排）；2 配置/输入错误。

#### `explain <query>`

```text
weeklint explain <task-id-or-title-substring> [--week YYYY-Www]
```

- 先按 id 精确匹配；否则按标题不区分大小写子串匹配。
- 0 个匹配 → 2 `task_not_found`；多个匹配 → 2 `ambiguous_task`，`detail.matches` 列出最多 10 个 `{id,title,line}`。
- 读 `plan.json`；不存在则内存生成。输出任务的估算、截止、优先级、所有块及 `reason`；未排程时输出原因。
- `--json`：6.7 的 `ExplainResult`。
- 退出码：0 找到；2 未找到/歧义/输入错误。

#### `doctor`

```text
weeklint doctor
```

- 只做解析和校验：配置、任务、日历、重复 id、路径、输出目录是否可写（尝试在内存中判断，不创建文件；无法判断时 warning）。
- 输出计数：任务总数/未完成/已完成/未估算、日历事件数（展开后落在本周的）、每个文件的大小、本周可用分钟。
- 输入错误（缺文件、坏 YAML、坏 ICS、重复 id 等）走 4.3 的错误 JSON，退出 2；`findings[]` 只放 warning/info。输出目录可写性用 `os.access` 判断，无法确认时 warning `output_dir_unverified`，不创建文件。
- `--json`：6.8 的 `DoctorResult`。

### 4.3 错误格式

所有非 finding 的错误：

```json
{"error":"找不到配置文件：/path/weeklint.yaml","code":"config_not_found","detail":{"path":"/path/weeklint.yaml"}}
```

- 写 stderr；`--json` 时也是这个 JSON（一行），否则人类可读一行 + 可选 `detail`。
- 退出码：用户/输入/配置错误 `2`；未预期内部错误 `3`（`internal_error`，`WEEKLINT_DEBUG=1` 时 stderr 追加 traceback，且 traceback 中不得包含任务正文以外的内容；正常模式不输出 traceback）。
- 错误码全集（v0.1.0）：

| 错误码 | 退出 | 触发 |
|---|---:|---|
| `config_not_found` | 2 | 配置文件不存在 |
| `config_invalid_yaml` | 2 | YAML 解析失败 |
| `config_invalid_encoding` | 2 | 配置不是 UTF-8 |
| `config_too_large` | 2 | 配置 > 256 KiB |
| `config_version_unsupported` | 2 | `version != 1` |
| `config_unknown_key` | 2 | 未知键 |
| `config_invalid_type` | 2 | 类型不对 |
| `config_invalid_timezone` | 2 | 时区非法 |
| `config_invalid_time_range` | 2 | 工作时间格式/重叠/结束不晚于开始 |
| `config_value_out_of_range` | 2 | 数值越界 |
| `config_invalid_path` | 2 | 路径为空或 output_dir 是文件 |
| `config_invalid_value` | 2 | 标题为空/过长/含换行 |
| `config_too_many_calendars` | 2 | 日历文件 > 20 |
| `invalid_env` | 2 | `WEEKLINT_*` 变量非法 |
| `invalid_week` | 2 | `--week` 格式或周不存在 |
| `invalid_now` | 2 | `--now` 非法 |
| `task_file_not_found` | 2 | 任务文件不存在 |
| `task_file_too_large` | 2 | 任务文件 > 1 MiB |
| `task_file_encoding` | 2 | 任务文件不是 UTF-8 |
| `task_parse_error` | 2 | 任务行格式错误（空标题等） |
| `task_invalid_due` | 2 | `@due` 非法 |
| `task_invalid_estimate` | 2 | `@estimate` 非法/越界 |
| `task_invalid_priority` | 2 | 优先级不在枚举 |
| `task_invalid_tag` | 2 | 标签非法/超过 8 个 |
| `task_invalid_id` | 2 | 显式 id 非法 |
| `task_unknown_metadata` | 2 | 未知 `@key` |
| `task_duplicate_id` | 2 | id 冲突 |
| `too_many_tasks` | 2 | 未完成任务 > 500 |
| `calendar_file_not_found` | 2 | 日历文件不存在 |
| `calendar_file_unreadable` | 2 | 日历文件存在但无法读取（权限/IO） |
| `too_many_events` | 2 | 单个日历 VEVENT > 5000 或展开后本周实例 > 20000 |
| `plan_locked` | 2 | 另一个 `plan` 正在写同一输出目录（`.lock` 存在） |
| `invalid_argument` | 2 | 参数组合不适用（如 `today --week`、未知子命令、缺参数） |
| `calendar_file_too_large` | 2 | 单个日历 > 5 MiB |
| `calendar_too_large` | 2 | 日历总大小 > 20 MiB |
| `ics_parse_error` | 2 | ICS 无法解析 |
| `ics_invalid_event` | 2 | VEVENT 的 DTSTART/DTEND/DURATION 非法 |
| `output_dir_not_writable` | 2 | 输出目录无法创建/写入 |
| `output_dir_unverified` | — | doctor 的 warning：无法确认输出目录可写（不创建文件） |
| `write_failed` | 2 | 临时文件写入或 `os.replace` 失败；已替换完成的文件保留，临时文件清理 |
| `task_not_found` | 2 | explain 无匹配 |
| `ambiguous_task` | 2 | explain 多个匹配 |
| `already_initialized` | 2 | init 目标文件已存在 |
| `init_failed` | 2 | init 创建失败 |
| `internal_error` | 3 | 未预期异常 |

## 5. 预算与发现

### 5.1 CheckResult（`check --json`）

```json
{
  "version": "0.1.0",
  "week": {"iso": "2026-W45", "start": "2026-11-02", "end": "2026-11-09", "timezone": "Asia/Shanghai"},
  "generatedAt": "2026-11-01T20:00:00+08:00",
  "now": "2026-11-01T20:00:00+08:00",
  "capacity": {
    "workMinutes": 2400,
    "busyMinutes": 720,
    "bufferMinutes": 70,
    "freeMinutes": 1680,
    "usableMinutes": 1540
  },
  "demand": {"taskCount": 8, "estimatedMinutes": 1860, "unestimatedCount": 2},
  "days": [
    {"date": "2026-11-02", "workMinutes": 480, "busyMinutes": 120, "freeMinutes": 360, "usableMinutes": 330}
  ],
  "gapMinutes": 320,
  "overcommitted": true,
  "tasks": [],
  "findings": []
}
```

- `week.end` 是**下周一**（不含），不是周日。
- `generatedAt` 是运行时刻的 ISO 8601，带配置时区偏移；测试里由 `--now` 决定，保证可断言。
- `capacity.workMinutes`：本周工作时间总和。
- `capacity.busyMinutes`：日历事件占用（已含 `buffer_after_event_minutes`，且已与工作时间求交）。
- `capacity.bufferMinutes`：`busyMinutes` 中由 buffer 贡献的部分，单独列出便于解释。
- `capacity.freeMinutes`：`workMinutes - busyMinutes`。
- `capacity.usableMinutes`：`freeMinutes` 中长度 ≥ `min_block_minutes` 的空档总和；用于排程。
- `demand.taskCount`：5.2 范围内未完成任务数（含未估算）。
- `demand.estimatedMinutes`：5.2 范围内未完成任务的估算总和；截止晚于 `week.end` 的任务不计入。
- `demand.unestimatedCount`：5.2 范围内未写 `@estimate` 的任务数。
- `gapMinutes = max(0, estimatedMinutes - usableMinutes)`。
- `overcommitted = gapMinutes > 0`。
- `days[]`：按周一到周日，每项 `date`（`YYYY-MM-DD`）、`workMinutes`、`busyMinutes`（含 buffer）、`freeMinutes`、`usableMinutes`；被 `include_weekends=false` 排除的周末也输出，三个分钟数均为 0。DESIGN 的「可用」一律指 `usableMinutes`。
- `tasks[]`：3.1 的 Task，加两个字段：
  - `scheduledMinutes`：`check` 里固定为 0（未排程）；
  - `atRisk`：布尔；`check` 中定义为 `overcommitted == true` 且 `due != null` 且 `due <= week.end`；`plan` 输出的同名字段按 6.4 覆盖（已排看块结束，未排看截止）。
- `findings[]`：3.5 的 Finding，按 `severity`（error→warning→info）、`code`、`taskId`、`day` 排序。

### 5.2 任务范围

- 未完成任务中，`due == null` 或 `due <= week.end` 的进入本周范围；`due > week.end` 的不进入，输出 `task_after_horizon`（info，每个任务一条）。
- 已完成任务不进入范围，不产生 finding；`doctor` 统计。
- 截止日期早于 `now` 的任务标 `overdue`，输出 `overdue_task`（warning），并参与排程（优先）。
- 没有截止日期的任务参与排程，按优先级排序。

### 5.3 发现码

| code | severity | 触发 | message 必须包含 |
|---|---|---|---|
| `overcommitted` | error | `gapMinutes > 0` | 可用分钟、需求分钟、缺口分钟 |
| `deadline_at_risk` | error | `check` 中 `overcommitted` 且任务有截止日期；`plan` 中块结束晚于 `due` 或任务未排程且有截止日期 | `check` 固定文案「本周容量不足，可能无法在截止前完成」；`plan` 必须含任务标题、截止时间、块结束或未排程原因 |
| `task_unscheduled` | error | `plan` 中任务因 `no_capacity`/`deep_work_limit`/`task_limit` 整条未排（含仅有 locked 块但剩余排不下） | 任务标题、剩余分钟、原因 |
| `task_unestimated` | warning | `estimated == false` | 任务标题、采用的默认分钟 |
| `overdue_task` | warning | `due < now` | 任务标题、截止时间 |
| `no_tasks` | warning | 未完成任务数为 0 | 任务文件路径 |
| `no_calendar_files` | warning | `calendar_files` 为空 | 说明按全空闲计算 |
| `fragmented_day` | warning | 某天存在长度 >0 且 < `min_block_minutes` 的自由区间，且该天没有任何长度 ≥ `min_block_minutes` 的自由区间 | 日期、碎片总分钟 |
| `dst_adjusted` | warning | 输入的本地时间落在跳变/回拨点，已按 6.1 规则调整 | 调整前后的时间 |
| `stale_lock_removed` | warning | `output_dir/.lock` 超过 10 分钟，已删除并继续 | 锁文件路径、时间 |
| `duplicate_event` | warning | 两个 VEVENT 的 UID+start+end 完全相同，保留第一条 | UID、来源文件 |
| `no_work_hours` | warning | 某天工作时间总长为 0 且不是周末被排除 | 日期 |
| `task_after_horizon` | info | 任务截止晚于 `week.end` | 任务标题、截止时间 |
| `all_day_ignored` | warning | `block_all_day_events=false` 且遇到全天事件 | 事件标题、日期 |
| `recurrence_override_ignored` | warning | 遇到带 `RECURRENCE-ID` 的 VEVENT | 事件标题、UID |
| `recurrence_truncated` | warning | 单个 RRULE 展开超过 1000 次 | UID |
| `event_missing_start` | warning | VEVENT 无 DTSTART | 来源文件、UID |
| `event_missing_end` | warning | VEVENT 无 DTEND/DURATION | 来源文件、UID |
| `previous_plan_invalid` | warning | 旧 `plan.json` 无法解析或版本不符 | 路径、原因 |
| `previous_plan_week_mismatch` | info | 旧计划不是本周 | 旧周、当前周 |
| `locked_block_dropped` | warning | 旧块因任务不存在/完成/冲突被丢弃 | 任务 id、原因 |
| `previous_plan_ignored` | warning | 旧 `plan.json` 无法解析、版本不符或不是本周 | 原因 |

- `deadline_at_risk` 在 `check` 中只对「有截止日期且 `overcommitted`」的任务发；具体完成时间无法在 `check` 中确定，message 固定写「本周容量不足，可能无法在截止前完成」，靠 `taskId` 定位，不要求含标题和截止。
- `check` 不输出 `deadline_at_risk` 之外的任务级排程判断；`task_unscheduled` 只由 `plan` 产生。
- `plan` 的 findings 与 `check` 相同，但 `deadline_at_risk` 的依据换成实际块，并追加 `task_unscheduled`；`overcommitted` 仍保留。

## 6. 排程

### 6.1 时间范围

- 周范围：配置时区下周一 00:00（含）到下一周一 00:00（不含）。
- 本地时间规则：不存在的本地时间（春令时跳变）按跳变后的偏移顺延；有歧义的本地时间（秋令时回拨）取 `fold=0`（第一次出现）。`@due`、`work_hours`、周边界统一用这个规则。
- 工作时间按天切成区间；只保留与周范围相交的部分。
- 日历事件按天切分后，与工作时间求交，再加 `buffer_after_event_minutes`：buffer 加在事件结束之后，且不超出当天工作时间；多个事件重叠时先合并事件再统一加 buffer，避免重复计算。
- 计算顺序：工作时间 → 减去事件 → 得到自由区间 → 合并相邻/重叠自由区间 → 过滤掉 < `min_block_minutes` 的区间得到 `usable`。

### 6.2 任务排序

对未完成任务排序，键为：

1. `overdue`（`due < now`）在前；
2. `due` 升序，`null` 最后；
3. `priority`：`high` > `normal` > `low`；
4. `estimateMinutes` 降序；
5. `id` 字典序升序。

### 6.3 旧计划锁定

- `lock_existing_plan=true` 时，读 `output_dir/plan.json`。
- 仅当 `week.start` 与当前周相同、`version` 相同、JSON 可解析时使用；否则 warning。
- 对每个旧 block：
  - 任务 id 存在、任务未完成、任务仍在范围内；
  - block 起止在周范围内，落在工作时间，且不与任何日历事件（含 buffer）重叠；
  - 同一任务的旧 block 总分钟不超过任务估算；
  - 满足以上条件才保留，`locked=true`，计入当天已排分钟/任务数/深度工作分钟。
- 任何一条不满足就丢弃，warning `locked_block_dropped`。
- 旧块保留后，任务剩余分钟 = 估算 - 已锁定分钟；为 0 则不再排。

### 6.4 切块与放置

- `split_minutes(total, max_block, min_block)`：
  - `total <= max_block` → `[total]`；
  - 否则 `n = ceil(total / max_block)`，从 `n` 开始向下调整，直到 `total / n >= min_block` 或 `n == 1`；
  - 每块为 `total // n` 分钟，前 `total % n` 块各多 1 分钟（`floor` 分配，最后一块吸收余数），块长之和严格等于 `total`；不要求 5 分钟倍数，不使用 `round`。
  - 任务本身小于 `min_block_minutes` 时允许单块小于 `min_block`，但只能放进长度 ≥ `min_block` 的自由区间。
- 回滚只针对本次新放的块；`locked=true` 的旧块永不回滚。任务已有 locked 块但剩余分钟放不下时，保留 locked 块，任务进入 `unscheduled`，`remainingMinutes = 估算 - locked 分钟`。同日已有该任务的 locked 块时，不再为该任务新放块。
- 放置规则：
  - 按天从周一到周日；每天内按自由区间开始时间升序。
  - `high` 优先级优先选开始时间 < 12:00 的区间；如果没有，再选任意区间。
  - 一个任务每天最多一个块（多个块分到不同天）。
  - 放置后，在该块结束时间加 `gap_between_tasks_minutes`，作为同一天后续块的候选起点；gap 不从容量里再扣一次，只影响后续块位置。
  - 当天 `max_tasks_per_day` 按不同任务 id 计数；高优先级任务的分钟数不得超过 `max_deep_work_minutes_per_day`（`0` 表示不限）。
  - 若某个块放不下，回滚该任务已放的所有块，整任务进入 `unscheduled`，原因 `no_capacity`；不产生半截任务。
- 未排程原因枚举：`no_capacity`（没有任何足够长的空档）、`deep_work_limit`（仅因高优先级每日上限放不下）、`task_limit`（仅因每日任务数上限放不下）、`estimate_too_large`（估算 > 2400，理论上不会出现）。
- `atRisk`：
  - 已排任务：最后一个块结束 > `due`；
  - 未排任务：`due != null` 且 `due <= week.end`；
  - `due == null` 的未排任务不算 atRisk，但出现在 `unscheduled`。

### 6.5 PlanOutput（`plan --json`）

```json
{
  "version": "0.1.0",
  "week": {"iso": "2026-W45", "start": "2026-11-02", "end": "2026-11-09", "timezone": "Asia/Shanghai"},
  "days": [
    {"date": "2026-11-02", "workMinutes": 480, "busyMinutes": 120, "freeMinutes": 360, "usableMinutes": 330}
  ],
  "generatedAt": "2026-11-01T20:00:00+08:00",
  "now": "2026-11-01T20:00:00+08:00",
  "blocks": [],
  "unscheduled": [
    {"taskId": "t-...", "title": "...", "remainingMinutes": 120, "reason": "no_capacity"}
  ],
  "summary": {
    "scheduledMinutes": 1540,
    "unscheduledMinutes": 320,
    "tasksScheduled": 6,
    "tasksUnscheduled": 2,
    "capacityMinutes": 1540,
    "gapMinutes": 320
  },
  "findings": [],
  "files": {
    "planJson": "/abs/.weeklint/plan.json",
    "planIcs": "/abs/.weeklint/plan.ics",
    "planMarkdown": "/abs/.weeklint/plan.md",
    "reportHtml": "/abs/.weeklint/report.html"
  }
}
```

- `files.reportHtml` 在 `--no-report` 时为 `null`。
- `days[]` 与 5.1 相同，供 HTML 报告按天显示「可用」；`blocks[]` 按开始时间升序，同开始时间按 `taskId`。
- `summary.capacityMinutes = usableMinutes`；`gapMinutes = max(0, demand - capacity)`。
- `plan.json` 落盘内容与 `--json` 输出完全相同（含 `files`）。

### 6.6 TodayResult（`today --json`）

```json
{
  "version": "0.1.0",
  "date": "2026-11-04",
  "now": "2026-11-04T10:00:00+08:00",
  "planFound": true,
  "blocks": [],
  "next": null,
  "dueTodayUnscheduled": []
}
```

- `blocks`：当天所有块，按开始时间。
- `next`：`now` 之后最近的一个块；没有则 null。
- `dueTodayUnscheduled`：`due` 日期为今天且未排程的任务（含 `title`、`taskId`、`due`）。
- `planFound=false` 时 `blocks` 来自内存计划。

### 6.7 ExplainResult（`explain --json`）

```json
{
  "version": "0.1.0",
  "task": {},
  "blocks": [],
  "unscheduled": null,
  "reason": "截止 11-04 17:00，高优先级；放在周一上午第一个足够长的空档。"
}
```

- `blocks[]` 与 PlanOutput 的块结构相同。
- `unscheduled` 为 null 或 `{"remainingMinutes":120,"reason":"no_capacity"}`。
- `reason` 是给人看的中文一句话，必须包含排序依据（截止/优先级）和放置依据（第几个空档/哪一天）。

### 6.8 DoctorResult（`doctor --json`）

```json
{
  "version": "0.1.0",
  "configPath": "/abs/weeklint.yaml",
  "taskFile": "/abs/tasks.md",
  "calendarFiles": ["/abs/calendar.ics"],
  "counts": {
    "tasks": 10,
    "openTasks": 8,
    "completedTasks": 2,
    "unestimatedTasks": 1,
    "events": 12,
    "workMinutes": 2400,
    "freeMinutes": 1680,
    "usableMinutes": 1540
  },
  "findings": []
}
```

## 7. 核心流程（逐步）

### 7.1 `check`

1. 读环境变量、命令行参数；确定配置文件路径。
2. 读配置 → 校验 → 得到 `Config`；失败退出 2。
3. 读任务文件 → 解析为 `Task[]`；失败退出 2。
4. 读每个日历文件 → 解析为 `CalendarEvent[]`，展开本周重复事件；失败退出 2。
5. 计算周范围、工作时间、忙闲、容量。
6. 计算任务范围、需求、缺口、findings。
7. 设置 `atRisk`（5.1 规则）；排序。
8. 输出人类表格或 JSON；按 4.2 返回退出码。
9. 不写任何文件，不修改输入文件（测试用文件 mtime/hash 断言）。

### 7.2 `plan`

1. 执行 7.1 的 1–6。
2. 读取旧计划（6.3），保留可复用块。
3. 按 6.2 排序，按 6.4 切块/放置。
4. 计算 `unscheduled`、`summary`、`findings`、`atRisk`。
5. 创建 `output_dir`；按 4.2 写四个文件；任一写失败退出 2，已写成的文件保留。
6. 输出人类摘要或 JSON；有 error 返回 1，否则 0。

### 7.3 `today`

1. 读配置/任务/日历，确定 `now` 和当前周。
2. 读 `output_dir/plan.json`；若不存在/周不符/解析失败，内存生成计划（不写）。
3. 过滤当天块；计算 next；计算今天到期但未排程的任务。
4. 输出；退出 0/2。

### 7.4 `explain`

1. 读配置/任务/日历。
2. 按 id 或标题子串找任务；0/多匹配按错误处理。
3. 读/生成计划，找该任务的块或未排程记录。
4. 输出；退出 0/2。

### 7.5 `doctor`

1. 读配置/任务/日历；对每个文件做存在性、大小、编码、语法校验。
2. 计算计数和本周容量；不写文件。
3. 输出；有输入错误 2，否则 0。

## 8. 输出文件格式

### 8.1 `plan.json`

见 6.5，UTF-8、缩进 2、末尾换行。所有时间带偏移。

### 8.2 `plan.ics`

- 合法 VCALENDAR 2.0；`PRODID:-//Weeklint//Weeklint 0.1.0//ZH`；`CALSCALE:GREGORIAN`。
- 每个 block 一个 VEVENT：
  - `UID`: `weeklint-<taskId>-<YYYYMMDDTHHMM>-<n>@weeklint.local`，`n` 从 1 起，保证同一文件内唯一；
  - `DTSTAMP`: `generatedAt` 转 UTC，格式 `YYYYMMDDTHHMMSSZ`；
  - `DTSTART:YYYYMMDDTHHMMSSZ`（转 UTC，避免无 VTIMEZONE 的 TZID 导入问题）；
  - `DTEND:YYYYMMDDTHHMMSSZ`；
  - `SUMMARY`: `[Weeklint] <title>`，转义 `\`、`;`、`,` 和换行；
  - `DESCRIPTION`: `taskId=<id>; minutes=<n>; locked=<true|false>`；
  - `TRANSP:OPAQUE`。
- 行结束 CRLF；按 RFC 5545 的 75 octet 折行（UTF-8 字节），末尾 CRLF；用 `icalendar` 生成后重新解析验证。

### 8.3 `plan.md`

```markdown
# 本周计划（2026-W45）

容量：18 小时 30 分 · 已排：14 小时 20 分 · 未排：4 小时 10 分

## 周一 11-02

| 时间 | 任务 | 分钟 |
|---|---|---:|
| 09:00–10:30 | 写分布式系统实验报告 | 90 |

## 未排程

- 复习编译原理（120 分钟）：本周容量不足
```

- 时间格式 `HH:MM–HH:MM`（en dash）。
- 无块的日期写 `无安排。`。
- 未排程为空时写 `无。`。

### 8.4 `report.html`

见 DESIGN.md；要求：

- 单文件，UTF-8，`<!doctype html>`，`lang="zh-CN"`；
- 内联 `<style>`，不引用任何外部 CSS/JS/字体/图片；无 `<script>`；
- 浅色/深色跟随 `prefers-color-scheme`；
- 375px 宽度无横向滚动；
- 所有用户数据 HTML 转义；
- 打印时隐藏交互元素，保留周计划；
- 页脚写明「由 Weeklint 在本地生成；没有上传任何数据」。

## 9. 风险与防护

| 风险 | 防护 | 测试 |
|---|---|---|
| 算错容量，误导用户 | 全部用整数分钟；日历与工作时间求交；buffer 单独记账；`check` 输出可复算的四个数字 | `test_budget.py` 覆盖重叠事件、跨天、全天事件、buffer、周末 |
| 把任务排到截止后 | 排序按截止；排完逐块比较 `end > due`；产生 `deadline_at_risk` | `test_planner.py` 截止风险用例 |
| 重排把用户已确认的计划打乱 | `lock_existing_plan=true` 保留满足约束的旧块；不满足的写 `locked_block_dropped` | `test_planner.py` 锁定/冲突/任务完成 |
| 写坏用户的日历或任务 | 只读 `tasks.md`/`.ics`；输出只写 `output_dir`；不调用日历 API | `test_cli.py` 运行前后 hash/mtime 不变 |
| 输出文件写一半 | 临时文件 + `os.replace`；先备份 `plan.prev.json` | `test_report.py` 模拟写入失败，断言旧文件仍在 |
| HTML 注入 | 所有标题/标签/路径用 `html.escape`；不输出 `<script>` | `test_report.py` 标题含 `<script>`、引号、`</style>` |
| ICS 注入 | 按 RFC 5545 转义 `\ ; , 换行` | `test_report.py` 标题含逗号/分号/换行 |
| 超大输入拖垮内存 | 配置 256 KiB、任务 1 MiB/500 条、单个 ICS 5 MiB、总 20 MiB、RRULE 1000 次 | `test_config/test_tasks/test_ics` 上限用例 |
| 路径越界/覆盖 | 输出文件固定四名；`output_dir` 解析后写入；不拼接用户可控文件名 | `test_cli.py` `output_dir` 指向文件时报错 |
| 时区/夏令时算错 | 统一转配置时区；日期边界用 `zoneinfo`；测试 `America/New_York` 春/秋令 | `test_ics.py` DST 用例 |
| 终端宽度/颜色不可读 | `rich` 自动换行；`--json` 无 ANSI；`NO_COLOR` 支持 | `test_cli.py` `--json` 不含 `\x1b` |
| 用户以为数据被上传 | README/报告页脚写明本地；代码无网络库；测试禁用 socket | `test_cli.py` monkeypatch socket 后跑完整流程 |

## 10. Mock 与测试替身

本项目**没有外部服务**：不调用大模型、第三方 API、网络请求、系统日历 API。因此不需要 mock 开关。唯一需要注入的外部输入是：

- **时钟**：`--now`（命令行）或 `WEEKLINT_NOW`（环境变量）；测试一律显式传 `--now`，不使用真实当前时间。
- **文件系统**：测试用 `tmp_path` 创建独立目录，每个用例一份；不读写用户目录。
- **终端**：测试用 `subprocess` 或 `CliRunner` 捕获 stdout/stderr，`--json` 断言无 ANSI。

测试中禁止：`time.sleep`、真实网络、读取 `$HOME` 下的配置、依赖当前日期、依赖 locale 的日期格式。需要等待的唯一场景是文件写入，写入是同步的，不需要轮询。

## 11. 测试要求

全部用 `pytest`，在临时目录和固定 `--now` 下运行，不联网。每个用例名用中文或英文描述行为；失败信息带输入片段。

### 11.1 配置（`test_config.py`）

- 最小配置能加载；所有默认值正确；`init` 生成的配置能加载。
- 缺文件 → `config_not_found`；空文件/非 map → `config_invalid_yaml`；非 UTF-8 → `config_invalid_encoding`；>256 KiB → `config_too_large`。
- `version` 缺失/为 2/为字符串 → `config_version_unsupported`。
- 未知顶层键、未知 `planning` 键、未知 `report` 键 → `config_unknown_key`，`detail.key` 正确。
- 类型错误：`include_weekends: "yes"`、`buffer_after_event_minutes: true`、`calendar_files: "x"` → `config_invalid_type`。
- 时区 `Mars/Base` → `config_invalid_timezone`；`UTC`、`Asia/Shanghai`、`America/New_York` 通过。
- 工作时间：`9:00-18:00`（缺前导 0）、`09:00-09:00`、`10:00-09:00`、`09:00-12:00` 与 `11:00-13:00` 重叠、分钟不是 5 的倍数、一天 5 段 → `config_invalid_time_range`。
- 数值边界：buffer -1/121、min_block 14/241、max_block 29/481、max_block < min_block、max_deep -1/721、max_tasks 0/13、default_estimate 4/481 → `config_value_out_of_range`。
- 路径：空 `task_file`、空 `calendar_files[]` 元素、`output_dir` 指向已存在普通文件 → `config_invalid_path`；21 个日历 → `config_too_many_calendars`。
- 标题空/81 字符/含换行 → `config_invalid_value`。
- 相对路径按配置文件目录解析；`~` 展开；绝对路径保留。
- 环境变量：`WEEKLINT_NOW` 非法、`WEEKLINT_NO_COLOR=yes`、`WEEKLINT_DEBUG=2` → `invalid_env`；`--now` 覆盖环境；`--config` 覆盖环境。
- 配置加载不检查任务/日历是否存在。

### 11.2 任务（`test_tasks.py`）

- 基本 `- [ ]` / `* [x]` / `- [X]`；完成/未完成计数。
- 标题、标签、优先级、估算、截止全部解析；日期形式补 `23:59`；带偏移/`Z` 保留。
- 估算格式：`90m`、`2h`、`1h30m`、`1.5h`、`5m`、`2400m`；`0m`、`4m`、`2401m`、`abc`、`1.5` → `task_invalid_estimate`。
- 截止格式：`2026-11-04`、`2026-11-04T17:00`、`2026-11-04T17:00:00+08:00`、`2026-11-04T09:00:00Z`；非法日期/时间/时区 → `task_invalid_due`。
- 优先级缺省 `normal`；`urgent` → `task_invalid_priority`。
- 标签 8 个通过；9 个、空、含空格/中文、25 字符 → `task_invalid_tag`。
- 显式 id 合法/非法；重复 id、同标题派生冲突 → `task_duplicate_id`。
- 未知 `@foo(bar)` → `task_unknown_metadata`；标题中间出现 `@` 不误判；末尾元数据顺序任意。
- 空标题 `- [ ]` → `task_parse_error`；标题 201 字符 → `task_parse_error`。
- 忽略标题、说明、空行、`#` 注释、普通列表；缩进任务照常解析。
- BOM、CRLF、UTF-8 中文；非 UTF-8 → `task_file_encoding`；1 MiB+1 → `task_file_too_large`；501 个未完成 → `too_many_tasks`。
- `line` 是原始行号；`snippet` 最多 80 字符。

### 11.3 ICS（`test_ics.py`）

- 单次事件、跨天事件、事件在周外、事件完全覆盖工作时间。
- 全天事件：`block_all_day_events=true` 阻塞当天；`false` 忽略并 warning。
- 重复：`FREQ=WEEKLY;BYDAY=MO,WE;COUNT=3`、`INTERVAL=2`、`UNTIL`、`EXDATE`、`RDATE`；`RECURRENCE-ID` 跳过并 warning；无 COUNT/UNTIL 的无限 RRULE 在本周结束后停止；本周实例 >1000 截断 warning；VEVENT >5000 或实例 >20000 → `too_many_events`。只展开与本周范围相交的实例；无 `COUNT`/`UNTIL` 的无限 RRULE 在实例开始时间超过 `week.end` 时停止；本周内实例超过 1000 个时截断并 warning。单个日历 VEVENT > 5000 或展开后本周实例 > 20000 → `too_many_events`。
- 时区：`TZID=America/New_York` 的春令时/秋令时；浮动时间按配置时区；`Z` 转配置时区。
- `STATUS:CANCELLED`、`TRANSP:TRANSPARENT` 忽略；`DURATION` 替代 DTEND；无 DTSTART/无结束 → warning 或错误。
- 多个日历文件合并；UID 缺失时 fallback 含来源文件和序号；仅 UID+start+end 全同才去重并 warning `duplicate_event`；单文件 >5 MiB、总 >20 MiB、21 个文件 → 错误。
- 非法 ICS → `ics_parse_error`；非法 DTSTART/DTEND → `ics_invalid_event`。
- RRULE 超过 1000 次 → 截断 + `recurrence_truncated`。
- buffer 加在事件后并裁剪到工作时间；相邻事件 buffer 不重复；事件结束在工作时间外不产生负区间。

### 11.4 预算（`test_budget.py`）

- 无事件：容量 = 工作时间；有事件：精确到分钟。
- 午休两段工作时间；事件跨午休；buffer 只加一次；事件重叠合并。
- 周末开关：`include_weekends=false` 时周六日不计；`true` 且配置了周六工作时间时计入；`true` 但周六空 → warning。
- `usableMinutes` 过滤小于 `min_block` 的碎片；`gapMinutes` 只在需求超出时为正。
- 任务范围：无截止、截止在本周、截止在周后、已完成、过期；对应 findings。
- `fragmented_day`、`no_work_hours`、`no_tasks`、`no_calendar_files` 的触发和 message 数字。
- `generatedAt`/`now` 来自 `--now`；周范围跨年：`2026-W53` 合法（2026-12-28 至 2027-01-03）；`2027-W53` 不存在 → `invalid_week`。
- 时区 `America/New_York` 的 DST 周：工作分钟数正确（23/25 小时日）；不存在的本地时间顺延、歧义时间取 fold=0，并产生 `dst_adjusted`。

### 11.5 排程（`test_planner.py`）

- 排序：过期 > 截止早 > 高优先级 > 长任务 > id。
- 切块：121m/120m/30m → 2 块且每块 ≥30；130m → 65+65；250m → 85+85+80；<30m 单块。
- 放置：周一第一个空档；高优先级上午优先；同一天不同任务数上限；高优先级每日上限。
- 截止风险：块结束晚于 due → `deadline_at_risk`；未排且有 due → atRisk。
- `max_tasks_per_day`/`max_deep_work_minutes_per_day` 导致整条未排（即使 `gapMinutes=0`）→ `task_unscheduled` error，`plan` 退出 1。
- `2026-W53` 是合法周（2026-12-28 至 2027-01-03）；`2027-W53` → `invalid_week`。
- 容量不足：整任务回滚，不产生半截；`unscheduled` 原因 `no_capacity`。
- 旧计划锁定：满足条件保留且 `locked=true`；事件冲突、任务完成、任务删除、跨周 → 丢弃 + warning。
- locked 块不因新块回滚而删除；剩余分钟排不下时保留 locked 块 + `task_unscheduled`，`remainingMinutes` 正确。
- 同日已有 locked 块时不再新放块。
- 并发：`plan` 锁存在 → `plan_locked`；陈旧锁 >10 分钟 → `stale_lock_removed` 并继续。
- 幂等：同一输入运行两次，blocks 相同（除 generatedAt）；第二次全部 locked。
- `lock_existing_plan=false` 时不读旧计划。
- 计划不修改输入文件；输出目录不存在时创建。
- `--no-report` 不写 report.html，`files.reportHtml=null`。

### 11.6 CLI（`test_cli.py`）

- `init` 创建三文件；内容可加载；已存在 → `already_initialized`；`--dir` 多级创建；`--json` 字段。
- `check` 退出码 0/1/2；`--json` 输出的键集合与 5.1 完全一致；无 ANSI；人类输出包含关键数字。
- `plan` 写四文件；`plan.json` 可解析且等于 stdout JSON；`plan.prev.json` 在第二次运行时出现；`plan.ics` 可被 `icalendar` 重新解析；`plan.md` 含表格。
- `today`：有 plan/无 plan/今天无块/next 正确/到期未排程。
- `explain`：id、标题子串、大小写、0 匹配、多个匹配、未排程任务。
- `doctor`：正常/缺任务/缺日历/重复 id；`--json` 计数。
- 错误：缺配置、坏 YAML、缺任务、坏 ICS、非法 `--week`、非法 `--now`、`output_dir` 是文件、`calendar_files` 空数组 vs 文件缺失 vs 不可读、`init` 已存在、`plan` 锁已存在；错误 JSON 字段 `error/code/detail`，退出 2；内部错误 3。
- `today/init/doctor/version --week` → `invalid_argument`；未知子命令、缺参数 → `invalid_argument` 的 JSON。
- `calendar_files` 为空 → warning `no_calendar_files` 且退出 0；文件缺失 → `calendar_file_not_found`；文件不可读 → `calendar_file_unreadable`。
- 所有命令 `--json` 时 stdout 只有一个 JSON 对象；stderr 为空（成功时）。
- `--version`、`version`、`version --json`、`--help`。
- 网络禁用测试：monkeypatch `socket.socket` 抛异常，运行 `check/plan` 仍成功。
- 输入不变测试：运行前后 `tasks.md`/`calendar.ics` 的 sha256 和 mtime 不变。

### 11.7 报告（`test_report.py`）

- HTML 含 `<!doctype html>`、`lang="zh-CN"`、`prefers-color-scheme`、375px media query、所有 token 变量。
- 不包含 `<script>`、`http://`、`https://`、`@import`、`url(` 外链。
- 任务标题含 `<script>alert(1)</script>`、`"`、`'`、`&`、`</style>` 时被转义，页面不出现可执行标签。
- ICS 标题含 `,`、`;`、`\`、换行时按 RFC 5545 转义，重新解析后标题一致。
- `--no-report` 不生成文件。
- 临时文件写入失败或 `os.replace` 失败时，删除临时文件，已替换完成的文件保留，退出 2 `write_failed`；旧 `plan.json` 不丢。
- 空计划也生成合法 HTML（显示「本周没有排程」）。

## 12. 文字与术语

界面、报错、日志、文档统一用词：

| 概念 | 统一用词 | 不要用 |
|---|---|---|
| 一段被排进日历的工作 | 时间块 | 卡片、事件块、slot |
| 日历里的固定安排 | 日历事件 | 会议（可能不是会议）、日程 |
| 未排进本周的任务 | 未排程任务 | 失败任务、 backlog |
| 本周可用时间不够 | 装不下 / 容量不足 | 爆了、超载 |
| 任务的预计耗时 | 估算 | 预估、工期 |
| 截止时间 | 截止时间 | deadline、DDL（正文可用一次解释） |
| 计划文件 | 周计划 | 排程结果、日程表 |

- 所有面向用户的句子用简洁书面语；不使用 emoji、颜文字、感叹号堆叠。
- 错误信息结构：`哪里出错 + 具体值 + 下一步怎么做`。例：`@estimate 的值 "0m" 无效：必须是 5–2400 分钟。请改成 30m 或 1h。`
- 日志只写 stderr，默认不输出 debug；`WEEKLINT_DEBUG=1` 时输出文件路径和阶段，不输出任务全文。

## 13. 版本与兼容

- 版本号 `0.1.0`；`weeklint --version`、`__version__`、`pyproject.toml` 三处一致。
- `plan.json`/`CheckResult` 的 `version` 字段为 `0.1.0`；读取旧计划时版本不一致 → warning 并忽略。
- Python 3.11/3.12/3.13 都跑测试；CI 矩阵覆盖。
- 升级不迁移数据（本来就没有数据库）；不兼容变更走次版本号并写 CHANGELOG。
