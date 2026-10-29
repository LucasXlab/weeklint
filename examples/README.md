# 示例

这是一个可复现的大学一周：四门课、组会、兼职、导师 meeting，以及 7 个任务。时间固定在 2026 年 11 月第一周（America/New_York）。

```bash
python -m weeklint plan --config examples/weeklint.yaml --now 2026-11-02T08:30:00-05:00
```

输出在 `examples/.weeklint/`（已被 `.gitignore` 忽略）：

- `plan.json`、`plan.ics`、`plan.md`、`report.html`

打开 `report.html` 可以看到 README 里的截图。示例故意留了一个没有 `@estimate` 的任务（「整理实验数据」），所以报告会显示一条 `task_unestimated` warning；这不是渲染错误。
