# 已核实的外部接口与标准

本项目**不发起任何网络请求**：没有大模型、没有第三方 API、没有 OAuth、没有遥测、不读取系统日历数据库。对外部世界的依赖只有文件格式、时区数据库和 Python 库。因此本文件记录的是「格式标准 + 库的实际行为」，不是 HTTP 接口。

核实日期：2026-10-29。核实环境：macOS 15（darwin 24.x），Python 3.13.5，`icalendar 6.3.2`、`python-dateutil 2.9.0.post0`、`PyYAML 6.0.3`、`rich 13.9.4`。

## 1. 网络接口

无。

- 代码中不导入 `requests`、`httpx`、`urllib.request`、`socket`、`http.client`、`aiohttp`。
- 测试 `test_cli.py::test_no_network` 在运行 `check`/`plan` 前 monkeypatch `socket.socket`，让它抛异常；命令仍成功。
- HTML 报告不引用外部 CSS/JS/字体/图片；测试断言输出不含 `http://`、`https://`、`@import`、`url(`。
- 如果未来加入任何网络接口，必须先更新本文件、SPEC 和 mock 规则。

## 2. iCalendar（RFC 5545）

- 标准：RFC 5545《Internet Calendars and Scheduling Core Object Specification》 <https://www.rfc-editor.org/rfc/rfc5545>
- 实现库：`icalendar` 6.3.2 <https://icalendar.readthedocs.io/>
- 支持范围（v0.1.0）：
  - `VEVENT` 的 `UID`、`SUMMARY`、`DTSTART`、`DTEND`、`DURATION`、`RRULE`、`EXDATE`、`RDATE`、`STATUS`、`TRANSP`、`RECURRENCE-ID`；
  - `DTSTART` 为 `DATE`（全天事件）或 `DATE-TIME`（带 `TZID`、带 `Z`、浮动）；
  - `RRULE` 的 `FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`、`INTERVAL`、`COUNT`、`UNTIL`、`BYDAY`；仅用 `dateutil.rrule` 支持且本项目测试覆盖的组合。
  - `EXDATE`、`RDATE`；`RECURRENCE-ID` 的覆盖实例不合并，跳过并 warning（见 SPEC 5.3）。
- 不声称支持：`VTODO`、`VJOURNAL`、`VFREEBUSY`、`VALARM`、时区自定义 `VTIMEZONE` 的完整解析（交给 `icalendar`/`zoneinfo`）、复杂的 `BYSETPOS`/`BYYEARDAY` 组合、跨时区的 `RECURRENCE-ID` 合并。
- 实际验证（2026-10-29，本地脚本）：
  - 解析 `DTSTART;TZID=America/New_York:20260301T090000`，`icalendar` 返回 `2026-03-01 09:00:00-05:00`，`tzinfo` 为 `America/New_York`；
  - 用 `dateutil.rrule.rrulestr` 展开 `FREQ=WEEKLY;COUNT=4`，跨 2026-03-08 美国春令时，得到 `09:00-05:00`、`09:00-04:00`、`09:00-04:00`、`09:00-04:00`，说明库会保留本地墙钟时间并切换偏移；
  - `EXDATE` 在 `icalendar` 中为 `vDDDLists`，通过 `event.get('EXDATE').dts` 取 `vDDDTypes.dt`，不能直接迭代属性对象。
- 已知边界（写进 deviations）：
  - 同一 UID 的多个 `RECURRENCE-ID` 覆盖不会替换主事件，主事件仍会生成；v0.1.0 只 warning，不合并；
  - 重复事件展开上限 1000 次，超过截断并 warning；
  - 全天事件的 `DTEND` 按 RFC 为「不含」的日期，代码按此处理。

## 3. ISO 8601 日期时间

