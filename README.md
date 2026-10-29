<p align="center"><img src="assets/logo.svg" width="88" height="88" alt="Weeklint"></p>

<h1 align="center">Weeklint 周检</h1>

<p align="center"><strong>先算这周装不装得下，再决定要不要答应。</strong></p>

<p align="center">
  <a href="README_EN.md">English</a> ·
  Python 3.11+ · MIT · 本地运行 · 无网络 · 无账号
</p>

Weeklint 是一个本地优先的周计划可行性检查器：读一份 Markdown 任务和一份 ICS 日历，先告诉你「这周到底装不装得下、哪些任务装不下」，再把能装下的部分排成一个可解释、可锁定的周计划。

它适合每周被课程、会议、兼职和截止日期切碎时间的人。你不需要把日历交给云端，也不需要让 AI 猜你的优先级。

![Weeklint 周计划报告](assets/screenshot-desktop.png)

> 截图来自 `examples/` 的真实输出，命令与时间见「复现截图」；没有改数字、没有用占位文本。

## 它解决什么问题

大多数待办工具假设「只要排进日历就能做完」。真实情况是：

- 一周只有那么多可用分钟，会议前后还有切换成本；
- 有些任务 4 小时，但每天只剩 40 分钟碎片；
- 你答应了新任务，却不知道它会把哪个截止日期挤掉；
- 上周已经确认的计划，这周重排时不该被悄悄打乱。

Weeklint 先做减法：工作时间 − 日历事件 − buffer = 真正可用的空档；再和任务估算比。缺口大于 0 时，它不会假装「排得下」，而是明确告诉你差多少分钟、哪些任务有截止风险。然后 `plan` 才排程，并且只排能完整放下的任务——不会留下做了一半的任务块。

## 适用 / 不适用

**适用**

- 每周有固定工作时间和若干会议，想先判断「这周能不能再接一个任务」。
- 用 Markdown 管任务、用 Google/Outlook/Apple 日历管会议，但不想把两者同步到同一个 SaaS。
- 需要一个可复现、可解释的排程结果：为什么这个任务在周二下午，而不是周一上午。

**不适用**

- 需要多人协作、审批、云端同步的团队排期。
- 需要 AI 自动拆解任务、自动定优先级、自然语言对话。
- 需要 CalDAV/Google Calendar 双向写回；Weeklint 只读 ICS 导出文件。

## 核心流程

```text
calendar.ics ──┐
               ├─► check ──► 本周容量 / 需求 / 缺口 / findings
tasks.md ──────┘                │
                                ├─► plan ──► plan.json / plan.ics / plan.md / report.html
                                │              （可锁定上次已确认的块）
                                └─► today ──► 今天做什么、下一块是什么
```

三个命令的分工：

- `check`：只算，不写文件。适合「要不要接这个任务」的 10 秒判断。
- `plan`：排程并写四个文件。适合周日晚上或周一早上生成一周计划。
- `today`：读当前计划，只看今天。适合每天早上。

## 功能

完整行为、边界和错误码见 [docs/features.md](docs/features.md)。

- **容量账本**：工作分钟、会议占用、buffer、自由分钟、可用分钟，四个数字可复算。
- **任务语法**：一行一个任务，支持 `@due`、`@estimate`、`@priority`、`@tag`、`@id`；未知元数据报错而不是静默忽略。
- **真实日历**：ICS 重复事件、EXDATE、全天事件、时区与 DST；`TRANSPARENT` / `CANCELLED` 不计入忙时。
- **确定性排程**：按过期/截止/优先级/估算排序；30–120 分钟块；高优先级优先上午；每日任务数和深度工作上限；放不下就整条回滚。
- **锁定旧计划**：上次已确认且仍满足约束的块保留为 `locked=true`，重排不会打乱。
- **可解释**：每个块有 `reason`；`explain` 能回答「为什么这个任务排在这里 / 为什么没排」。
- **单文件报告**：浅色/深色、375px、打印样式；无脚本、无外部字体/CSS/图片。
- **稳定错误格式**：`{error, code, detail}`，退出码 0/1/2/3；错误信息带文件、行号或字段，不泄露任务正文以外的内容。

## 快速开始

前提：Python 3.11 或更高版本，能运行 `python -m venv`。不需要 API key、数据库或服务器。

Weeklint 尚未发布到 PyPI，从源码安装：

```bash
# 在仓库根目录（有 pyproject.toml 的那一层）
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
```

初始化一个工作目录：

```bash
mkdir ~/week && cd ~/week
weeklint init
```

会创建三个文件：

```text
weeklint.yaml   配置：时区、工作时间、buffer、输出目录
tasks.md        任务：一行一个复选框
calendar.ics    空日历；把 Google/Outlook/Apple 的日历导出到这里
```

最少只需要改两处：

1. `weeklint.yaml` 的 `timezone` 改成你的 IANA 时区（例如 `Asia/Shanghai`）。
2. 把真实日历导出覆盖 `calendar.ics`。

然后写几个任务：

```markdown
- [ ] 写课程论文 @due(2026-11-05T17:00) @estimate(240m) @priority(high) @tag(course)
- [ ] 准备组会汇报 @due(2026-11-03T14:00) @estimate(90m) @priority(high) @tag(research)
- [ ] 复习线性代数 @due(2026-11-06) @estimate(120m) @priority(normal)
- [ ] 买日用品 @estimate(45m) @priority(low)
```

先看这周装不装得下：

```bash
weeklint check
```

输出示例：

```text
2026-W45 · 2026-11-02 至 2026-11-08
可支配 24h30m · 任务需要 11h45m · 缺口 0m
...
```

再生成计划：

```bash
weeklint plan
```

