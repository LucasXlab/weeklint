# 实现偏差记录

编号在 v0.1.0 内稳定。每条写「偏差、原因、影响、测试/文档」。

## D1. `plan.ics` 使用 UTC 时间，不生成 VTIMEZONE

- **偏差**：SPEC 早期版本要求 `DTSTART;TZID=<timezone>`；实现改为 `DTSTART:...Z`。
- **原因**：RFC 5545 要求 TZID 可解析，没有 `VTIMEZONE` 的 TZID 在 Apple/Outlook 上可能导入失败。生成完整 VTIMEZONE 成本高且容易错；UTC 时间所有客户端都能正确换算。
- **影响**：导入后显示的是本地时间，但 ICS 文本里是 UTC；用户若手工编辑需注意。
- **验证**：`tests/test_report.py::test_write_files_and_ics` 用 `icalendar` 重新解析并断言 `DTSTART` 以 `Z` 结尾；`docs/external-apis.md` 记录。

## D2. 新增 `task_unscheduled` error finding

- **偏差**：原 SPEC 的 plan 退出码写「任务未排完 → 1」，但 5.3 没有对应 finding。
- **原因**：`max_tasks_per_day` / `max_deep_work_minutes_per_day` 可以在 `gapMinutes=0` 时让任务整条进 `unscheduled`，没有 error 会让 check 退 0、plan 退 1，用户无法解释。
- **影响**：plan 的 findings 多一个 `task_unscheduled`（severity=error，含 taskId、剩余分钟、原因）；check 不产生它。
- **验证**：`tests/test_planner.py::test_deep_work_limit_unscheduled`、`test_task_limit_unscheduled`；SPEC 5.3/6.5 已同步。

## D3. 被排除的周末不再产生 `no_work_hours`

- **偏差**：原逻辑对 `include_weekends=false` 的周六/周日也发 `no_work_hours` warning。
- **原因**：默认配置下每周固定两条噪音，用户无法关闭；周末不排是配置意图，不是异常。
- **影响**：只有「工作日（或 include_weekends=true 的周末）工作时间为空」才 warning；`days[]` 仍输出周末 0 分钟。
- **验证**：`tests/test_budget.py::test_no_work_hours_for_weekday`；周末案例断言无 warning。

## D4. `--now` 接受纯日期

- **偏差**：SPEC 4.1 只写 ISO 8601 时间；实现额外接受 `YYYY-MM-DD`，按当天 00:00。
- **原因**：手工复现「某天早上」的场景更省事，且不改变带时间的行为。
- **影响**：`--now 2026-11-02` 等价于 `2026-11-02T00:00:00<配置时区>`；非法日期仍 `invalid_now`。
- **验证**：`tests/test_cli.py::test_env_config_and_now` 使用完整时间；`resolve_now` 对日期分支有单元覆盖需求（见 PROGRESS 待办）。

## D5. `plan` 的锁文件与陈旧锁

- **偏差**：原 SPEC 未规定并发写；实现增加 `output_dir/.lock`（`O_CREAT|O_EXCL`），内容为 PID + 开始时间，超过 10 分钟视为陈旧并删除 + warning `stale_lock_removed`。
- **原因**：两个 `plan` 并发会互相覆盖 `plan.json`/`plan.prev.json`，丢失锁定块。
- **影响**：锁存在时 `plan_locked` 退 2；崩溃留下的锁最多阻塞 10 分钟；锁不跨机器。
- **验证**：`tests/test_cli.py::test_plan_lock`；`tests/test_planner.py::test_lock_second_run_idempotent`。

## D6. `output_dir_unverified` 是 doctor 的 warning，不在错误码表

- **偏差**：SPEC 4.2 要求 doctor 判断输出目录可写；5.3 的 finding 枚举原本没有对应码。
- **原因**：POSIX 上不创建文件很难可靠判断可写；`os.access` 在 ACL/只读挂载下可能误判。
- **影响**：doctor 只发 warning，不创建文件、不因它退 2；真正写失败仍由 `plan` 的 `output_dir_not_writable`/`write_failed` 处理。
- **验证**：`tests/test_cli.py::test_doctor`；`docs/external-apis.md` 记录判断方式。

## D7. HTML 报告只从 `plan` 生成

- **偏差**：`report.html` 是 `plan` 的产物；`check` 不生成报告。
- **原因**：报告需要块、未排程、锁定状态，这些只有 plan 有；check 只做可行性判断。
- **影响**：想先看报告必须跑 `plan`（会写文件）。`--no-report` 可跳过 HTML，只写 JSON/ICS/MD。
- **验证**：`tests/test_cli.py::test_plan_writes_files`、`test_plan_no_report`。

## D8. ICS 上限与截断