- 标准：ISO 8601-1:2019 / ISO 8601-2:2019 <https://www.iso.org/iso-8601-date-and-time-format.html>
- 使用范围：CLI `--now`、配置中的时间、任务 `@due`、JSON 输出、ICS `DTSTAMP`。
- 解析规则：
  - 接受 `YYYY-MM-DD`、`YYYY-MM-DDTHH:MM`、`YYYY-MM-DDTHH:MM:SS`，可带 `Z` 或 `±HH:MM`；
  - 不带偏移按配置时区解释；
  - 日期形式（无时间）按当天 `23:59` 解释，仅用于任务截止；
  - 输出统一带偏移，例如 `2026-11-04T23:59:00+08:00`；
  - 拒绝 `2026-02-30`、`25:00`、无年份等非法值。
- 实际验证：Python 3.13 `datetime.fromisoformat` 支持上述格式；项目额外用正则限制不允许的写法，避免接受 `2026-11-04 17:00`（空格）这类跨平台差异。

## 4. 时区数据库（IANA tzdb）

- 标准/数据：IANA Time Zone Database <https://www.iana.org/time-zones>
- Python：`zoneinfo.ZoneInfo` <https://docs.python.org/3/library/zoneinfo.html>
- 使用范围：配置 `timezone`、ICS `TZID`、周范围边界、DST 计算。
- 实际验证（2026-10-29）：
  - `ZoneInfo("Asia/Shanghai")`、`ZoneInfo("America/New_York")`、`ZoneInfo("UTC")` 可用；
  - `America/New_York` 2026-03-08 的本地日长度为 23 小时，2026-11-01 为 25 小时（由 `zoneinfo` 提供）。
- 不读取 `pytz`；不使用系统 `date` 命令；不依赖 `TZ` 环境变量（配置优先）。
- 如果运行环境缺少 tzdata（例如精简容器），`zoneinfo` 可能找不到时区；此时 `config_invalid_timezone`，错误信息提示安装 `tzdata` 包。README 的前置条件写明。

## 5. Python 库

| 库 | 版本（实测） | 用途 | 文档 |
|---|---|---|---|
| `icalendar` | 6.3.2 | 解析/生成 ICS | <https://icalendar.readthedocs.io/> |
| `python-dateutil` | 2.9.0.post0 | `rrule` 展开 | <https://dateutil.readthedocs.io/en/stable/rrule.html> |
| `PyYAML` | 6.0.3 | 读取 `weeklint.yaml`（只用 `safe_load`） | <https://pyyaml.org/wiki/PyYAMLDocumentation> |
| `rich` | 13.9.4 | 终端表格/颜色；`--json` 不使用 | <https://rich.readthedocs.io/> |
| `pytest` | 8.4.2 | 测试 | <https://docs.pytest.org/> |

- 只用 `yaml.safe_load`，不用 `load`/`unsafe_load`；不执行 YAML 标签。
- `rich` 只在人类可读输出时使用；`--json`、`--no-color`、非 TTY 时降级为纯文本。
- 不引入 `requests`、`httpx`、`beautifulsoup4`、`pandas`、`numpy` 等运行时不需要的包。

## 6. 文件格式

- Markdown 任务文件：不是标准，本项目自定义一行一任务的语法，见 SPEC 3.1。没有外部接口需要核实。
- `weeklint.yaml`：YAML 1.2 子集，`safe_load`；字段和校验见 SPEC 2.2。
- 输出 `plan.ics`：按 RFC 5545 生成，`,` `;` `\` 换行转义；`DTSTAMP` 用 UTC `Z`。
- 输出 `plan.json`：UTF-8，缩进 2；时间带偏移。
- 输出 `report.html`：单文件，无外部资源；HTML5，`lang="zh-CN"`。

## 7. 未核实/不承诺

- 没有在 Windows 实机跑过（CI 会跑 `windows-latest`，但本地验证以 macOS/Linux 为主）；路径分隔符和终端编码由 `pathlib`/UTF-8 处理。
- 没有验证所有日历厂商导出的 `.ics`；只按 RFC 5545 和上述库的行为实现。遇到解析失败，`doctor` 会给出文件、UID 和错误原因。
- 没有实现 CalDAV/Google Calendar API；未来若加，必须先核实 OAuth scope、速率限制、错误格式，并补 mock。
