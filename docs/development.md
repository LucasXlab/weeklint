# 开发与发布

## 环境

- Python 3.11+（CI 覆盖 3.11、3.12、3.13）
- 依赖：`icalendar>=6.1,<7`、`python-dateutil>=2.9,<3`、`PyYAML>=6.0,<7`、`rich>=13.9,<14`
- 测试：`pytest>=8.3,<9`

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

Windows 上激活命令是 `.venv\Scripts\activate`。

## 目录

```text
src/weeklint/
  cli.py       命令行、参数、退出码、错误信封
  config.py    YAML 校验、路径解析
  tasks.py     Markdown 任务解析
  ics.py       ICS 解析/展开/生成
  budget.py    周范围、忙闲、需求、findings
  planner.py   切块、排序、锁定、回滚
  report.py    plan.json / plan.md / plan.ics / report.html
  model.py     数据对象
  errors.py    WeeklintError
  timeutil.py  DST 规则、ISO 解析
tests/         按模块划分，全部使用临时目录和 --now
docs/          SPEC、DESIGN、功能、外部依赖、偏差
```

## 测试约定

- 不访问网络。`test_cli.py::test_no_network` 在运行命令前把 `socket.socket` 换成抛异常的函数。
- 不固定 sleep；时间一律通过 `--now` / `WEEKLINT_NOW` 注入。
- 不依赖系统时区；测试固定 `America/New_York`，另测 `Asia/Shanghai` 的解析。
- 临时目录用 pytest `tmp_path`，不写仓库内文件。
- 失败路径必须有测试：坏 YAML、坏 ICS、缺失文件、非法 `--week`、非法 `--now`、写文件失败、锁冲突。
- 报告测试断言：无 `<script>`、无 `http://`/`https://`、无 `url(`、包含 token、转义用户数据、375px 媒体查询。
- ICS 测试用 `icalendar` 重新解析生成的 `plan.ics`，不只看字符串。

运行单个模块：

```bash
python -m pytest tests/test_planner.py -q
python -m pytest -q -k "dst or lock"
```

## 代码风格

- 类型注解 + `from __future__ import annotations`。
- 用户可见错误用 `WeeklintError(code, message, detail)`，不要 `print` 后退出。
- 不在代码里硬编码用户路径、时间、颜色；报告颜色只来自 CSS token。
- 新增 finding 必须同时更新 `SPEC.md` 5.3、`docs/features.md`、测试。
- 新增配置字段必须同时更新 `SPEC.md` 2.2、默认值、错误码、`init` 模板、测试。

## 版本与发布

- 版本号在 `pyproject.toml` 和 `src/weeklint/__init__.py` 保持一致；`CLI --version` 读取后者。
- 发布前：`python -m pytest -q` 连续三次通过；`python -m build` 成功；在空目录用 `pip install dist/*.whl` 跑 `weeklint init/check/plan`。
- 打标签：`git tag v0.1.0`。`.github/workflows/release.yml` 会校验标签与 `pyproject.toml` 版本一致，跑测试、构建，并用 `softprops/action-gh-release` 上传 `dist/*`。
- CHANGELOG 按 Keep a Changelog；版本按 SemVer。
- 本项目当前只做本地提交，不 push、不发布。

## 设计文档

- `SPEC.md` 是唯一契约；实现与测试冲突时以 SPEC 为准，改 SPEC 必须同步改测试和 `docs/deviations.md`。
- `DESIGN.md` 是报告的唯一视觉契约；CSS token 清单在 2.5 节，测试会断言。
- 任何外部格式/库行为记录在 `docs/external-apis.md`，附核实日期和版本。
