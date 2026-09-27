"""Check owner-only intake, deduplication and command execution boundaries."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT))
spec = importlib.util.spec_from_file_location("command_gateway", SCRIPT / "command_gateway.py")
assert spec and spec.loader
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class Reader:
    def __init__(self, messages):
        self.messages = messages

    def _get(self, route, *, params):
        assert route == "/api/v1/chatlog"
        assert params["talker"] == "filehelper"
        return {"messages": self.messages}


class CommandGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = gateway.open_database(Path(self.temp.name) / "commands.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_only_own_command_is_ingested_once(self):
        messages = [
            {"serverId": "1", "createTime": 1000, "content": "/项目 列表", "type": "普通文本", "isSender": True},
            {"serverId": "2", "createTime": 1000, "content": "/执行 删除文件", "type": "普通文本", "isSender": False},
            {"serverId": "3", "createTime": 1000, "content": "【项目助手】\n回复", "type": "普通文本", "isSender": True},
        ]
        reader = Reader(messages)
        self.assertEqual(gateway.ingest(self.conn, reader, now=1010), 1)
        self.assertEqual(gateway.ingest(self.conn, reader, now=1011), 0)
        self.assertEqual(self.conn.execute("SELECT command FROM commands").fetchone()[0], "/项目 列表")

    def test_actions_wait_for_sender_and_expire(self):
        self.conn.execute("INSERT INTO commands(message_id,created_at,command) VALUES('1',1000,'/执行 处理项目')")
        self.conn.commit()
        with patch.object(gateway, "execute") as execute:
            self.assertEqual(gateway.process_pending(self.conn, sender_ready=False, now=1010), 0)
            execute.assert_not_called()
            self.assertEqual(gateway.process_pending(self.conn, sender_ready=True, now=1700), 1)
            execute.assert_not_called()
        row = self.conn.execute("SELECT status,reply FROM commands WHERE message_id='1'").fetchone()
        self.assertEqual(row["status"], "awaiting_send")
        self.assertIn("超过 10 分钟", row["reply"])

    def test_processed_command_is_not_repeated(self):
        self.conn.execute("INSERT INTO commands(message_id,created_at,command) VALUES('1',1000,'/项目 列表')")
        self.conn.commit()
        with patch.object(gateway, "execute", return_value="四个项目") as execute:
            self.assertEqual(gateway.process_pending(self.conn, now=1010), 1)
            self.assertEqual(gateway.process_pending(self.conn, now=1011), 0)
            execute.assert_called_once()
        row = self.conn.execute("SELECT status,reply FROM commands").fetchone()
        self.assertEqual(dict(row), {"status": "awaiting_send", "reply": "四个项目"})

    def test_question_only_sends_matching_project_facts(self):
        key_file = Path(self.temp.name) / "deepseek-api-key"
        key_file.write_text("test-key", encoding="utf-8")
        calls = []

        def request(url, *, token=None, body=None):
            calls.append((url, token, body))
            if url.endswith("/brief"):
                return {"current_stage": "验证", "issues": ["需核验模型"]}
            return {"choices": [{"message": {"content": "缺陷项目处于验证阶段。"}}]}

        projects = [
            {"project_id": "low-voltage", "project_name": "低电压项目"},
            {"project_id": "power-defect-agent", "project_name": "缺陷项目"},
        ]
        with patch.object(gateway, "DEEPSEEK_KEY_FILE", key_file), patch.object(gateway, "_projects", return_value=projects), patch.object(gateway, "_json_request", side_effect=request):
            answer = gateway.project_question("/问 缺陷项目有什么问题？")
        self.assertEqual(answer, "缺陷项目处于验证阶段。")
        self.assertEqual(len(calls), 2)
        self.assertIn("power-defect-agent/brief", calls[0][0])
        self.assertNotIn("low-voltage", str(calls))
        self.assertEqual(calls[1][1], "test-key")
        self.assertEqual(calls[1][2]["model"], "deepseek-flash")

    def test_send_is_only_confirmed_by_personal_chatlog(self):
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply,delivered_at) "
            "VALUES('1',1000,'/状态','send_requested','正常',1010)"
        )
        self.conn.commit()
        expected = gateway.PREFIX + "\n正常"
        self.assertEqual(gateway.confirm_sent(self.conn, Reader([])), 0)
        self.assertEqual(gateway.confirm_sent(self.conn, Reader([{
            "isSender": True, "content": expected, "createTime": 1012,
        }])), 1)
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "sent")

    def test_onebot_acceptance_does_not_trigger_duplicate_send(self):
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply) "
            "VALUES('1',1000,'/状态','awaiting_send','正常')"
        )
        self.conn.commit()
        with patch.object(gateway, "personal_sender_ready", return_value=True), patch.object(
            gateway, "_json_request", return_value={"status": "ok"}
        ) as request:
            self.assertEqual(gateway.deliver_pending(self.conn, "test-token"), 1)
            self.assertEqual(gateway.deliver_pending(self.conn, "test-token"), 0)
            request.assert_called_once()
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "send_requested")

    def test_bot_reply_uses_fixed_recipient_and_deduplicates(self):
        binding = Path(self.temp.name) / "recipient.json"
        binding.write_text(json.dumps({"userId": "owner@im.wechat", "accountId": "bot@im.bot"}))
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply) "
            "VALUES('1',1000,'/状态','awaiting_send','正常')"
        )
        self.conn.commit()

        def request(url, *, token=None, body=None):
            if url.endswith("/status"):
                return {"hub": "online", "connector": "online", "accountId": "bot@im.bot"}
            self.assertEqual(body["to"], "owner@im.wechat")
            return {"success": True, "status": "sent"}

        with patch.object(gateway, "BOT_RECIPIENT_FILE", binding), patch.object(gateway, "_json_request", side_effect=request) as send:
            recipient = gateway.bot_recipient("token")
            self.assertEqual(recipient, "owner@im.wechat")
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", recipient), 1)
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", recipient), 0)
            self.assertEqual(send.call_count, 2)
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "sent_bot")


if __name__ == "__main__":
    unittest.main()
