from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weeklint.errors import WeeklintError
from weeklint.tasks import derive_id, load_tasks, parse_task_text

TZ = ZoneInfo("America/New_York")


def parse(text: str):
    return parse_task_text(text, TZ, 60)


def test_parse_basic():
    tasks = parse("- [ ] 写论文 @due(2026-11-05T17:00) @estimate(90m) @priority(high) @tag(course)\n")
    task = tasks[0]
    assert task.title == "写论文"
    assert task.estimate_minutes == 90
    assert task.priority == "high"
    assert task.tags == ["course"]
    assert task.due.hour == 17
    assert task.completed is False
    assert task.id.startswith("t-")


def test_parse_completed_and_ignored_lines():
    tasks = parse("# heading\n- [x] 已完成\n- [ ] 未完成\n普通文字\n")
    assert len(tasks) == 2
    assert tasks[0].completed is True
    assert tasks[1].completed is False


def test_parse_defaults():
    task = parse("- [ ] 任务\n")[0]
    assert task.estimate_minutes == 60
    assert task.priority == "normal"
    assert task.estimated is False
    assert task.due is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("90m", 90), ("1h", 60), ("1h30m", 90), ("1.5h", 90), ("2H", 120), ("  30m  ", 30)],
)
def test_estimate_formats(value, expected):
    task = parse(f"- [ ] x @estimate({value})\n")[0]
    assert task.estimate_minutes == expected
    assert task.estimated is True


@pytest.mark.parametrize("value", ["0m", "4m", "2401m", "abc", "1h30", "", "1.5", "3d"])
def test_estimate_invalid(value):
    with pytest.raises(WeeklintError) as exc:
        parse(f"- [ ] x @estimate({value})\n")
    assert exc.value.code == "task_invalid_estimate"


def test_due_date_means_end_of_day():
    task = parse("- [ ] x @due(2026-11-04)\n")[0]
    assert task.due.isoformat() == "2026-11-04T23:59:00-05:00"


def test_due_naive_datetime_uses_config_tz():
    task = parse("- [ ] x @due(2026-11-04T17:00)\n")[0]
    assert task.due.isoformat() == "2026-11-04T17:00:00-05:00"


def test_due_with_offset_converts():
    task = parse("- [ ] x @due(2026-11-04T17:00:00+08:00)\n")[0]
    assert task.due.isoformat() == "2026-11-04T04:00:00-05:00"


@pytest.mark.parametrize("value", ["2026-02-30", "2026-13-01", "25:00", "2026-11-04 17:00", "tomorrow", ""])
def test_due_invalid(value):
    with pytest.raises(WeeklintError) as exc:
        parse(f"- [ ] x @due({value})\n")
    assert exc.value.code == "task_invalid_due"


def test_priority_invalid():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] x @priority(urgent)\n")
    assert exc.value.code == "task_invalid_priority"


def test_tags_and_id():
    task = parse("- [ ] x @tag(a) @tag(B-2) @id(my-task_1)\n")[0]
    assert task.tags == ["B-2", "a"]
    assert task.id == "my-task_1"


@pytest.mark.parametrize("value", ["", "has space", "a;b", "a" * 65, "中文"])
def test_id_invalid(value):
    with pytest.raises(WeeklintError) as exc:
        parse(f"- [ ] x @id({value})\n")
    assert exc.value.code == "task_invalid_id"


def test_tag_invalid():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] x @tag(a b)\n")
    assert exc.value.code == "task_invalid_tag"


def test_unknown_metadata():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] x @owner(me)\n")
    assert exc.value.code == "task_unknown_metadata"
    assert exc.value.detail["key"] == "owner"


def test_duplicate_metadata():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] x @priority(normal) @priority(normal)\n")
    assert exc.value.code == "task_parse_error"


def test_title_can_contain_at_sign():
    task = parse("- [ ] 发邮件给 a@b.com\n")[0]
    assert task.title == "发邮件给 a@b.com"


def test_empty_title():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] @estimate(30m)\n")
    assert exc.value.code == "task_parse_error"


def test_too_long_title():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] " + "x" * 201 + "\n")
    assert exc.value.code == "task_parse_error"


def test_duplicate_derived_ids():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] 同名\n- [ ] 同名\n")
    assert exc.value.code == "task_duplicate_id"


def test_explicit_id_duplicate():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] a @id(one)\n- [ ] b @id(one)\n")
    assert exc.value.code == "task_duplicate_id"


def test_derive_id_is_stable_and_normalized():
    assert derive_id("  ＡＢＣ  ") == derive_id("abc")


def test_too_many_open_tasks():
    text = "".join(f"- [ ] 任务{i}\n" for i in range(501))
    with pytest.raises(WeeklintError) as exc:
        parse(text)
    assert exc.value.code == "too_many_tasks"


def test_load_tasks_missing(tmp_path):
    with pytest.raises(WeeklintError) as exc:
        load_tasks(tmp_path / "nope.md", TZ, 60)
    assert exc.value.code == "task_file_not_found"


def test_load_tasks_not_utf8(tmp_path):
    path = tmp_path / "tasks.md"
    path.write_bytes(b"\xff\xfe- [ ] x")
    with pytest.raises(WeeklintError) as exc:
        load_tasks(path, TZ, 60)
    assert exc.value.code == "task_file_encoding"


def test_load_tasks_too_large(tmp_path):
    path = tmp_path / "tasks.md"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(WeeklintError) as exc:
        load_tasks(path, TZ, 60)
    assert exc.value.code == "task_file_too_large"


def test_dst_nonexistent_due_is_shifted_and_flagged():
    task = parse_task_text("- [ ] 春季任务 @due(2026-03-08T02:30)\n", ZoneInfo("America/New_York"), 60)[0]
    assert task.due is not None
    assert (task.due.hour, task.due.minute) == (3, 30)
    assert task.dst_adjusted is True


def test_dst_ambiguous_due_uses_first_instance_and_is_flagged():
    task = parse_task_text("- [ ] 秋季任务 @due(2026-11-01T01:30)\n", ZoneInfo("America/New_York"), 60)[0]
    assert task.due is not None
    assert task.due.utcoffset() is not None
    assert task.due.utcoffset().total_seconds() == -4 * 3600
    assert task.dst_adjusted is True


def test_explicit_offset_due_is_not_flagged():
    task = parse_task_text("- [ ] 秋季任务 @due(2026-11-01T01:30-05:00)\n", ZoneInfo("America/New_York"), 60)[0]
    assert task.due is not None
    assert task.due.utcoffset().total_seconds() == -4 * 3600
    assert task.dst_adjusted is False


def test_unclosed_metadata_is_an_error():
    with pytest.raises(WeeklintError) as exc:
        parse("- [ ] 坏任务 @estimate(30m\n")
    assert exc.value.code == "task_parse_error"
    assert "没有闭合" in exc.value.message
    assert exc.value.detail["line"] == 1
