from datetime import datetime
from pathlib import Path

from wechat_core import SeenState, classify_message, event_fingerprint, next_run_at, normalize_config, scheduled_slot


def test_default_schedule_is_half_hour_from_nine_to_twenty():
    cfg = normalize_config({})
    assert cfg["start_time"] == "09:00"
    assert cfg["end_time"] == "20:00"
    assert cfg["interval_minutes"] == 30


def test_schedule_includes_twenty_hundred_but_not_after():
    tz_now = datetime.now().astimezone()
    at_20 = tz_now.replace(hour=20, minute=0, second=0, microsecond=0)
    after = tz_now.replace(hour=20, minute=1, second=0, microsecond=0)
    assert scheduled_slot(at_20, "09:00", "20:00", 30) == at_20
    assert scheduled_slot(after, "09:00", "20:00", 30) is None


def test_next_run_rolls_to_next_day_after_window():
    tz_now = datetime.now().astimezone().replace(hour=21, minute=10, second=0, microsecond=0)
    nxt = next_run_at(tz_now, "09:00", "20:00", 30)
    assert nxt.date() > tz_now.date()
    assert (nxt.hour, nxt.minute) == (9, 0)


def test_config_keeps_only_explicit_authorized_groups():
    cfg = normalize_config(
        {
            "bindings": [
                {"project_id": "p1", "project_name": "项目一", "group_name": "项目群"},
                {"project_id": "p1", "project_name": "项目一", "group_name": "项目群"},
                {"project_id": "", "group_name": "不应采集"},
            ]
        }
    )
    assert cfg["bindings"] == [{"project_id": "p1", "project_name": "项目一", "group_name": "项目群"}]


def test_rule_first_message_classification():
    categories = classify_message("确认一下，0815资料包继续作为基准，0720版本不要了，周五前完成。")
    assert "decision" in categories
    assert "change" in categories
    assert "confirmation" in categories
    assert "deadline" in categories


def test_fingerprint_is_stable():
    kwargs = dict(
        project_id="p1",
        group_name="项目群",
        sender="葛工",
        text="  0815资料包   为准 ",
        observed_at="2026-09-24T09:30:16+08:00",
    )
    first = event_fingerprint(**kwargs)
    second = event_fingerprint(**kwargs)
    assert first == second
    assert len(first) == 64


def test_seen_state_roundtrip(tmp_path: Path):
    state = SeenState(tmp_path / "seen.json")
    state.save({"b", "a"})
    assert state.load() == {"a", "b"}
