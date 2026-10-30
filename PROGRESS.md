# 进度

更新时间：2026-10-30

## 阶段

- [x] Stage 1 选题：`docs/选题.md`，8 个候选、竞品、评分、适用/不适用。
- [x] Stage 2 规格：`SPEC.md`、`DESIGN.md`、`docs/external-apis.md`；独立规格审稿并修正（`notes/规格审稿.md`）。
- [x] Stage 2 评审门：规格摘要已准备，等待/已获得继续指令（本会话用户已说「继续」）。
- [x] Stage 3 实现：配置、任务、ICS、预算、排程、报告、CLI 全部落地；中文行为向提交。
- [x] Stage 3 测试：166 个测试通过（2026-10-30，`python -m pytest -q`）。
- [x] Stage 4 冷启动安装实录：`notes/安装实录.md`，全新 clone 到首次 check 5 秒。
- [x] Stage 4 真实使用 10 次：`notes/真实使用.md`，覆盖正常 + 9 类异常/边界。
- [x] Stage 4 三个独立审查：正确性/安全数据/新用户三个独立子代理；复现与修复见 `notes/审查修复.md`。
- [x] Stage 5 README/README_EN 最终校对、截图复核、发布材料；本地 tag `v0.1.0`。

## 当前状态

- 项目根：`/Users/you/NO/weeklint`，独立 git 仓库，本地提交完成，无 remote。
- 版本：0.1.0；`pyproject.toml` 与 `src/weeklint/__init__.py` 一致。
- 测试：166 passed；无 skip、无网络、无 sleep。
- 输出：`plan.json`、`plan.ics`、`plan.md`、`report.html` 已用真实示例生成；截图在 `assets/`。
- 已知问题：见 `docs/deviations.md`，没有未记录的严重缺陷。

## 下一步

1. 保持本地 tag `v0.1.0`，不推送、不发布。
2. 发布材料只留在 `launch/`；按用户确认后再考虑 GitHub/PyPI。
3. 已知限制见 `docs/deviations.md` 与 `notes/审查修复.md`。
5. 统一术语、最终测试三连、打本地 tag v0.1.0。

## 待补测试（已知缺口）

- ICS `too_many_events` / `recurrence_truncated` 上限分支（D8）。
- `today` 的 `next` 在块进行中的边界（当前只测未来块）。
- `WEEKLINT_DEBUG=1` 的内部错误 traceback 分支（只测了非法值）。
- `output_dir` 只读/写失败的真实权限分支（CI 以 root 运行时不可靠）。
