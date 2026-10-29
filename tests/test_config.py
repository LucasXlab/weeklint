from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from weeklint.config import load_config
from weeklint.errors import WeeklintError


def write(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_load_defaults(make_config):
    config = make_config()
    assert config.version == 1
    assert config.tz.key == "America/New_York"
    assert config.planning.work_hours["mon"][0][0].hour == 9
    assert config.planning.calendar_files[0].name == "calendar.ics"
    assert config.planning.output_dir.name == ".weeklint"


def test_relative_paths_resolve_against_config(workspace, make_config):
    config = make_config()
    assert config.planning.task_file == (workspace / "tasks.md").resolve()


def test_unknown_key(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["typo"] = 1
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_unknown_key"


def test_unknown_top_key(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["extra"] = 1
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_unknown_key"


def test_invalid_timezone(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["timezone"] = "Mars/Olympus"
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_timezone"


def test_invalid_yaml_line(workspace):
    (workspace / "weeklint.yaml").write_text("version: 1\ntimezone: [\n", encoding="utf-8")
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_yaml"
    assert exc.value.detail["line"] == 3


def test_version_unsupported(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["version"] = 2
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_version_unsupported"


def test_work_hours_overlap(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["work_hours"]["mon"] = ["09:00-12:00", "11:00-13:00"]
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_time_range"


def test_work_hours_bad_format(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["work_hours"]["mon"] = ["9-12"]
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_time_range"


def test_max_block_smaller_than_min(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["min_block_minutes"] = 60
    data["planning"]["max_block_minutes"] = 30
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_value_out_of_range"


def test_too_many_calendars(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["calendar_files"] = [f"c{i}.ics" for i in range(21)]
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_too_many_calendars"


def test_output_dir_is_file(workspace):
    (workspace / "notadir").write_text("x", encoding="utf-8")
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["output_dir"] = "notadir"
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_path"


def test_config_not_found(tmp_path):
    with pytest.raises(WeeklintError) as exc:
        load_config(tmp_path / "nope.yaml")
    assert exc.value.code == "config_not_found"


def test_config_too_large(workspace):
    (workspace / "weeklint.yaml").write_text("version: 1\n" + ("x" * (256 * 1024 + 1)), encoding="utf-8")
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_too_large"


def test_env_config(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    config = load_config(None, {"WEEKLINT_CONFIG": str(workspace / "weeklint.yaml")})
    assert config.path == (workspace / "weeklint.yaml").resolve()


def test_bad_title(workspace):
    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["report"] = {"title": "a\nb"}
    write(workspace / "weeklint.yaml", data)
    with pytest.raises(WeeklintError) as exc:
        load_config(workspace / "weeklint.yaml")
    assert exc.value.code == "config_invalid_value"