- **偏差**：SPEC 只写单文件 5 MiB/总 20 MiB、RRULE 1000 次；实现增加单文件 5000 VEVENT、展开后本周 20000 实例、本周单事件 1000 实例截断。
- **原因**：5 MiB 可以放数万事件，展开后内存/时间不可控；需要可预测的上限。
- **影响**：超限 `too_many_events` 退 2；截断只 warning `recurrence_truncated`，不静默丢。
- **验证**：`tests/test_ics.py` 的重复/EXDATE 用例；上限分支待补（见 PROGRESS）。

## D9. `RECURRENCE-ID` 覆盖不合并

- **偏差**：同一 UID 的单次改期事件被跳过并 warning，不替换主事件。
- **原因**：正确合并需要按 UID + RECURRENCE-ID 建索引，并处理时区/全天/取消，v0.1 不承担这个复杂度。
- **影响**：用户若在日历里改过某一次重复事件，那一周仍按原时间占用；报告会提示 `recurrence_override_ignored`。
- **验证**：`tests/test_ics.py::test_recurrence_override_skipped`。

## D10. `plan.prev.json` 只在旧 `plan.json` 存在时创建

- **偏差**：首次 `plan` 不生成 `plan.prev.json`。
- **原因**：没有旧计划可备份；生成空文件会误导。
- **影响**：第一次运行后目录里只有四个输出文件；第二次起才有 `plan.prev.json`。
- **验证**：`tests/test_cli.py::test_plan_writes_files` 断言首次不存在；`test_write_failure_keeps_old_plan` 覆盖旧文件保留。

## D11. 输出文件权限

- **偏差**：临时文件 0600，最终 `chmod 0644` 后再 `os.replace`。
- **原因**：计划里可能有课程/工作信息，临时文件不应被同机其他用户读到；最终文件按 SPEC 0644。
- **影响**：受 umask/文件系统影响；Windows 上 chmod 语义有限。
- **验证**：`tests/test_report.py` 不直接断言权限；SPEC 4.2 记录。

## D12. 本地未在 Windows 实机验证

- **偏差**：开发机是 macOS；Windows 只在 CI 配置里覆盖。
- **原因**：没有 Windows 机器；不能声称「已实机验证」。
- **影响**：路径分隔符、终端编码、文件锁在 Windows 上可能有差异；README 写明 CI 覆盖但本地未实机验证。
- **验证**：`.github/workflows/ci.yml` 有 `windows-latest`；发布前看 CI 结果。

## D13. `doctor` 不创建文件

- **偏差**：`doctor` 用 `os.access` 判断输出目录可写，不实际写测试文件。
- **原因**：doctor 的承诺是「只读检查」；创建再删除仍可能留下痕迹或在只读介质上失败。
- **影响**：ACL/只读挂载下可能误报/漏报；真正写入失败由 plan 报错。
- **验证**：`tests/test_cli.py::test_doctor`；D6 同源。

## D14. `explain` 对已完成/范围外任务也返回解释

- **偏差**：已完成或截止晚于本周的任务不在 check 的在范围内；`explain` 仍可按 id/标题找到，返回 `blocks=[]`、`unscheduled=null` 和一句中文 `reason`。
- **原因**：用户可能想确认「这个任务为什么没排」；直接 `task_not_found` 不友好。
- **影响**：`reason` 对这两种情况分别是「任务已完成，不参与本周排程。」和「截止晚于本周，未计入本周排程。」；不新增 `status` 字段，避免偏离 6.7 契约。
- **验证**：`tests/test_cli.py::test_explain_by_id_and_title` 覆盖已排任务，`test_explain_completed` 覆盖已完成分支。

## D15. RRULE 只展开到本周结束

- **偏差**：无限 RRULE 在实例开始时间 ≥ `week.end` 时停止；不预生成未来周。
- **原因**：Weeklint 一次只回答一周；预生成会浪费内存并让 `recurrence_truncated` 口径混乱。
- **影响**：跨周查看需分别运行；`recurrence_truncated` 只统计本周内超过 1000 的实例。
- **验证**：`tests/test_ics.py::test_dst_recurring_keeps_wall_clock`、`test_recurring_with_exdate`。


## D16. `plan` 按整周排程，周中会包含过去时段

- **偏差**：`plan` 没有把 `now` 之后的时段作为起点，仍按当前 ISO 周周一到周日排；周中或周日运行会把已经过去的块写进计划。
- **原因**：SPEC 4.2 要求「同一周、第二次 `now` 可以不同，`plan.json` 除 `now`/`generatedAt`/`locked` 外完全一致」；如果按 `now` 截断，第二次运行会改变计划，违反幂等。
- **影响**：`plan` 适合周初运行；README 已改成「周一早上」，周日排下一周请用 `--week`。`today` 会把已结束/进行中的块标出来，避免误以为还没发生。
- **验证**：`tests/test_planner.py::test_lock_second_run_idempotent`；`tests/test_cli.py::test_today_next_when_block_in_progress` 覆盖 `today` 的块状态。
