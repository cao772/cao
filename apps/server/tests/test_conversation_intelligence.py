import sqlite3

from conversation_intelligence import insert_event, project_summary, search_messages


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _event(text="0815资料包继续作为当前基准"):
    return {
        "event_fingerprint": "a" * 64,
        "project_id": "low-voltage",
        "project_name": "低电压项目",
        "source": "wechat_personal",
        "conversation_name": "低电压项目群",
        "sender": "葛工",
        "message_type": "text",
        "text": text,
        "observed_at": "2026-09-24T09:30:00+08:00",
        "user_id": "cyh",
        "device_id": "mac",
        "categories": ["decision", "change"],
        "metadata": {"collector": "wechat-mac-helper"},
    }


def test_insert_is_idempotent_by_fingerprint():
    conn = _conn()
    first_id, first_dup = insert_event(conn, _event(), "2026-09-24T01:30:01+00:00")
    second_id, second_dup = insert_event(conn, _event(), "2026-09-24T01:31:01+00:00")
    assert first_dup is False
    assert second_dup is True
    assert first_id == second_id


def test_search_finds_message_by_content_and_group():
    conn = _conn()
    insert_event(conn, _event(), "2026-09-24T01:30:01+00:00")
    by_content = search_messages(conn, "low-voltage", "0815 基准")
    by_group = search_messages(conn, "low-voltage", "低电压项目群")
    assert len(by_content) == 1
    assert by_content[0]["sender"] == "葛工"
    assert len(by_group) == 1


def test_summary_keeps_project_communication_categories():
    conn = _conn()
    insert_event(conn, _event(), "2026-09-24T01:30:01+00:00")
    summary = project_summary(conn, "low-voltage")
    assert summary["message_count"] == 1
    assert summary["group_count"] == 1
    assert {item["type"] for item in summary["categories"]} == {"decision", "change"}