打开 `.weeklint/report.html`。同目录还有：

| 文件 | 用途 |
|---|---|
| `.weeklint/plan.json` | 机器可读的计划、未排程、findings；下次 `plan` 会锁定其中的块 |
| `.weeklint/plan.ics` | 导入日历；每个任务块一个事件 |
| `.weeklint/plan.md` | 按天分组的纯文本计划 |
| `.weeklint/report.html` | 单文件报告，可直接发给别人或打印 |

只想看今天：

```bash
weeklint today
```

## 配置

最小配置：

```yaml
version: 1
timezone: Asia/Shanghai
```

常用字段：

```yaml
version: 1
timezone: Asia/Shanghai
planning:
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
  task_file: tasks.md
  calendar_files: [calendar.ics]
  output_dir: .weeklint
```

完整字段、默认值、校验错误见 [SPEC.md](SPEC.md) 第 2 节。所有路径相对 `weeklint.yaml` 所在目录解析；`~` 会展开。

## 命令

```text
weeklint [--config PATH] [--json] [--now ISO] [--week YYYY-Www] [--no-color] <command>

weeklint init [--dir PATH]
weeklint check [--week YYYY-Www]
weeklint plan [--week YYYY-Www] [--no-report]
weeklint today
weeklint explain <task-id-or-title-substring> [--week YYYY-Www]
weeklint doctor
weeklint version
```

- 全局参数可以写在命令前或后。
- `--json`：stdout 只输出一个 JSON 对象；错误仍写 stderr。
- `--now`：覆盖「现在」，用于复现和测试；支持带偏移的 ISO 8601 或纯日期。
- `--week`：指定 ISO 周；`2026-W53` 合法，`2027-W53` 不存在。
- 退出码：`0` 正常；`1` 至少一个 error finding；`2` 配置/输入/写文件错误；`3` 未预期内部错误。

## 升级

当前从源码安装：在仓库目录执行 `git pull` 后重新 `python -m pip install -e .`。未来发布到 PyPI 后，升级命令是 `python -m pip install -U weeklint`。升级不会改动你的 `weeklint.yaml`、`tasks.md` 或 `calendar.ics`；先看 [CHANGELOG.md](CHANGELOG.md) 的变更和 [docs/deviations.md](docs/deviations.md) 的行为差异。

## 报告

`report.html` 是单文件，直接双击打开即可：

- 浅色/深色跟随系统；所有颜色来自 CSS token；
- 375px 单列，无横向滚动；
- 打印时不截断块，正文不小于 11pt；
- 没有 `<script>`、没有外部 CSS/JS/字体/图片、没有网络请求；
- 所有任务标题、标签、文件名都经过 HTML 转义。

设计约束和 token 清单见 [DESIGN.md](DESIGN.md)。

## 隐私与安全

- **没有网络调用**：不导入 `requests`/`httpx`/`socket` 客户端；测试会把 `socket.socket` 换成抛异常的函数。
- **没有账号、没有 OAuth、没有 LLM、没有遥测**：不需要 API key。
- **只读输入**：只读 `task_file` 和 `calendar_files`；只写 `output_dir`。
- **不写回日历**：`plan.ics` 是导出文件，不会修改你的源日历。
- **原子写**：临时文件 + `os.replace`；旧 `plan.json` 先备份为 `plan.prev.json`。
- **错误不泄露内容**：错误信息只带路径、行号、字段名，不打印整份任务文件。

## 已知限制

- ICS 的 `RECURRENCE-ID` 单次改期不合并，会跳过并 warning；那一周仍按原时间占用。
- RRULE 只展开本周，单个事件本周最多 1000 个实例；超出截断并 warning。
- 一次只处理一个任务文件、最多 20 个日历文件。
- 没有 Windows 实机验证；CI 覆盖 `windows-latest`，但本地开发机是 macOS。
- 不是 CalDAV 客户端；需要手动导出 `.ics`。
- `plan.ics` 用 UTC 时间，不含 VTIMEZONE；导入后由客户端换算本地时间。

实现与规格的偏差逐条记录在 [docs/deviations.md](docs/deviations.md)。

## 复现截图

```bash
python -m weeklint plan --config examples/weeklint.yaml --now 2026-11-02T08:30:00-05:00
```

然后用浏览器打开 `examples/.weeklint/report.html`。截图使用 Playwright 的 1280px 浅色、1280px 深色和 375px 视口，未编辑图片内容。示例输入在 [examples/](examples/)。

## 文档

- [SPEC.md](SPEC.md)：唯一行为契约（配置、CLI、JSON、错误码、测试要求）。
- [DESIGN.md](DESIGN.md)：报告视觉契约、token、375px/打印规则。
- [docs/features.md](docs/features.md)：已实现功能与边界。
- [docs/development.md](docs/development.md)：开发、测试、发布。
- [docs/deviations.md](docs/deviations.md)：实现偏差与原因。
- [docs/external-apis.md](docs/external-apis.md)：外部格式/库的核实记录。
- [docs/选题.md](docs/选题.md)：选题过程、竞品与评分。
- [CHANGELOG.md](CHANGELOG.md)：版本变更。
- [examples/](examples/)：可复现的示例输入与截图命令。
- [docs/screenshots.md](docs/screenshots.md)：浅色、深色、375px 三张真实截图。

## 开发

```bash
python -m pytest -q
python -m pytest -q -k "planner or report"
```

测试不访问网络、不 sleep、不依赖系统时区；时间通过 `--now` 注入，文件写入临时目录。详见 [docs/development.md](docs/development.md)。

## 许可证

[MIT](LICENSE)。你可以自由使用、修改、分发；如果它帮你少接了一个做不完的任务，那就够了。
