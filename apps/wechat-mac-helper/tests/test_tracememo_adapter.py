from datetime import datetime
import time

import pytest

from tracememo_adapter import TraceMemoError, TraceMemoReader, extract_message, resolve_bound_group


def test_only_one_exact_authorized_group_is_accepted():
    binding = {"group_name": "HY CLAW 内研"}
    rooms = [
        {"type": "group", "m_nsNickName": "HY CLAW内研", "m_nsUsrName": "111@chatroom"},
        {"type": "group", "m_nsNickName": "HY CLAW内研备份", "m_nsUsrName": "222@chatroom"},
        {"type": "user", "m_nsNickName": "HY CLAW内研", "m_nsUsrName": "somebody"},
    ]
    assert resolve_bound_group(binding, rooms)["m_nsUsrName"] == "111@chatroom"
    with pytest.raises(TraceMemoError, match="匹配数量异常"):
        resolve_bound_group(binding, rooms + [rooms[0]])
    with pytest.raises(TraceMemoError, match="匹配数量异常"):
        resolve_bound_group({"group_name": "不存在的群"}, rooms)


def test_reader_rejects_non_loopback_and_non_group_targets(tmp_path):
    with pytest.raises(TraceMemoError, match="本机"):
        TraceMemoReader(tmp_path / "token", "http://example.com:6131")
    reader = TraceMemoReader(tmp_path / "token")
    with pytest.raises(TraceMemoError, match="非群聊"):
        reader.messages("private-contact", 123)


def test_extract_text_quote_and_file_without_media_or_raw_identifiers():
    common = {"serverId": "987654", "createTime": 1790232695, "name": "同事", "localId": 4}
    text = extract_message({**common, "type": "普通文本", "content": "今天提交"}, "111@chatroom")
    quote = extract_message(
        {**common, "type": "引用消息", "contentData": {"content": "同意", "quotedContent": "请确认范围"}},
        "111@chatroom",
    )
    file = extract_message(
        {**common, "type": "文件", "contentData": {"title": "方案.pdf", "url": "private://secret"}},
        "111@chatroom",
    )
    assert text["text"] == "今天提交"
    assert text["observed_at"] == datetime.fromtimestamp(1790232695).astimezone().isoformat()
    assert quote["text"] == "同意\n引用：请确认范围"
    assert file["text"] == "分享文件：方案.pdf"
    assert "private://" not in str(file)
    assert "987654" not in str(text)
    assert extract_message({**common, "type": "图片", "contentData": {"url": "private://secret"}}, "111@chatroom") is None


def test_collector_reads_only_bound_group_and_retries_failed_upload(tmp_path, monkeypatch):
    import wechat_helper as helper

    monkeypatch.setattr(helper, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(helper, "SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(helper, "CURSOR_PATH", tmp_path / "cursors.json")
    monkeypatch.setattr(helper, "probe_wechat", lambda: {"available": True, "capture_mode": "tracememo_local_api"})
    read_targets = []
    created = int(time.time()) - 100

    class FakeReader:
        def __init__(self, *_args):
            pass

        def chatrooms(self):
            return [
                {"type": "group", "m_nsNickName": "授权项目群", "m_nsUsrName": "111@chatroom"},
                {"type": "group", "m_nsNickName": "私人群", "m_nsUsrName": "222@chatroom"},
            ]

        def messages(self, talker, _start):
            read_targets.append(talker)
            return [{"type": "普通文本", "content": "已完成验证", "serverId": "stable-id", "createTime": created}]

    monkeypatch.setattr(helper, "TraceMemoReader", FakeReader)
    uploads = []
    upload_succeeds = False

    def upload(event):
        uploads.append(event)
        return upload_succeeds

    monkeypatch.setattr(helper, "upload_event", upload)
    config = {"bindings": [{"project_id": "p1", "project_name": "项目一", "group_name": "授权项目群"}]}
    first = helper.collect_authorized_groups(config)
    assert first["failed"] == 1 and first["uploaded"] == 0
    assert not helper.CURSOR_PATH.exists()

    upload_succeeds = True
    second = helper.collect_authorized_groups(config)
    assert second["uploaded"] == 1 and second["failed"] == 0
    assert helper.CURSOR_PATH.exists()
    third = helper.collect_authorized_groups(config)
    assert third["duplicates"] == 1 and third["uploaded"] == 0
    assert read_targets == ["111@chatroom"] * 3
    assert all(event["conversation_name"] == "授权项目群" for event in uploads)
